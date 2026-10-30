-- =====================================================================================================================
-- Guard layer: data model (PostgreSQL 14+; tested on 17/18)
--
-- Core idea: the model, the agents and the logs only ever see TOKENS.
--   user text -> detect identifiers -> tokenize -> vault (encrypted original) -> model/agents get tokens
--   a trusted agent + a trusted tool that has passed policy and score gates -> detokenize inside the tool -> real operation
--   the tool result is tokenized again -> agent -> final answer -> detokenize ONLY for a user allowed to see it
--
-- "Hash" in the plan = tokenization: a plain hash cannot be reversed. Each token stands for one value; the original is
-- stored AES-GCM encrypted (the application encrypts/decrypts, keys live in a KMS, never in this database) and a keyed
-- HMAC "blind index" lets the same value get the same token and be matched without ever decrypting.
--
-- Sections: 0 types | 1 tenancy and principals | 2 roles, permissions, policies | 3 compliance catalog | 4 registry
--           5 runtime | 6 vault | 7 authority score | 8 audit | 9 user profile | 10 guards and functions | 11 views | 12 RLS
-- Apply:    createdb guardrail_v2 && psql guardrail_v2 -f schema.sql -f seed.sql
-- =====================================================================================================================

SET client_min_messages = warning;

-- ---------------------------------------------------------------------------------------------------------------------
-- 0. Types (the order of enum values matters: comparisons such as risk >= 'high' use it)
-- ---------------------------------------------------------------------------------------------------------------------
CREATE TYPE principal_kind  AS ENUM ('user', 'agent', 'service');
CREATE TYPE principal_state AS ENUM ('active', 'suspended', 'retired');
CREATE TYPE risk_level      AS ENUM ('low', 'medium', 'high', 'critical');
CREATE TYPE trust_tier      AS ENUM ('untrusted', 'standard', 'trusted');
CREATE TYPE boundary_kind   AS ENUM ('user_input', 'model_input', 'model_output', 'tool_input', 'tool_output', 'handoff', 'user_output');
CREATE TYPE auth_effect     AS ENUM ('allow', 'deny', 'require_approval');
CREATE TYPE handling_action AS ENUM ('tokenize', 'block', 'log_only');
CREATE TYPE event_outcome   AS ENUM ('allowed', 'denied', 'tokenized', 'blocked', 'logged', 'approval_required');
CREATE TYPE policy_state    AS ENUM ('draft', 'active', 'retired');
CREATE TYPE vault_scope     AS ENUM ('session', 'user', 'tenant');
CREATE TYPE key_state       AS ENUM ('active', 'retiring', 'retired');
CREATE TYPE receipt_kind    AS ENUM ('decision', 'authority', 'detokenize');
CREATE TYPE score_rule_kind AS ENUM ('penalty', 'reward', 'admin_restore');
CREATE TYPE agent_type      AS ENUM ('orchestrator', 'worker', 'scripted', 'external');
CREATE TYPE run_state       AS ENUM ('running', 'completed', 'blocked', 'failed');

-- ---------------------------------------------------------------------------------------------------------------------
-- 1. Tenancy and principals. A principal is anything that can hold roles and be judged by policies: a user, an agent,
--    or a service. users and agents share the principal's primary key, so roles/policies/audit work the same for both.
-- ---------------------------------------------------------------------------------------------------------------------
CREATE TABLE tenants (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL UNIQUE,
    settings    jsonb NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE principals (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES tenants(id),
    kind          principal_kind NOT NULL,
    display_name  text NOT NULL,
    status        principal_state NOT NULL DEFAULT 'active',
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, kind),
    UNIQUE (id, tenant_id)
);
CREATE INDEX ix_principals_tenant ON principals (tenant_id, kind);

CREATE TABLE users (
    principal_id     uuid PRIMARY KEY,
    kind             principal_kind NOT NULL DEFAULT 'user' CHECK (kind = 'user'),
    tenant_id        uuid NOT NULL,
    email            text NOT NULL UNIQUE,
    external_auth_id text UNIQUE,                       -- id at the login provider (e.g. Clerk); no passwords stored here
    name             text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (principal_id, kind)      REFERENCES principals (id, kind),
    FOREIGN KEY (principal_id, tenant_id) REFERENCES principals (id, tenant_id)
);

CREATE TABLE agents (
    principal_id    uuid PRIMARY KEY,
    kind            principal_kind NOT NULL DEFAULT 'agent' CHECK (kind = 'agent'),
    tenant_id       uuid NOT NULL,
    agent_key       text NOT NULL,                      -- stable slug: 'orchestrator', 'data_agent'
    description     text,
    type            agent_type NOT NULL DEFAULT 'worker',
    framework       text,                               -- 'langgraph', 'langchain', 'custom'
    trust           trust_tier NOT NULL DEFAULT 'standard',   -- may be raised only by an admin (see admin_audit)
    initial_score   integer NOT NULL DEFAULT 100 CHECK (initial_score BETWEEN 0 AND 100),
    score_ceiling   integer NOT NULL DEFAULT 100 CHECK (score_ceiling BETWEEN 0 AND 100),
    owner_user_id   uuid REFERENCES users (principal_id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (principal_id, kind)      REFERENCES principals (id, kind),
    FOREIGN KEY (principal_id, tenant_id) REFERENCES principals (id, tenant_id),
    UNIQUE (tenant_id, agent_key)
);

-- ---------------------------------------------------------------------------------------------------------------------
-- 2. Roles, permissions, policies
--    permission  = a verb in a global catalog ('tool.invoke', 'vault.detokenize', ...)
--    role        = a named bundle of permissions, per tenant; held by users and/or agents
--    policy      = a versioned set of rules that refine permissions with conditions (resource, boundary, score, trust)
--    decision    = base permission through roles, then matching rules; an explicit deny always wins; default is deny
-- ---------------------------------------------------------------------------------------------------------------------
CREATE TABLE permissions (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code           text NOT NULL UNIQUE,
    resource_type  text,                                -- what the permission acts on: 'tool', 'entity_type', 'agent', 'model', or NULL
    description    text NOT NULL
);

CREATE TABLE roles (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id),
    name        text NOT NULL,
    holder      text NOT NULL DEFAULT 'any' CHECK (holder IN ('user', 'agent', 'any')),   -- who may hold it
    description text,
    is_system   boolean NOT NULL DEFAULT false,
    UNIQUE (tenant_id, name)
);

