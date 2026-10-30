INSERT INTO frameworks (code, name, description) VALUES
  ('HIPAA', 'HIPAA', 'US Health Insurance Portability and Accountability Act'),
  ('DPDP',  'DPDP',  'India Digital Personal Data Protection Act, 2023')
ON CONFLICT (code) DO NOTHING;
