INSERT INTO entity_types (code, name, sensitivity, description) VALUES
  ('NAME',        'Person name',         'high',     'A person full or partial name'),
  ('EMAIL',       'Email address',       'medium',   'Email like john@example.com'),
  ('SSN',         'US Social Security',  'critical', 'US SSN, format XXX-XX-XXXX'),
  ('AADHAAR',     'India Aadhaar',       'critical', 'India Aadhaar, 12 digits'),
  ('PAN',         'India PAN',           'high',     'India Permanent Account Number'),
  ('CREDIT_CARD', 'Credit card number',  'critical', 'Credit card, Luhn-valid'),
  ('PHONE',       'Phone number',        'medium',   'US or India phone'),
  ('ADDRESS',     'Postal address',      'medium',   'Street + city + zip'),
  ('ZIP',         'US ZIP code',         'low',      '5 or 9 digit US ZIP'),
  ('PIN',         'India PIN code',      'low',      '6 digit India PIN'),
  ('MRN',         'Medical record num',  'critical', 'Hospital MRN'),
  ('NPI',         'NPI number',          'high',     'US National Provider Identifier'),
  ('DOB',         'Date of birth',       'high',     'ISO date tied to a person'),
  ('DIAGNOSIS',   'Diagnosis',           'high',     'ICD code or condition text'),
  ('IP',          'IP address',          'low',      'IPv4 or IPv6')
ON CONFLICT (code) DO NOTHING;

INSERT INTO entity_type_frameworks (entity_type_code, framework_code) VALUES
  ('NAME','HIPAA'), ('EMAIL','HIPAA'), ('SSN','HIPAA'), ('CREDIT_CARD','HIPAA'), ('PHONE','HIPAA'), ('ADDRESS','HIPAA'), ('ZIP','HIPAA'), ('MRN','HIPAA'), ('NPI','HIPAA'), ('DOB','HIPAA'), ('DIAGNOSIS','HIPAA'),
  ('NAME','DPDP'), ('EMAIL','DPDP'), ('AADHAAR','DPDP'), ('PAN','DPDP'), ('PHONE','DPDP'), ('ADDRESS','DPDP'), ('PIN','DPDP'), ('DOB','DPDP')
ON CONFLICT DO NOTHING;
