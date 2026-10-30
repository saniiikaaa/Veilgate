from src.detection import detect, find_known, merge


def kinds(text):
    return {(e.type, e.value) for e in detect(text)}


def test_core_identifiers():
    got = kinds("SSN 123-45-6789, mail a@b.com, card 4532 0151 1283 0366, PAN ABCDE1234F, ip 10.0.0.1")
    assert ("SSN", "123-45-6789") in got
    assert ("EMAIL", "a@b.com") in got
    assert ("CREDIT_CARD", "4532 0151 1283 0366") in got
    assert ("PAN", "ABCDE1234F") in got
    assert ("IP", "10.0.0.1") in got


def test_luhn_rejects_random_digits():
    assert not [e for e in detect("order 1234 5678 9012 3456") if e.type == "CREDIT_CARD"]


def test_title_name_not_swallowed_by_keyword_rule():
    # "patient" must not swallow the title: the whole person is one span, never a lone "Dr"
    names = [e.value for e in detect("patient Dr. Alice Smith") if e.type == "NAME"]
    assert names and all("Alice Smith" in n for n in names) and "Dr" not in [n.strip(". ") for n in names]


def test_context_rules_need_a_cue():
    assert not detect("version 62701 shipped")
    assert ("ZIP", "62701") in kinds("zip code 62701")


def test_known_values_and_merge():
    text = "SSN 123-45-6789 for Smith"
    extra = find_known(text, [("NAME", "Alice Smith")])
    assert [e.value for e in merge(detect(text), extra, text)] == ["123-45-6789", "Smith"]
