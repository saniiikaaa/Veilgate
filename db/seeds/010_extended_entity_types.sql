INSERT INTO entity_types (code, name, sensitivity, description) VALUES
  ('LICENSE',     'Licence / certificate number', 'high',     'Driving licence, professional certificate or permit number'),
  ('VOTER_ID',    'Voter id',                     'high',     'India voter / EPIC number'),
  ('SALARY',      'Salary or income',             'high',     'Compensation amount tied to a person'),
  ('EMPLOYEE_ID', 'Employee / student id',        'medium',   'Staff, student or roll number'),
  ('USERNAME',    'Username or handle',           'medium',   'Account username or social handle'),
  ('GPS',         'GPS coordinates',              'high',     'Latitude / longitude pair'),
  ('DEVICE_ID',   'Device identifier',            'medium',   'Advertising id, serial number, browser fingerprint'),
  ('PLATE',       'Vehicle plate',                'medium',   'Vehicle registration / licence plate'),
  ('DATE',        'Event date',                   'high',     'Admission, discharge, death, service or visit date'),
  ('ENCODED',     'Encoded sensitive value',      'high',     'Sensitive data hidden in base64, hex, percent or entity encoding')
ON CONFLICT (code) DO NOTHING;

INSERT INTO entity_type_frameworks (entity_type_code, framework_code) VALUES
  ('LICENSE','HIPAA'), ('PLATE','HIPAA'), ('DEVICE_ID','HIPAA'), ('DATE','HIPAA'), ('GPS','HIPAA'), ('ENCODED','HIPAA'), ('USERNAME','HIPAA'),
  ('LICENSE','DPDP'), ('VOTER_ID','DPDP'), ('SALARY','DPDP'), ('EMPLOYEE_ID','DPDP'), ('USERNAME','DPDP'), ('GPS','DPDP'),
  ('DEVICE_ID','DPDP'), ('PLATE','DPDP'), ('DATE','DPDP'), ('ENCODED','DPDP')
ON CONFLICT DO NOTHING;
