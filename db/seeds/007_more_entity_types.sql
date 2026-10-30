INSERT INTO entity_types (code, name, sensitivity, description) VALUES
  ('URL',      'Web URL',               'low',      'http(s) URL'),
  ('MAC',      'MAC address',           'low',      'Device MAC address'),
  ('VIN',      'Vehicle VIN',           'medium',   '17-character vehicle identification number'),
  ('PASSPORT', 'Passport number',       'critical', 'Passport number near the word passport'),
  ('UPI',      'India UPI id',          'high',     'UPI handle like name@bank'),
  ('IMEI',      'Device IMEI',          'medium',   '15-digit Luhn-valid IMEI'),
  ('ACCOUNT',  'Bank account number',   'critical', 'Account number near an account keyword'),
  ('HEALTH_ID','Health plan id',        'high',     'Policy, member or subscriber id near a keyword')
ON CONFLICT (code) DO NOTHING;

INSERT INTO entity_type_frameworks (entity_type_code, framework_code) VALUES
  ('URL','HIPAA'), ('MAC','HIPAA'), ('VIN','HIPAA'), ('IP','HIPAA'), ('DOB','HIPAA'), ('ACCOUNT','HIPAA'), ('HEALTH_ID','HIPAA'), ('IMEI','HIPAA'),
  ('PASSPORT','DPDP'), ('UPI','DPDP'), ('ACCOUNT','DPDP'), ('CREDIT_CARD','DPDP'), ('IP','DPDP'), ('HEALTH_ID','DPDP')
ON CONFLICT DO NOTHING;
