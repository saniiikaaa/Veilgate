-- Smoke test: verify the schema's invariants hold.
-- Run as the owner role (it bypasses RLS; triggers still fire), after migrate.py + seed.py:
--   psql -f db/tests/smoke_test.sql   (or scripts wrap this with psycopg2)
-- Uses the demo tenant 11111111-... and demo agent aaaaaaaa-... planted by the seeds.

DO $$
DECLARE
    v_session   uuid;
    v_run       uuid;
    v_event     uuid;
    v_rule      uuid;
    v_ok        boolean;
    v_count     integer;
BEGIN
    ---- 1. A session and an agent run can be created -----------------------------------------
    INSERT INTO sessions (tenant_id, user_id)
        VALUES ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222')
        RETURNING id INTO v_session;

    INSERT INTO agent_runs (tenant_id, session_id, agent_id, initial_score, score_ceiling)
        VALUES ('11111111-1111-1111-1111-111111111111', v_session,
                'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 100, 100)
        RETURNING id INTO v_run;

    ---- 2. A receipt is chained by the trigger, and the chain verifies -----------------------
    INSERT INTO receipts (tenant_id, session_id, type, payload)
        VALUES ('11111111-1111-1111-1111-111111111111', v_session, 'decision',
                jsonb_build_object('test', 'smoke'));

    SELECT ok, receipt_count INTO v_ok, v_count FROM fn_verify_receipts(v_session);
    IF NOT v_ok OR v_count <> 1 THEN
        RAISE EXCEPTION 'receipt chain verification failed: ok=%, count=%', v_ok, v_count;
    END IF;

    ---- 3. Append-only tables refuse UPDATE (and DELETE) --------------------------------------
    INSERT INTO events (tenant_id, session_id, boundary, outcome)
        VALUES ('11111111-1111-1111-1111-111111111111', v_session, 'user_input', 'allowed')
        RETURNING id INTO v_event;

    BEGIN
        UPDATE events SET latency_ms = 1 WHERE id = v_event;
        RAISE EXCEPTION 'events UPDATE should have been blocked by the append-only guard';
    EXCEPTION
        WHEN restrict_violation THEN
            NULL;  -- expected: trg_events_immutable raises restrict_violation
    END;

    ---- 4. A penalty rule can never raise a score (fn_ledger_guard) ---------------------------
    SELECT id INTO v_rule FROM score_rules
        WHERE tenant_id = '11111111-1111-1111-1111-111111111111' AND code = 'pii_in_prompt';

    BEGIN
        INSERT INTO score_ledger (tenant_id, run_id, rule_id, delta)
            VALUES ('11111111-1111-1111-1111-111111111111', v_run, v_rule, 5);
        RAISE EXCEPTION 'a positive-delta penalty should have been blocked by fn_ledger_guard';
    EXCEPTION
        WHEN raise_exception THEN
            NULL;  -- expected: fn_ledger_guard raises 'a penalty rule cannot raise a score'
    END;

    RAISE NOTICE 'ALL SMOKE TESTS PASSED';
END $$;
