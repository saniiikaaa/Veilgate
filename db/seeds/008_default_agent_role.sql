-- Every agent (seeded or auto-provisioned on first sight) holds this role; the tool gate and policies refine it.
INSERT INTO roles (id, tenant_id, name, holder, description, is_system) VALUES
  ('eeee0000-eeee-eeee-eeee-eeeeeeeeeeee', '11111111-1111-1111-1111-111111111111', 'agent_default', 'agent', 'Baseline agent role', true)
ON CONFLICT (tenant_id, name) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT 'eeee0000-eeee-eeee-eeee-eeeeeeeeeeee', id FROM permissions WHERE code IN ('tool.invoke', 'vault.tokenize', 'agent.handoff')
ON CONFLICT DO NOTHING;

INSERT INTO principal_roles (principal_id, role_id)
SELECT principal_id, 'eeee0000-eeee-eeee-eeee-eeeeeeeeeeee' FROM agents WHERE tenant_id = '11111111-1111-1111-1111-111111111111'
ON CONFLICT DO NOTHING;
