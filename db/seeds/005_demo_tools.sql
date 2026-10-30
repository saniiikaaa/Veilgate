INSERT INTO tools (id, tenant_id, name, description, risk, min_trust, requires_clear_input, returns_sensitive) VALUES
  ('dddd1111-dddd-dddd-dddd-dddddddd1111', '11111111-1111-1111-1111-111111111111', 'lookup_patient', 'Read patient by MRN',     'medium',   'standard',  true, false),
  ('dddd2222-dddd-dddd-dddd-dddddddd2222', '11111111-1111-1111-1111-111111111111', 'write_note',     'Append note to chart',   'high',     'standard',  true, false),
  ('dddd3333-dddd-dddd-dddd-dddddddd3333', '11111111-1111-1111-1111-111111111111', 'delete_record', 'Delete patient record',  'critical', 'trusted',   true, false),
  ('dddd4444-dddd-dddd-dddd-dddddddd4444', '11111111-1111-1111-1111-111111111111', 'web_search',    'External web search',    'low',      'untrusted', false, true)
ON CONFLICT (tenant_id, name) DO NOTHING;

INSERT INTO agent_tool_grants (agent_id, tool_id) VALUES
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'dddd1111-dddd-dddd-dddd-dddddddd1111'),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'dddd2222-dddd-dddd-dddd-dddddddd2222'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'dddd1111-dddd-dddd-dddd-dddddddd1111'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'dddd4444-dddd-dddd-dddd-dddddddd4444'),
  ('cccccccc-cccc-cccc-cccc-cccccccccccc', 'dddd2222-dddd-dddd-dddd-dddddddd2222')
ON CONFLICT DO NOTHING;

-- risk_thresholds come from config/default.yml
INSERT INTO agent_delegation_rules (parent_agent_id, child_agent_id) VALUES
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'cccccccc-cccc-cccc-cccc-cccccccccccc'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'cccccccc-cccc-cccc-cccc-cccccccccccc')
ON CONFLICT DO NOTHING;
