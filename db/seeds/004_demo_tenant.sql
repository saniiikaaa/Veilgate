INSERT INTO tenants (id, name, settings) VALUES
  ('11111111-1111-1111-1111-111111111111', 'Acme Healthcare', '{}')
ON CONFLICT (id) DO NOTHING;

INSERT INTO principals (id, tenant_id, kind, display_name) VALUES
  ('22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', 'user', 'Dr. Demo User'),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '11111111-1111-1111-1111-111111111111', 'agent', 'Orchestrator'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '11111111-1111-1111-1111-111111111111', 'agent', 'Data Agent'),
  ('cccccccc-cccc-cccc-cccc-cccccccccccc', '11111111-1111-1111-1111-111111111111', 'agent', 'Reporter')
ON CONFLICT (id) DO NOTHING;

INSERT INTO users (principal_id, tenant_id, email, name) VALUES
  ('22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', 'demo@acme.health', 'Dr. Demo User')
ON CONFLICT (principal_id) DO NOTHING;

INSERT INTO agents (principal_id, tenant_id, agent_key, description, type, framework, trust, initial_score, score_ceiling, owner_user_id) VALUES
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '11111111-1111-1111-1111-111111111111', 'orchestrator', 'Top-level planner',    'orchestrator', 'langgraph', 'trusted',  100, 100, '22222222-2222-2222-2222-222222222222'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '11111111-1111-1111-1111-111111111111', 'data_agent',   'Fetches patient data', 'worker',      'langgraph', 'standard', 80, 90,  '22222222-2222-2222-2222-222222222222'),
  ('cccccccc-cccc-cccc-cccc-cccccccccccc', '11111111-1111-1111-1111-111111111111', 'reporter',     'Writes reports',       'worker',      'langgraph', 'standard', 70, 85,  '22222222-2222-2222-2222-222222222222')
ON CONFLICT (tenant_id, agent_key) DO NOTHING;
