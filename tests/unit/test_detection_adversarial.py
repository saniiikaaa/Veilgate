"""Every case here is a way a value could slip through. The secret must not survive masking."""

import base64

import pytest

from src.detection import detect, find_known, merge


def mask(text: str, known: list[tuple[str, str]] | None = None) -> str:
    ents = merge(detect(text), find_known(text, known or []), text)
    out, pos = [], 0
    for e in ents:
        out += [text[pos:e.start], f"<{e.type}>"]
        pos = e.end
    return "".join(out) + text[pos:]


# (text, secret that must be gone)
LEAKS = [
    # --- formats and separators
    ("ssn 123 45 6789", "6789"),
    ("ssn is 123456789", "123456789"),
    ("SSN: 123.45.6789", "6789"),
    ("call (555) 123-4567 now", "4567"),
    ("phone: 5551234567", "5551234567"),
    ("mobile 98765 43210", "43210"),
    ("whatsapp +91-98765-43210", "43210"),
    ("tel 098765 43210", "43210"),
    ("Call +44 20 7946 0958", "0958"),
    ("card 4111 1111 1111 1111", "1111 1111"),
    ("card number 4111-1111-1111-1112", "1112"),  # fails Luhn, still caught by the cue
    ("aadhaar 2345 6789 0123", "6789"),  # fails Verhoeff, still caught by the cue
    ("my uid is 234567890123", "234567890123"),
    ("PAN card: abcde1234f", "1234"),
    ("passport no. K1234567", "K1234567"),
    ("A/C 123456789012", "123456789012"),
    ("IBAN GB82 WEST 1234 5698 7654 32", "7654 32"),
    ("IFSC HDFC0001234", "HDFC0001234"),
    ("DL no MH1220110062821", "MH1220110062821"),
    ("voter id ABC1234567", "ABC1234567"),
    ("vehicle MH12AB1234 parked", "MH12AB1234"),
    ("IMEI 490154203237518", "490154203237518"),
    ("device id A1B2C3D4E5F6G7H8", "A1B2C3D4E5F6G7H8"),
    ("employee id EMP-20931", "20931"),
    ("username: rahul_v99", "rahul_v99"),
    ("follow @rahul_v99 today", "rahul_v99"),
    ("at 12.971599, 77.594566", "12.971599"),
    ("ipv6 2001:0db8:85a3:0000:0000:8a2e:0370:7334", "7334"),
    ("visit https://hospital.example.org/p/884213?t=abc", "884213"),
    ("see www.clinic.in/records/55", "records/55"),
    ("UPI rahul@okaxis", "okaxis"),
    ("zip code 62701", "62701"),
    ("Springfield, IL 62701", "62701"),
    ("pincode 560001", "560001"),
    ("lives at 221B Baker Street, London", "Baker"),
    ("12/3 MG Road, Bengaluru 560001", "MG Road"),
    ("P.O. Box 4521", "4521"),
    ("flat no 12, Green Park Apartments", "Green Park"),
    ("DOB: 14/02/1980", "1980"),
    ("born on March 5, 1975", "1975"),
    ("date of birth 5th March 1975", "1975"),
    ("admitted on 2024-03-01", "2024-03-01"),
    ("discharged on 12 Jan 2025", "2025"),
    ("MRN: 00884213", "00884213"),
    ("UHID AB-99812", "99812"),
    ("policy number HX-445566", "445566"),
    ("NPI 1234567893", "1234567893"),
    ("salary of Rs. 12,00,000", "12,00,000"),
    ("CTC is 18 LPA", "18 LPA"),
    ("earns $85,000 a year", "85,000"),
    ("₹12,00,000 per annum", "12,00,000"),
    # --- people
    ("Patient: Rahul Verma was seen", "Verma"),
    ("Dr. Alice Smith called", "Smith"),
    ("DR. PRIYA SHARMA", "SHARMA"),
    ("my name is Anita Desai", "Desai"),
    ("my name is rahul verma", "verma"),
    ("Hello Sunita Rao,", "Rao"),
    ("Regards, Vikram Singh", "Singh"),
    ("son of Mohan Lal", "Lal"),
    ("guardian: Kavita Nair", "Nair"),
    ("Verma, Rahul visited", "Verma"),
    ("Rahul Verma visited the clinic", "Verma"),
    ("PRIYA SHARMA visited", "SHARMA"),
    ("Contact Mr O'Brien", "Brien"),
    # --- structured
    ('{"patient_name": "Rahul Verma", "x": 1}', "Verma"),
    ('{"name": "Rahul Verma"}', "Verma"),
    ('{"dob": "1980-02-14"}', "1980"),
    ('{"phone": "9876543210"}', "9876543210"),
    ('{"aadhaar": "234567890124"}', "234567890124"),
    ('{"ssn": "123456789"}', "123456789"),
    ('{"email": "a@b.co"}', "a@b.co"),
    ("Name: Rahul Verma DOB: 1980-02-14", "1980"),
    ("salary: 1200000", "1200000"),
    ("address: 12 Park Lane, Pune", "Park Lane"),
    ("city: Pune", "Pune"),
    # --- disguised
    ("mail john [at] gmail [dot] com", "gmail"),
    ("mail john at gmail dot com", "gmail"),
    ("john(at)gmail.com", "gmail"),
    ("ssn １２３-４５-６７８９", "６７８９"),  # fullwidth digits
    ("ssn ١٢٣-٤٥-٦٧٨٩", "٦٧٨٩"),  # Arabic-Indic
    ("ssn 123​-45‌-6789", "6789"),  # zero-width characters
    ("emаil: j.doe@gmail.com", "j.doe"),  # Cyrillic a in the cue word
    ("j.dоe@gmail.com", "gmail"),  # Cyrillic o in the address
    ("phone nine eight seven six five four three two one zero", "nine eight"),
    ("data " + base64.b64encode(b"ssn 123-45-6789 for Rahul").decode(), "MTIz"),
    ("hex " + b"email a.b@gmail.com".hex(), "656d"),
    ("mail john%40gmail.com", "john%40gmail.com"),
    ("mail john&#64;gmail.com", "john&#64;gmail.com"),
]