CREATE TABLE role_permissions (
    role_id        uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id  uuid NOT NULL REFERENCES permissions(id),
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE principal_roles (
    principal_id  uuid NOT NULL REFERENCES principals(id) ON DELETE CASCADE,
    role_id       uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    granted_by    uuid REFERENCES principals(id),
    granted_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz,
    PRIMARY KEY (principal_id, role_id)
);
CREATE INDEX ix_principal_roles_role ON principal_roles (role_id);

CREATE TABLE policies (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id),
    name        text NOT NULL,
    version     integer NOT NULL DEFAULT 1,
    status      policy_state NOT NULL DEFAULT 'draft',
    description text,
    created_by  uuid REFERENCES principals(id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name, version)
);

-- One rule: "when <who> asks for <permission> on <resource> at <boundary> with <score/trust in range>, then <effect>".
-- NULL in a condition column means "any".
CREATE TABLE policy_rules (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id      uuid NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
    priority       integer NOT NULL DEFAULT 100,
    effect         auth_effect NOT NULL,
    permission_id  uuid NOT NULL REFERENCES permissions(id),
    resource_type  text CHECK (resource_type IN ('tool', 'tool_risk', 'entity_type', 'agent', 'model')),
    resource_ref   text,                                -- tool name, risk level, entity type code, agent key, model key
    boundary       boundary_kind,
    score_min      integer CHECK (score_min BETWEEN 0 AND 100),
    score_max      integer CHECK (score_max BETWEEN 0 AND 100),
    trust_min      trust_tier,
    trust_max      trust_tier,
    conditions     jsonb NOT NULL DEFAULT '{}',         -- room for extra conditions the application evaluates
    reason         text,
    CHECK (resource_ref IS NULL OR resource_type IS NOT NULL),
    CHECK (score_min IS NULL OR score_max IS NULL OR score_min <= score_max)
);
CREATE INDEX ix_policy_rules_policy ON policy_rules (policy_id);
CREATE INDEX ix_policy_rules_perm   ON policy_rules (permission_id);

-- Where a policy applies: to one role, to one principal, or tenant-wide (exactly one).
CREATE TABLE policy_assignments (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id     uuid NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
    role_id       uuid REFERENCES roles(id) ON DELETE CASCADE,
    principal_id  uuid REFERENCES principals(id) ON DELETE CASCADE,
    tenant_wide   boolean NOT NULL DEFAULT false,
    CHECK ((role_id IS NOT NULL)::int + (principal_id IS NOT NULL)::int + tenant_wide::int = 1)
);
CREATE INDEX ix_policy_assign_policy ON policy_assignments (policy_id);
CREATE INDEX ix_policy_assign_role   ON policy_assignments (role_id)      WHERE role_id IS NOT NULL;
CREATE INDEX ix_policy_assign_prin   ON policy_assignments (principal_id) WHERE principal_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------------------------------
-- 3. Compliance catalog (global) and per-principal switches
-- ---------------------------------------------------------------------------------------------------------------------
CREATE TABLE frameworks (
    code         text PRIMARY KEY,                      -- 'HIPAA', 'DPDP'
    name         text NOT NULL,
    description  text
);

CREATE TABLE entity_types (
    code         text PRIMARY KEY,                      -- 'NAME', 'SSN', 'AADHAAR', ...
    name         text NOT NULL,
    sensitivity  risk_level NOT NULL DEFAULT 'medium',
    description  text
);

CREATE TABLE entity_type_frameworks (
    entity_type_code  text NOT NULL REFERENCES entity_types(code),
    framework_code    text NOT NULL REFERENCES frameworks(code),
    PRIMARY KEY (entity_type_code, framework_code)
);

CREATE TABLE principal_framework_settings (             -- the old per-user HIPAA / DPDP toggles, for any principal
    principal_id    uuid NOT NULL REFERENCES principals(id) ON DELETE CASCADE,
    framework_code  text NOT NULL REFERENCES frameworks(code),
    enabled         boolean NOT NULL DEFAULT true,
    PRIMARY KEY (principal_id, framework_code)
);

-- What to do with an identifier at a boundary. NULL = any. Default everywhere is tokenize; 'block' is for hard stops.
-- There is no "redact": the model always gets a token it can carry around, and the owner can get the value back.
CREATE TABLE handling_rules (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES tenants(id),
    entity_type_code  text REFERENCES entity_types(code),
    boundary          boundary_kind,
    action            handling_action NOT NULL DEFAULT 'tokenize',
    priority          integer NOT NULL DEFAULT 100
);
CREATE INDEX ix_handling_rules_tenant ON handling_rules (tenant_id);

