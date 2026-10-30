INSERT INTO permissions (code, resource_type, description) VALUES
  ('tool.invoke',         'tool',        'Invoke a tool'),
  ('vault.detokenize',    'entity_type', 'Decrypt a vault token to its original value'),
  ('vault.tokenize',      'entity_type', 'Tokenize a value into the vault'),
  ('agent.handoff',       'agent',       'Delegate work to another agent'),
  ('agent.create',        'agent',       'Create a new agent principal'),
  ('policy.create',       NULL,          'Create or modify policies'),
  ('admin.trust.raise',   'agent',       'Raise an agent trust tier'),
  ('admin.score.restore', 'agent',       'Restore a score (requires admin_audit)')
ON CONFLICT (code) DO NOTHING;