@pytest.mark.parametrize("text,secret", LEAKS)
def test_secret_does_not_survive(text, secret):
    assert secret not in mask(text), mask(text)


def test_reformatted_known_values_are_caught_again():
    known = [("SSN", "123-45-6789"), ("PHONE", "+91 98765 43210"), ("NAME", "Alice Smith"), ("EMAIL", "a.smith@mail.com")]
    assert "6789" not in mask("the number was 123456789", known)
    assert "43210" not in mask("ring 9876543210 later", known)
    assert "Smith" not in mask("ask SMITH about it", known)
    assert "A.SMITH@MAIL.COM" not in mask("write to A.SMITH@MAIL.COM", known)


def test_fake_vault_token_cannot_smuggle_a_value():
    text = "id tok_aadhaar_234567890124 end"
    assert "234567890124" not in mask(text)  # not trusted -> scanned
    ents = detect(text, trusted_tokens={"tok_aadhaar_234567890124"})
    assert ents == []  # a genuine, vault-issued token is left alone


def test_overlapping_hits_are_one_span():
    ents = detect("Contact: Dr. Alice Smith at alice.smith@mail.com")
    assert not any(a.end > b.start for a, b in zip(ents, ents[1:]))


# --- things that must NOT be flagged ---------------------------------------------------------------------------------
CLEAN = [
    "Please summarise the quarterly report for the finance team.",
    "Patient Records are stored securely in the data centre.",
    "Hello World, this is a test of the system.",
    "The version is 2.4.1 and the build number is 20241031.",
    "Total revenue grew 12% to 4,500 units in March.",
    "Call customer care for support.",
    "Thanks Team, see you on Monday.",
    "The City Hospital opens at 9am.",
    "Use the search tool to look up the policy document.",
    "In 2024 we shipped 3 releases.",
    "Grace Period applies for ten days.",
]


@pytest.mark.parametrize("text", CLEAN)
def test_ordinary_text_is_left_alone(text):
    assert detect(text) == [], [e.value for e in detect(text)]