-- ---------------------------------------------------------------------------------------------------------------------
-- 4. Registry: tools, grants, thresholds, providers and models
-- ---------------------------------------------------------------------------------------------------------------------
CREATE TABLE tools (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            uuid NOT NULL REFERENCES tenants(id),
    name                 text NOT NULL,
    description          text,
    risk                 risk_level NOT NULL DEFAULT 'medium',
    min_trust            trust_tier NOT NULL DEFAULT 'standard',   -- the calling agent must be at least this trusted
    requires_clear_input boolean NOT NULL DEFAULT false,           -- needs real values (detokenize) to do its job
    returns_sensitive    boolean NOT NULL DEFAULT false,           -- its output is tokenized before the agent sees it
    on_undeclared        text NOT NULL DEFAULT 'keep_token' CHECK (on_undeclared IN ('keep_token', 'refuse')),   -- a token the tool is not declared for: pass it on as a token, or refuse the call
    status               principal_state NOT NULL DEFAULT 'active',
    version              integer NOT NULL DEFAULT 1,
    arg_schema           jsonb,
    owner_user_id        uuid REFERENCES users (principal_id),
    created_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

-- Which identifier types a tool may receive in clear (detokenize_input) or produce (tokenize_output).
CREATE TABLE tool_entity_access (
    tool_id           uuid NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    entity_type_code  text NOT NULL REFERENCES entity_types(code),
    direction         text NOT NULL CHECK (direction IN ('detokenize_input', 'tokenize_output')),
    PRIMARY KEY (tool_id, entity_type_code, direction)
);

-- The agent's declared tools (the old "agent_allowed_tools"). No grant = out of scope.
CREATE TABLE agent_tool_grants (
    agent_id    uuid NOT NULL REFERENCES agents(principal_id) ON DELETE CASCADE,
    tool_id     uuid NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    granted_by  uuid REFERENCES principals(id),
    granted_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz,
    PRIMARY KEY (agent_id, tool_id)
);

-- Which agent may hand work to which (delegation graph).
CREATE TABLE agent_delegation_rules (
    parent_agent_id  uuid NOT NULL REFERENCES agents(principal_id) ON DELETE CASCADE,
    child_agent_id   uuid NOT NULL REFERENCES agents(principal_id) ON DELETE CASCADE,
    PRIMARY KEY (parent_agent_id, child_agent_id),
    CHECK (parent_agent_id <> child_agent_id)
);

CREATE TABLE risk_thresholds (                          -- the score an agent must have to call a tool of this risk
    tenant_id  uuid NOT NULL REFERENCES tenants(id),
    risk       risk_level NOT NULL,
    min_score  integer NOT NULL CHECK (min_score BETWEEN 0 AND 100),
    PRIMARY KEY (tenant_id, risk)
);

CREATE TABLE providers (                                -- model providers; secrets are NOT stored, only a pointer to them
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id),
    name        text NOT NULL,
    base_url    text NOT NULL,
    secret_ref  text,                                   -- e.g. a secret-manager path
    enabled     boolean NOT NULL DEFAULT true,
    UNIQUE (tenant_id, name)
);

CREATE TABLE models (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id  uuid NOT NULL REFERENCES providers(id),
    model_key    text NOT NULL,
    enabled      boolean NOT NULL DEFAULT true,
    UNIQUE (provider_id, model_key)
);

-- ---------------------------------------------------------------------------------------------------------------------
-- 5. Runtime: sessions, agent runs (the delegation tree), events (every boundary crossing), tool and model calls
-- ---------------------------------------------------------------------------------------------------------------------
CREATE TABLE sessions (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    uuid NOT NULL REFERENCES tenants(id),
    user_id      uuid NOT NULL REFERENCES users (principal_id),
    channel      text,
    external_ref text,
    started_at   timestamptz NOT NULL DEFAULT now(),
    ended_at     timestamptz
);
CREATE INDEX ix_sessions_user ON sessions (user_id, started_at DESC);

CREATE TABLE agent_runs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id),
    session_id      uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    agent_id        uuid NOT NULL REFERENCES agents (principal_id),
    parent_run_id   uuid REFERENCES agent_runs(id),
    initial_score   integer NOT NULL CHECK (initial_score BETWEEN 0 AND 100),   -- copied from the agent when the run starts
    score_ceiling   integer NOT NULL CHECK (score_ceiling BETWEEN 0 AND 100),
    status          run_state NOT NULL DEFAULT 'running',
    started_at      timestamptz NOT NULL DEFAULT now(),
    ended_at        timestamptz,
    CHECK (parent_run_id IS NULL OR parent_run_id <> id)
);
CREATE INDEX ix_runs_session ON agent_runs (session_id);
CREATE INDEX ix_runs_parent  ON agent_runs (parent_run_id) WHERE parent_run_id IS NOT NULL;

-- Append-only. The text stored is ALWAYS the tokenized text: the original never lands in this table.
CREATE TABLE events (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      uuid NOT NULL REFERENCES tenants(id),
    session_id     uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    run_id         uuid REFERENCES agent_runs(id),
    boundary       boundary_kind NOT NULL,
    outcome        event_outcome NOT NULL,
    policy_rule_id uuid REFERENCES policy_rules(id),    -- the rule that decided, if any
    entities_found integer NOT NULL DEFAULT 0 CHECK (entities_found >= 0),
    tokenized_text text,
    text_sha256    char(64),
    latency_ms     numeric(10,2),
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_events_session ON events (session_id, created_at);
CREATE INDEX ix_events_run     ON events (run_id) WHERE run_id IS NOT NULL;

CREATE TABLE tool_calls (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES tenants(id),
    run_id            uuid NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    tool_id           uuid NOT NULL REFERENCES tools(id),
    request_event_id  uuid NOT NULL REFERENCES events(id),
    result_event_id   uuid REFERENCES events(id),
    args_tokenized    jsonb,
    outcome           event_outcome NOT NULL,
    required_score    integer,
    score_at_call     integer,
    detokenized       boolean NOT NULL DEFAULT false,   -- real values were used inside the tool
    error             text,
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz
);
CREATE INDEX ix_tool_calls_run ON tool_calls (run_id);

CREATE TABLE model_calls (                              -- per-call usage: tokens and latency per user come from here
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          uuid NOT NULL REFERENCES tenants(id),
    run_id             uuid NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    model_id           uuid REFERENCES models(id),
    request_event_id   uuid REFERENCES events(id),
    response_event_id  uuid REFERENCES events(id),
    prompt_tokens      integer CHECK (prompt_tokens >= 0),
    completion_tokens  integer CHECK (completion_tokens >= 0),
    tokens_estimated   boolean NOT NULL DEFAULT false,
    latency_ms         numeric(10,2),
    cost               numeric(12,6),
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_model_calls_run ON model_calls (run_id);

-- ---------------------------------------------------------------------------------------------------------------------
-- 6. Vault: token <-> encrypted original. The database never holds a key; the application encrypts and decrypts.
-- ---------------------------------------------------------------------------------------------------------------------
CREATE TABLE vault_keys (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id),
    kms_ref     text NOT NULL,                          -- pointer to the key in the KMS, never the key
    algorithm   text NOT NULL DEFAULT 'AES-256-GCM',
    status      key_state NOT NULL DEFAULT 'active',
    created_at  timestamptz NOT NULL DEFAULT now(),
    rotated_at  timestamptz
);

CREATE TABLE vault_entries (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             uuid NOT NULL REFERENCES tenants(id),
    token                 text NOT NULL,                -- what everyone downstream sees, e.g. tok_name_9f3a21c4e7b0
    entity_type_code      text NOT NULL REFERENCES entity_types(code),
    scope                 vault_scope NOT NULL DEFAULT 'session',
    scope_ref             uuid,                         -- the session or user id the token is valid in (NULL for tenant scope)
    owner_user_id         uuid REFERENCES users (principal_id),     -- the user who supplied the value, if it came from a user
    subject_ref           text,                         -- data subject for record data (e.g. a patient id), for erasure requests
    value_ciphertext      bytea,
    nonce                 bytea,
    key_id                uuid NOT NULL REFERENCES vault_keys(id),
    value_hmac            bytea NOT NULL,               -- keyed hash of the normalized value: same value -> same token, searchable
    created_by_event_id   uuid REFERENCES events(id),
    created_at            timestamptz NOT NULL DEFAULT now(),
    expires_at            timestamptz,
    erased_at             timestamptz,                  -- crypto-shredding: right to erasure removes the ciphertext, tokens remain
    UNIQUE (tenant_id, token),
    CHECK ((erased_at IS NULL) = (value_ciphertext IS NOT NULL)),
    CHECK (value_ciphertext IS NULL OR nonce IS NOT NULL)
);
CREATE UNIQUE INDEX ux_vault_same_value ON vault_entries
    (tenant_id, entity_type_code, scope, coalesce(scope_ref, '00000000-0000-0000-0000-000000000000'::uuid), value_hmac);
CREATE INDEX ix_vault_owner   ON vault_entries (owner_user_id) WHERE owner_user_id IS NOT NULL;
CREATE INDEX ix_vault_subject ON vault_entries (tenant_id, subject_ref) WHERE subject_ref IS NOT NULL;

-- Which tokens appeared in which event (so a decision can be traced to the identifiers it involved, without plaintext).
CREATE TABLE event_entities (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id          uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    vault_entry_id    uuid NOT NULL REFERENCES vault_entries(id),
    entity_type_code  text NOT NULL REFERENCES entity_types(code),
    confidence        numeric(4,3),
    UNIQUE (event_id, vault_entry_id)
);

-- Every decryption request, allowed or not. Append-only.
CREATE TABLE vault_access_log (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id),
    vault_entry_id  uuid NOT NULL REFERENCES vault_entries(id),
    principal_id    uuid NOT NULL REFERENCES principals(id),      -- who asked (the user, or the agent acting)
    run_id          uuid REFERENCES agent_runs(id),
    tool_id         uuid REFERENCES tools(id),
    boundary        boundary_kind NOT NULL,
    allowed         boolean NOT NULL,
    reason          text,
    policy_rule_id  uuid REFERENCES policy_rules(id),
    event_id        uuid REFERENCES events(id),
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_vault_access_entry ON vault_access_log (vault_entry_id, created_at);
CREATE INDEX ix_vault_access_prin  ON vault_access_log (principal_id, created_at);

-- ---------------------------------------------------------------------------------------------------------------------
-- 7. Authority score: rules and an append-only ledger. Own score = initial + sum(delta), clamped 0..ceiling.
--    Effective score = the lowest own score on the path to the root run (delegation cap). The database itself
--    refuses an upward move unless it is a reward with its evidence event or an admin restore with an audit row.
-- ---------------------------------------------------------------------------------------------------------------------
CREATE TABLE score_rules (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    uuid NOT NULL REFERENCES tenants(id),
    code         text NOT NULL,                         -- 'out_of_scope', 'prompt_injection', 'clean_tool_result', ...
    kind         score_rule_kind NOT NULL,
    delta        integer NOT NULL CHECK (delta <> 0),
    description  text,
    UNIQUE (tenant_id, code),
    CHECK ((kind = 'penalty' AND delta < 0) OR (kind <> 'penalty' AND delta > 0))
);

CREATE TABLE admin_audit (                              -- who changed roles, policies, trust tiers, thresholds ... Append-only.
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          uuid NOT NULL REFERENCES tenants(id),
    actor_principal_id uuid NOT NULL REFERENCES principals(id),
    action             text NOT NULL,
    target_type        text NOT NULL,
    target_id          text,
    before_state       jsonb,
    after_state        jsonb,
    reason             text,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_admin_audit_tenant ON admin_audit (tenant_id, created_at);

CREATE TABLE score_ledger (
    id              bigserial PRIMARY KEY,
    tenant_id       uuid NOT NULL REFERENCES tenants(id),
    run_id          uuid NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    rule_id         uuid NOT NULL REFERENCES score_rules(id),
    delta           integer NOT NULL CHECK (delta <> 0),
    reason          text,
    event_id        uuid REFERENCES events(id),         -- the event that caused it (the evidence for a reward)
    admin_audit_id  uuid REFERENCES admin_audit(id),    -- required for an admin restore
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_ledger_run ON score_ledger (run_id, id);

-- ---------------------------------------------------------------------------------------------------------------------
-- 8. Receipts: one hash chain per session, written by a trigger (not by application code). Covers compliance decisions,
--    authority (score) decisions and every detokenize. The payload is stored inside the receipt, so verification does
--    not depend on any other row.
-- ---------------------------------------------------------------------------------------------------------------------
CREATE TABLE receipts (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    uuid NOT NULL REFERENCES tenants(id),
    session_id   uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq          integer NOT NULL,
    type         receipt_kind NOT NULL,
    event_id     uuid REFERENCES events(id),
    run_id       uuid REFERENCES agent_runs(id),        -- attribution: run -> agent_id and parent run -> parent agent
    payload      jsonb NOT NULL,
    prev_hash    char(64) NOT NULL,
    hash         char(64) NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, seq)
);
CREATE INDEX ix_receipts_event ON receipts (event_id) WHERE event_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------------------------------
-- 9. User profile: rating snapshots, resets. Token usage comes from model_calls (view below).
-- ---------------------------------------------------------------------------------------------------------------------
CREATE TABLE rating_resets (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL REFERENCES users (principal_id),
    reset_by     uuid NOT NULL REFERENCES principals(id),
    reason       text,
    admin_audit_id uuid REFERENCES admin_audit(id),
    reset_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_rating_resets_user ON rating_resets (user_id, reset_at DESC);

CREATE TABLE user_rating_snapshots (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES tenants(id),
    user_id          uuid NOT NULL REFERENCES users (principal_id),
    computed_at      timestamptz NOT NULL DEFAULT now(),
    window_start     timestamptz,
    window_end       timestamptz,
    authority_trust  numeric(5,2) CHECK (authority_trust BETWEEN 0 AND 100),
    violation_rate   numeric(5,2) CHECK (violation_rate BETWEEN 0 AND 100),
    effective_use    numeric(5,2) CHECK (effective_use BETWEEN 0 AND 100),
    composite        numeric(5,2) CHECK (composite BETWEEN 0 AND 100),
    details          jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX ix_rating_snap_user ON user_rating_snapshots (user_id, computed_at DESC);

-- ---------------------------------------------------------------------------------------------------------------------
-- 10. Guards and functions
-- ---------------------------------------------------------------------------------------------------------------------

-- Append-only tables refuse UPDATE and DELETE (a superuser can still disable the trigger; verification detects that).
CREATE FUNCTION fn_forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'table % is append-only (% not allowed)', TG_TABLE_NAME, TG_OP USING ERRCODE = 'restrict_violation';
END $$;

CREATE TRIGGER trg_events_immutable        BEFORE UPDATE OR DELETE ON events           FOR EACH ROW EXECUTE FUNCTION fn_forbid_mutation();
CREATE TRIGGER trg_event_entities_immutable BEFORE UPDATE OR DELETE ON event_entities  FOR EACH ROW EXECUTE FUNCTION fn_forbid_mutation();
CREATE TRIGGER trg_receipts_immutable      BEFORE UPDATE OR DELETE ON receipts         FOR EACH ROW EXECUTE FUNCTION fn_forbid_mutation();
CREATE TRIGGER trg_ledger_immutable        BEFORE UPDATE OR DELETE ON score_ledger     FOR EACH ROW EXECUTE FUNCTION fn_forbid_mutation();
CREATE TRIGGER trg_vault_access_immutable  BEFORE UPDATE OR DELETE ON vault_access_log FOR EACH ROW EXECUTE FUNCTION fn_forbid_mutation();
CREATE TRIGGER trg_admin_audit_immutable   BEFORE UPDATE OR DELETE ON admin_audit      FOR EACH ROW EXECUTE FUNCTION fn_forbid_mutation();

-- Receipt chain: sequence, previous hash and hash are set here, under a per-session lock, so they cannot race or be forged.
CREATE FUNCTION fn_receipt_chain() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    last_seq  integer;
    last_hash char(64);
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.session_id::text, 0));
    SELECT seq, hash INTO last_seq, last_hash FROM receipts WHERE session_id = NEW.session_id ORDER BY seq DESC LIMIT 1;
    NEW.seq       := coalesce(last_seq, 0) + 1;
    NEW.prev_hash := coalesce(last_hash, repeat('0', 64));
    NEW.hash      := encode(sha256(convert_to(NEW.prev_hash || '|' || NEW.seq::text || '|' || NEW.type::text || '|' || NEW.payload::text, 'UTF8')), 'hex');
    RETURN NEW;
END $$;
CREATE TRIGGER trg_receipt_chain BEFORE INSERT ON receipts FOR EACH ROW EXECUTE FUNCTION fn_receipt_chain();

-- Monotonic reduction, enforced by the database: a positive delta needs a reward rule (+ its evidence event) or an
-- admin_restore rule (+ an audit row). Nothing else can raise a score.
CREATE FUNCTION fn_ledger_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    k score_rule_kind;
    d integer;
BEGIN
    SELECT kind, delta INTO k, d FROM score_rules WHERE id = NEW.rule_id;
    IF NEW.delta > 0 AND k = 'penalty' THEN
        RAISE EXCEPTION 'a penalty rule cannot raise a score';
    ELSIF NEW.delta < 0 AND k <> 'penalty' THEN
        RAISE EXCEPTION 'only a penalty rule can lower a score';
    ELSIF NEW.delta > 0 AND k = 'reward' AND NEW.event_id IS NULL THEN
        RAISE EXCEPTION 'a reward needs the evidence event that earned it';
    ELSIF NEW.delta > 0 AND k = 'admin_restore' AND NEW.admin_audit_id IS NULL THEN
        RAISE EXCEPTION 'an admin restore needs an admin_audit row';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_ledger_guard BEFORE INSERT ON score_ledger FOR EACH ROW EXECUTE FUNCTION fn_ledger_guard();

-- A role marked for users cannot be given to an agent, and the reverse.
CREATE FUNCTION fn_principal_role_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    h text;
    pk principal_kind;
BEGIN
    SELECT holder INTO h FROM roles WHERE id = NEW.role_id;
    SELECT kind INTO pk FROM principals WHERE id = NEW.principal_id;
    IF h <> 'any' AND h <> pk::text THEN
        RAISE EXCEPTION 'role is for % principals, not %', h, pk;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_principal_role_guard BEFORE INSERT OR UPDATE ON principal_roles FOR EACH ROW EXECUTE FUNCTION fn_principal_role_guard();

-- Own score of one run.
CREATE FUNCTION fn_run_score(p_run uuid) RETURNS integer LANGUAGE sql STABLE AS $$
    SELECT greatest(0, least(r.score_ceiling, r.initial_score + coalesce((SELECT sum(l.delta) FROM score_ledger l WHERE l.run_id = r.id), 0)))::integer
    FROM agent_runs r WHERE r.id = p_run
$$;

-- Effective score: the lowest own score from this run up to the root (delegation cap).
CREATE FUNCTION fn_effective_score(p_run uuid) RETURNS integer LANGUAGE sql STABLE AS $$
    WITH RECURSIVE chain AS (
        SELECT id, parent_run_id FROM agent_runs WHERE id = p_run
        UNION ALL
        SELECT r.id, r.parent_run_id FROM agent_runs r JOIN chain c ON r.id = c.parent_run_id
    )
    SELECT min(fn_run_score(id)) FROM chain
$$;

-- Generic decision: base permission through roles, refined by matching rules. Explicit deny wins, then require_approval,
-- then allow by priority; with no rule the role grant decides; no grant = deny.
CREATE FUNCTION fn_authorize(
    p_principal     uuid,
    p_permission    text,
    p_resource_type text          DEFAULT NULL,
    p_resource_ref  text          DEFAULT NULL,
    p_boundary      boundary_kind DEFAULT NULL,
    p_run           uuid          DEFAULT NULL
) RETURNS TABLE (allowed boolean, effect auth_effect, rule_id uuid, reason text)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_tenant uuid;
    v_perm   uuid;
    v_score  integer;
    v_trust  trust_tier;
    v_base   boolean;
    r        record;
BEGIN
    SELECT tenant_id INTO v_tenant FROM principals WHERE id = p_principal AND status = 'active';
    IF v_tenant IS NULL THEN
        RETURN QUERY SELECT false, 'deny'::auth_effect, NULL::uuid, 'principal is unknown or not active'; RETURN;
    END IF;
    SELECT id INTO v_perm FROM permissions WHERE code = p_permission;
    IF v_perm IS NULL THEN
        RETURN QUERY SELECT false, 'deny'::auth_effect, NULL::uuid, 'unknown permission ' || p_permission; RETURN;
    END IF;
    IF p_run IS NOT NULL THEN
        v_score := fn_effective_score(p_run);
        SELECT a.trust INTO v_trust FROM agent_runs ar JOIN agents a ON a.principal_id = ar.agent_id WHERE ar.id = p_run;
    END IF;

    SELECT EXISTS (
        SELECT 1 FROM principal_roles pr JOIN role_permissions rp ON rp.role_id = pr.role_id
        WHERE pr.principal_id = p_principal AND rp.permission_id = v_perm AND (pr.expires_at IS NULL OR pr.expires_at > now())
    ) INTO v_base;

    FOR r IN
        SELECT ru.id, ru.effect, ru.reason
        FROM policy_rules ru
        JOIN policies p ON p.id = ru.policy_id AND p.status = 'active' AND p.tenant_id = v_tenant
        JOIN policy_assignments pa ON pa.policy_id = p.id
        WHERE ru.permission_id = v_perm
          AND (pa.tenant_wide OR pa.principal_id = p_principal
               OR pa.role_id IN (SELECT role_id FROM principal_roles WHERE principal_id = p_principal AND (expires_at IS NULL OR expires_at > now())))
          AND (ru.resource_type IS NULL OR ru.resource_type = p_resource_type)
          AND (ru.resource_ref  IS NULL OR ru.resource_ref  = p_resource_ref)
          AND (ru.boundary      IS NULL OR ru.boundary      = p_boundary)
          AND (ru.score_min IS NULL OR (v_score IS NOT NULL AND v_score >= ru.score_min))
          AND (ru.score_max IS NULL OR (v_score IS NOT NULL AND v_score <= ru.score_max))
          AND (ru.trust_min IS NULL OR (v_trust IS NOT NULL AND v_trust >= ru.trust_min))
          AND (ru.trust_max IS NULL OR (v_trust IS NOT NULL AND v_trust <= ru.trust_max))
        ORDER BY (ru.effect = 'deny') DESC, (ru.effect = 'require_approval') DESC, ru.priority DESC, ru.id
        LIMIT 1
    LOOP
        IF r.effect = 'allow' THEN
            RETURN QUERY SELECT true, r.effect, r.id, coalesce(r.reason, 'allowed by policy rule'); RETURN;
        END IF;
        RETURN QUERY SELECT false, r.effect, r.id, coalesce(r.reason, CASE r.effect WHEN 'deny' THEN 'denied by policy rule' ELSE 'approval required' END);
        RETURN;
    END LOOP;

    IF v_base THEN
        RETURN QUERY SELECT true, 'allow'::auth_effect, NULL::uuid, 'granted by role';
    ELSE
        RETURN QUERY SELECT false, 'deny'::auth_effect, NULL::uuid, 'no role grants ' || p_permission;
    END IF;
END $$;

-- The tool gate: declared tool? trusted enough? score high enough for the tool's risk? policy allows?
-- 'suggested_penalty' is the score rule the application should record when the call is refused.
CREATE FUNCTION fn_authorize_tool_call(p_run uuid, p_tool uuid)
RETURNS TABLE (allowed boolean, reason text, required_score integer, current_score integer, rule_id uuid, suggested_penalty text)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_agent uuid;
    v_tenant uuid;
    v_trust trust_tier;
    v_tool  tools%ROWTYPE;
    v_req   integer;
    v_cur   integer;
    a       record;
BEGIN
    SELECT ar.agent_id, ar.tenant_id, ag.trust INTO v_agent, v_tenant, v_trust
    FROM agent_runs ar JOIN agents ag ON ag.principal_id = ar.agent_id WHERE ar.id = p_run;
    SELECT * INTO v_tool FROM tools WHERE id = p_tool AND status = 'active';
    IF v_agent IS NULL OR v_tool.id IS NULL THEN
        RETURN QUERY SELECT false, 'unknown run or inactive tool', NULL::integer, NULL::integer, NULL::uuid, 'denied_attempt'; RETURN;
    END IF;
    v_cur := fn_effective_score(p_run);
    SELECT min_score INTO v_req FROM risk_thresholds WHERE tenant_id = v_tenant AND risk = v_tool.risk;
    v_req := coalesce(v_req, 0);

    IF NOT EXISTS (SELECT 1 FROM agent_tool_grants g WHERE g.agent_id = v_agent AND g.tool_id = p_tool AND (g.expires_at IS NULL OR g.expires_at > now())) THEN
        RETURN QUERY SELECT false, 'tool is not in the agent''s declared tools (out of scope)', v_req, v_cur, NULL::uuid, 'out_of_scope'; RETURN;
    END IF;
    IF v_trust < v_tool.min_trust THEN
        RETURN QUERY SELECT false, format('agent trust %s is below the %s this tool needs', v_trust, v_tool.min_trust), v_req, v_cur, NULL::uuid, 'denied_attempt'; RETURN;
    END IF;
    IF v_cur < v_req THEN
        RETURN QUERY SELECT false, format('effective score %s is below the %s a %s-risk tool needs', v_cur, v_req, v_tool.risk), v_req, v_cur, NULL::uuid, 'denied_attempt'; RETURN;
    END IF;
    SELECT * INTO a FROM fn_authorize(v_agent, 'tool.invoke', 'tool', v_tool.name, 'tool_input', p_run);
    IF NOT a.allowed THEN
        RETURN QUERY SELECT false, a.reason, v_req, v_cur, a.rule_id, 'denied_attempt'; RETURN;
    END IF;
    RETURN QUERY SELECT true, 'tool call authorised', v_req, v_cur, a.rule_id, NULL::text;
END $$;

-- The only door to the original value. It checks, logs (always), and returns the ciphertext only when allowed;
-- the application decrypts it with the KMS. Rules, in order:
--   1. never at model_input / model_output / handoff (the model and agents only ever see tokens)
--   2. tool_input: the tool must be declared for that entity type, and the acting agent must hold vault.detokenize
--   3. user_output: the owner of the value, or a principal holding vault.detokenize for that entity type
--   4. policy deny rules always apply
CREATE FUNCTION fn_request_detokenize(
    p_principal uuid, p_entry uuid, p_boundary boundary_kind,
    p_run uuid DEFAULT NULL, p_tool uuid DEFAULT NULL, p_session uuid DEFAULT NULL, p_event uuid DEFAULT NULL
) RETURNS TABLE (allowed boolean, reason text, value_ciphertext bytea, nonce bytea, key_id uuid)
LANGUAGE plpgsql AS $$
DECLARE
    e         vault_entries%ROWTYPE;
    v_ok      boolean := false;
    v_reason  text;
    v_rule    uuid;
    a         record;
BEGIN
    SELECT * INTO e FROM vault_entries WHERE id = p_entry;
    IF e.id IS NULL THEN
        RETURN QUERY SELECT false, 'unknown token', NULL::bytea, NULL::bytea, NULL::uuid; RETURN;
    END IF;

    IF e.erased_at IS NOT NULL THEN
        v_reason := 'value was erased (right to erasure)';
    ELSIF e.expires_at IS NOT NULL AND e.expires_at < now() THEN
        v_reason := 'token expired';
    ELSIF p_boundary IN ('model_input', 'model_output', 'handoff') THEN
        v_reason := 'the model and agents only ever see tokens: no detokenize at ' || p_boundary;
    ELSIF p_boundary NOT IN ('tool_input', 'user_output') THEN
        v_reason := 'detokenize is not allowed at ' || p_boundary;
    ELSE
        SELECT * INTO a FROM fn_authorize(p_principal, 'vault.detokenize', 'entity_type', e.entity_type_code, p_boundary, p_run);
        v_rule := a.rule_id;
        IF a.rule_id IS NOT NULL AND a.effect IN ('deny', 'require_approval') THEN   -- an explicit rule decided; a plain "no role grants it" does not block the owner path
            v_reason := a.reason;
        ELSIF p_boundary = 'tool_input' THEN
            IF p_tool IS NULL OR p_run IS NULL THEN
                v_reason := 'tool_input needs the run and the tool';
            ELSIF NOT EXISTS (SELECT 1 FROM tool_entity_access t WHERE t.tool_id = p_tool AND t.entity_type_code = e.entity_type_code AND t.direction = 'detokenize_input') THEN
                v_reason := 'this tool is not declared for ' || e.entity_type_code || ' in clear';
            ELSIF NOT a.allowed THEN
                v_reason := a.reason;
            ELSIF NOT (SELECT t.allowed FROM fn_authorize_tool_call(p_run, p_tool) t) THEN
                v_reason := 'the tool call itself is not authorised (score, trust or scope)';
            ELSE
                v_ok := true; v_reason := 'tool authorised and declared for this identifier';
            END IF;
        ELSE  -- user_output
            IF e.owner_user_id IS NOT NULL AND e.owner_user_id = p_principal THEN
                v_ok := true; v_reason := 'owner of the value';
            ELSIF a.allowed THEN
                v_ok := true; v_reason := 'principal holds vault.detokenize for ' || e.entity_type_code;
            ELSE
                v_reason := 'not the owner and no clearance for ' || e.entity_type_code;
            END IF;
        END IF;
    END IF;

    INSERT INTO vault_access_log (tenant_id, vault_entry_id, principal_id, run_id, tool_id, boundary, allowed, reason, policy_rule_id, event_id)
    VALUES (e.tenant_id, e.id, p_principal, p_run, p_tool, p_boundary, v_ok, v_reason, v_rule, p_event);

    IF p_session IS NOT NULL THEN
        INSERT INTO receipts (tenant_id, session_id, type, event_id, run_id, payload)
        VALUES (e.tenant_id, p_session, 'detokenize', p_event, p_run,
                jsonb_build_object('token', e.token, 'entity', e.entity_type_code, 'principal', p_principal,
                                   'boundary', p_boundary, 'allowed', v_ok, 'reason', v_reason));
    END IF;

    IF v_ok THEN
        RETURN QUERY SELECT true, v_reason, e.value_ciphertext, e.nonce, e.key_id;
    ELSE
        RETURN QUERY SELECT false, v_reason, NULL::bytea, NULL::bytea, NULL::uuid;
    END IF;
END $$;

-- Recompute the whole chain of one session.
CREATE FUNCTION fn_verify_receipts(p_session uuid)
RETURNS TABLE (ok boolean, receipt_count integer, broken_at_seq integer, reason text)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    r        record;
    expected integer := 1;
    prev     char(64) := repeat('0', 64);
    n        integer := 0;
BEGIN
    FOR r IN SELECT * FROM receipts WHERE session_id = p_session ORDER BY seq LOOP
        n := n + 1;
        IF r.seq <> expected THEN
            RETURN QUERY SELECT false, n, r.seq, 'sequence gap: a receipt is missing'; RETURN;
        END IF;
        IF r.prev_hash <> prev THEN
            RETURN QUERY SELECT false, n, r.seq, 'previous-hash link does not match'; RETURN;
        END IF;
        IF r.hash <> encode(sha256(convert_to(r.prev_hash || '|' || r.seq::text || '|' || r.type::text || '|' || r.payload::text, 'UTF8')), 'hex') THEN
            RETURN QUERY SELECT false, n, r.seq, 'payload no longer matches its hash'; RETURN;
        END IF;
        prev := r.hash;
        expected := expected + 1;
    END LOOP;
    RETURN QUERY SELECT true, n, NULL::integer, 'chain intact';
END $$;

-- ---------------------------------------------------------------------------------------------------------------------
-- 11. Views
-- ---------------------------------------------------------------------------------------------------------------------
CREATE VIEW v_run_scores AS
SELECT r.id AS run_id, r.session_id, r.agent_id, r.parent_run_id,
       fn_run_score(r.id) AS own_score, fn_effective_score(r.id) AS effective_score, r.score_ceiling
FROM agent_runs r;

CREATE VIEW v_user_token_usage AS
SELECT s.user_id, date_trunc('day', m.created_at) AS day,
       sum(coalesce(m.prompt_tokens, 0))      AS prompt_tokens,
       sum(coalesce(m.completion_tokens, 0))  AS completion_tokens,
       count(*)                               AS model_calls
FROM model_calls m
JOIN agent_runs r ON r.id = m.run_id
JOIN sessions s   ON s.id = r.session_id
GROUP BY s.user_id, date_trunc('day', m.created_at);

CREATE VIEW v_session_denials AS                        -- the dashboard's "denied tool calls per agent"
SELECT r.session_id, r.agent_id, a.agent_key, count(*) FILTER (WHERE t.outcome = 'denied') AS denied_calls, count(*) AS tool_calls
FROM tool_calls t JOIN agent_runs r ON r.id = t.run_id JOIN agents a ON a.principal_id = r.agent_id
GROUP BY r.session_id, r.agent_id, a.agent_key;

-- ---------------------------------------------------------------------------------------------------------------------
-- 12. Row-level security: every table that has a tenant_id is filtered by the tenant the application sets per connection:
--         SET app.tenant_id = '<tenant uuid>';
--     The application connects as guardrail_app (not the table owner, which bypasses RLS).
-- ---------------------------------------------------------------------------------------------------------------------
DO $$
DECLARE t record;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'guardrail_app') THEN
        CREATE ROLE guardrail_app NOLOGIN;
    END IF;
    FOR t IN SELECT c.table_name FROM information_schema.columns c JOIN information_schema.tables tb
                 ON tb.table_schema = c.table_schema AND tb.table_name = c.table_name AND tb.table_type = 'BASE TABLE'
             WHERE c.table_schema = 'public' AND c.column_name = 'tenant_id' AND c.table_name <> 'tenants'
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t.table_name);
        EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (tenant_id = nullif(current_setting(''app.tenant_id'', true), '''')::uuid) '
                       'WITH CHECK (tenant_id = nullif(current_setting(''app.tenant_id'', true), '''')::uuid)', t.table_name);
    END LOOP;
END $$;
GRANT USAGE ON SCHEMA public TO guardrail_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO guardrail_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guardrail_app;
