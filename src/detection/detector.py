"""Sensitive-identifier detector for HIPAA / DPDP data. Pure functions, no I/O.

Layers, all run on a *normalised view* of the text (invisible characters dropped, look-alike letters and non-Latin digits
folded, NFKC), with every hit mapped back to the original text:

1. structured patterns with checksum validators (SSN, Aadhaar, card, PAN, IBAN, IP, MAC ...)
2. cue patterns ("phone: ...", "MRN ...", "salary of Rs. ...") that accept any value format after a strong cue
3. key/value pairs, so {"patient_name": "..."} and "DOB: ..." are caught whatever the value looks like
4. names: titles, relationship and greeting cues, first-name gazetteer, "Surname, First"
5. disguised forms: "john [at] gmail [dot] com", digits spelled out, base64 / hex / percent / HTML-entity wrapped values
6. values already seen in the session (``find_known``), matched whatever the formatting

Overlapping hits are merged into one span so a value is never left half-visible.
"""

import base64
import binascii
import html
import ipaddress
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import unquote

from src.detection.names import FIRST_NAMES, NOT_NAME_WORDS

TOKEN_RX = re.compile(r"\btok_[a-z_]+_[0-9a-f]{12}\b")
_MASK = "\x00"


@dataclass(frozen=True)
class Entity:
    type: str
    start: int
    end: int
    value: str
    confidence: float = 0.95


# ---------------------------------------------------------------------------------------------------------------------
# validators
# ---------------------------------------------------------------------------------------------------------------------
_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _verhoeff(number: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def _luhn(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _iban(value: str) -> bool:
    s = re.sub(r"\s", "", value).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    moved = s[4:] + s[:4]
    return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _ipv6(value: str) -> bool:
    return value.count(":") >= 2 and _is_ip(value) and ipaddress.ip_address(value).version == 6


def _nd(lo: int, hi: int | None = None) -> Callable[[str], bool]:
    hi = lo if hi is None else hi
    return lambda v: lo <= len(_digits(v)) <= hi


def _money(v: str) -> bool:
    """An amount: has a currency marker or unit, or at least five digits (so "income tax 2020" is not a salary)."""
    return bool(re.search(r"Rs|INR|₹|\$|USD|€|£|lakh|lac|crore|\bcr\b|\bk\b|\bm\b|\bL\b|mn|LPA", v, re.I)) or len(_digits(v)) >= 5


def _has_digit(minlen: int = 1) -> Callable[[str], bool]:
    return lambda v: len(v.strip()) >= minlen and any(c.isdigit() for c in v)


# ---------------------------------------------------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------------------------------------------------
_CAP = r"[A-Z](?:['’][A-Z])?[a-z]+(?:\-[A-Z]?[a-z]+)?"
_NAME = rf"{_CAP}(?:\s+(?:[A-Z]\.\s*)?{_CAP}){{0,3}}"
_NAME_U = r"[A-Z]{2,}(?:\s+[A-Z]{2,}){0,3}"
_NAME_ANY = rf"(?:{_NAME}|{_NAME_U})"
_RUN = rf"\b(?:{_CAP}(?:\s+(?:[A-Z]\.\s*)?{_CAP}){{1,3}}|[A-Z]{{2,}}(?:\s+[A-Z]{{2,}}){{1,3}})\b"


def _named(v: str) -> bool:
    """For weak cues ("called", "hello"): accept two or more words, or one known first name."""
    w = v.split()
    return len(w) >= 2 or (bool(w) and w[0].lower() in FIRST_NAMES)


def _trim_name(value: str) -> str | None:
    """Cut a candidate name at the first non-name word ("Rahul Verma Hospital" -> "Rahul Verma")."""
    kept: list[str] = []
    for w in value.split():
        if w.strip(".,").lower() in NOT_NAME_WORDS:
            break
        kept.append(w)
    return " ".join(kept) if kept else None


def _person_like(value: str) -> bool:
    v = value.strip()
    if not v or any(c.isdigit() for c in v) or "@" in v or len(v.split()) > 5:
        return False
    return _trim_name(v) == v and v[:1].isalpha() and "_" not in v


# ---------------------------------------------------------------------------------------------------------------------
# normalisation (offsets map back to the original text)
# ---------------------------------------------------------------------------------------------------------------------
_CONFUSABLES = {
    **dict(zip("авсеіјорѕхуАВСЕНІЈКМОРЅТХ", "abceijopsxyABCEHIJKMOPSTX", strict=True)),
    **dict(zip("αεικνορυχΑΒΕΖΗΙΚΜΝΟΡΤΥΧ", "aeiknopuxABEZHIKMNOPTYX", strict=True)),
}


def normalize(text: str) -> tuple[str, list[int]]:
    """Return (normalised text, index map). Drops invisible/format characters, folds look-alikes and non-Latin digits."""
    out: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text):
        cat = unicodedata.category(ch)
        if cat == "Cf" or (cat == "Cc" and ch not in "\n\t\r") or (cat == "Mn" and out and out[-1].isascii()):
            continue
        if cat == "Nd":
            ch = str(unicodedata.digit(ch))
        ch = _CONFUSABLES.get(ch, ch)
        for c in unicodedata.normalize("NFKC", ch):
            out.append(c)
            idx.append(i)
    return "".join(out), idx


# ---------------------------------------------------------------------------------------------------------------------
# pattern rules: (type, regex, group, validator, confidence)
# ---------------------------------------------------------------------------------------------------------------------
Rule = tuple[str, "re.Pattern[str]", int, "Callable[[str], bool] | None", float]


def _r(etype: str, pattern: str, group: int = 0, ok: Callable[[str], bool] | None = None, conf: float = 0.9,
       flags: int = 0) -> Rule:
    return (etype, re.compile(pattern, flags), group, ok, conf)


_KW = r"[\s:#=\-]*(?:is\s+|was\s+|of\s+)?"
_AMOUNT = (r"(?:(?:Rs\.?|INR|₹|USD|US\$|\$|€|£)\s*)?\d[\d,]*(?:\.\d+)?"
           r"(?:\s*(?:lakhs?|lacs?|crores?|LPA|mn|cr|k|m|L)\b)?")
_STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA "
           "RI SC SD TN TX UT VT VA WA WV WI WY DC").split()
_STREET = (r"Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Boulevard|Blvd|Drive|Dr|Court|Ct|Way|Place|Pl|Nagar|Marg|Colony|Layout|"
           r"Cross|Sector|Block|Society|Apartments?|Residency|Highway|Hwy|Terrace|Circle|Chowk|Path|Gali")
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
_DATE = (rf"(?:\d{{4}}[-/.]\d{{1,2}}[-/.]\d{{1,2}}|\d{{1,2}}[-/.]\d{{1,2}}[-/.]\d{{2,4}}|"
         rf"\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH},?\s+\d{{2,4}}|{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{2,4}})")
_PHONE_CUE = (r"(?:phone|mobile|mob|cell|cellphone|tel|telephone|contact|whatsapp|call|fax|ph|helpline|reach me)"
              r"(?:\s*(?:no\.?|number|num|#))?")

_RULES: list[Rule] = [
    # --- contact ---
    _r("EMAIL", r"(?<![\w.%+\-])[\w.%+\-]+@[\w\-]+(?:\.[\w\-]+)*\.[A-Za-z]{2,}\b", conf=0.99),
    _r("EMAIL", r"\b[\w.\-]+\s*(?:\[at\]|\(at\)|\{at\}|<at>)\s*[\w\-]+(?:\s*(?:\[dot\]|\(dot\)|\{dot\}|\.)\s*[\w\-]+)+", conf=0.95, flags=re.I),
    _r("EMAIL", r"\b[\w.\-]+\s+at\s+[\w\-]+(?:\s+dot\s+[\w\-]+)+\b", conf=0.9, flags=re.I),
    _r("UPI", r"(?<![\w.%+\-])[\w.\-]{2,}@(?:ok(?:axis|hdfcbank|icici|sbi)|ybl|ibl|axl|paytm|upi|apl|sbi|hdfcbank|icici|axisbank|fbl|pnb|aubank|ikwik|postbank|barodampay|okhdfc)\b", conf=0.97),
    _r("URL", r"\b(?:https?://|www\.)[^\s<>\"')\]]+", conf=0.95, flags=re.I),
    _r("PHONE", r"(?<![\w.])(?:\(?\+?91\)?[\s.\-]?|0)?[6-9]\d{4}[\s.\-]?\d{5}(?!\d)", conf=0.88),
    _r("PHONE", r"(?<![\w.])(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]\d{4}(?!\d)", conf=0.85),
    _r("PHONE", r"(?<![\w.])\+\d{1,3}[\s.\-]?\(?\d{1,4}\)?(?:[\s.\-]?\d{2,5}){2,4}(?!\d)", ok=_nd(8, 15), conf=0.85),
    _r("PHONE", rf"\b{_PHONE_CUE}{_KW}(\+?\d[\d\s.\-()]{{6,18}}\d)", 1, _nd(7, 15), 0.9, re.I),
    # --- government / financial ids ---
    _r("SSN", r"\b(?!000|666|9\d\d)\d{3}[-.\s](?!00)\d{2}[-.\s](?!0000)\d{4}\b", conf=0.97),
    _r("SSN", rf"\b(?:ssn|social security(?: number| no\.?)?|sin){_KW}(\d{{3}}[-.\s]?\d{{2}}[-.\s]?\d{{4}})\b", 1, _nd(9), 0.95, re.I),
    _r("AADHAAR", r"(?<!\d)[2-9]\d{3}[\s.\-]?\d{4}[\s.\-]?\d{4}(?!\d)", ok=lambda v: _verhoeff(_digits(v)), conf=0.95),
    _r("AADHAAR", rf"\b(?:aadhaar|aadhar|adhaar|uidai|uid|aadhaar card){_KW}(\d{{4}}[\s.\-]?\d{{4}}[\s.\-]?\d{{4}})(?!\d)", 1, _nd(12), 0.95, re.I),
    _r("PAN", r"\b[A-Z]{5}\d{4}[A-Z]\b", conf=0.95),
    _r("PAN", rf"\bpan(?: card| number| no\.?)?{_KW}([A-Za-z]{{5}}\d{{4}}[A-Za-z])\b", 1, conf=0.95, flags=re.I),
    _r("CREDIT_CARD", r"(?<!\d)(?:\d[ .\-]?){12,18}\d(?!\d)", ok=lambda v: 13 <= len(_digits(v)) <= 19 and _luhn(_digits(v)), conf=0.97),
    _r("CREDIT_CARD", rf"\b(?:card|cc|credit|debit|visa|mastercard|master card|amex|rupay)(?: card)?(?: number| no\.?| num)?{_KW}((?:\d[ .\-]?){{12,18}}\d)(?!\d)", 1, _nd(13, 19), 0.9, re.I),
    _r("IMEI", r"(?<!\d)\d{15}(?!\d)", ok=_luhn, conf=0.8),
    _r("IMEI", rf"\bimei(?: number| no\.?)?{_KW}(\d{{15}})(?!\d)", 1, conf=0.95, flags=re.I),
    _r("MAC", r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b", conf=0.97),
    _r("IP", r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.]*\d)", conf=0.95),
    _r("IP", r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])", ok=_ipv6, conf=0.9),
    _r("VIN", r"\b[A-HJ-NPR-Z0-9]{17}\b", ok=lambda v: any(c.isdigit() for c in v) and any(c.isalpha() for c in v), conf=0.8),
    _r("PLATE", r"\b[A-Z]{2}[\s-]?\d{1,2}[\s-]?[A-Z]{1,3}[\s-]?\d{4}\b", conf=0.8),
    _r("PLATE", rf"\b(?:license plate|number plate|plate(?: number| no\.?)?|vehicle (?:number|no\.?)|registration (?:number|no\.?)){_KW}([A-Z0-9][A-Z0-9\- ]{{3,9}}[A-Z0-9])\b", 1, _has_digit(4), 0.85, re.I),
    _r("ACCOUNT", r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\s?[A-Z0-9]{0,4}\b", ok=_iban, conf=0.95),
    _r("ACCOUNT", r"\b[A-Z]{4}0[A-Z0-9]{6}\b", conf=0.85),
    _r("ACCOUNT", rf"\b(?:bank |savings |current |checking )?(?:account|acct|a/c|acc)(?: number| no\.?| num|#)?{_KW}(\d[\d\- ]{{5,28}}\d|[A-Z]{{2}}\d{{2}}[A-Z0-9]{{10,30}})\b", 1, lambda v: len(_digits(v)) >= 6, 0.9, re.I),
    _r("PASSPORT", rf"\bpassport(?: number| no\.?| num)?{_KW}([A-Z0-9]{{6,9}})\b", 1, _has_digit(6), 0.9, re.I),
    _r("VOTER_ID", rf"\b(?:voter(?: id| card)?|epic)(?: number| no\.?)?{_KW}([A-Z]{{3}}\d{{7}}|[A-Z0-9]{{8,12}})\b", 1, _has_digit(8), 0.9, re.I),
    _r("LICENSE", r"\b[A-Z]{2}[\s-]?\d{2}[\s-]?\d{4}[\s-]?\d{7}\b", conf=0.85),
    _r("LICENSE", rf"\b(?:driv(?:er|ing)'?s?[\s-]*licen[cs]e|licen[cs]e|dl|certificate|permit)(?: number| no\.?| num|#)?{_KW}([A-Z0-9][A-Z0-9\-/]{{5,19}})\b", 1, _has_digit(6), 0.88, re.I),
    _r("EMPLOYEE_ID", rf"\b(?:employee|emp|staff|student|roll|enrol?lment|registration|badge)[\s_-]*(?:id|no\.?|number|num){_KW}([A-Z0-9][A-Z0-9\-/]{{2,19}})\b", 1, _has_digit(3), 0.82, re.I),
    _r("USERNAME", rf"\b(?:username|user name|screen name|login name){_KW}@?([\w.\-]{{3,40}})", 1, conf=0.85, flags=re.I),
    _r("USERNAME", r"(?<![\w@./])@[A-Za-z0-9_]{3,30}\b", conf=0.75),
    _r("DEVICE_ID", rf"\b(?:device|advertising|ad|android|ios|hardware|serial|machine)[\s_-]*(?:id|identifier|number|no\.?){_KW}([A-Za-z0-9][A-Za-z0-9\-]{{7,40}})\b", 1, _has_digit(8), 0.82, re.I),
    _r("GPS", r"(?<![\d.])[-+]?\d{1,2}\.\d{4,}\s*[,;/]\s*[-+]?\d{1,3}\.\d{4,}(?![\d.])", conf=0.9),
    # --- health ---
    _r("MRN", rf"\b(?:MRN|M\.R\.N\.?|medical record(?: number| no\.?)?|medical record id|chart(?: number| no\.?| id)?|patient[\s_-]*(?:id|number|no\.?)|UHID|hospital id|record (?:id|number)){_KW}([A-Z0-9][A-Z0-9\-/]{{3,}})", 1, _has_digit(4), 0.95, re.I),
    _r("NPI", rf"\bNPI(?: number| no\.?)?{_KW}(\d{{10}})\b", 1, conf=0.95, flags=re.I),
    _r("HEALTH_ID", rf"\b(?:policy|member|subscriber|beneficiary|insurance|medicare|medicaid|hicn|mbi|health plan)(?:[\s_-]*(?:id|no\.?|number|num))?{_KW}([A-Z]{{0,4}}[- ]?\d{{5,}}[A-Z0-9\-]*)\b", 1, _has_digit(6), 0.85, re.I),
    _r("DOB", rf"\b(?:dob|d\.o\.b\.?|date of birth|birth ?date|birthday|b'day|born(?: on)?){_KW}({_DATE})", 1, conf=0.95, flags=re.I),
    _r("DATE", rf"\b(?:admission(?: date)?|admitted(?: on)?|discharge(?: date)?|discharged(?: on)?|date of (?:death|admission|discharge)|died(?: on)?|deceased|surgery(?: date)?|operated on|visit(?: date)?|service date|appointment(?: on| date)?|consultation|encounter|seen on){_KW}({_DATE})", 1, conf=0.9, flags=re.I),
    # --- geography ---
    _r("ADDRESS", rf"\b\d{{1,5}}[A-Za-z]?(?:[/\-]\d{{1,4}})?,?\s+(?:[A-Za-z0-9.'\-]+\s+){{0,4}}?(?:{_STREET})\b\.?(?:,?\s+[A-Z][A-Za-z.]+(?:\s[A-Z][A-Za-z.]+)?){{0,3}}(?:,?\s+\d{{5,6}}(?:-\d{{4}})?)?", conf=0.85, flags=re.I),
    _r("ADDRESS", r"\bP\.?\s?O\.?\s+Box\s+\d+\b", conf=0.9, flags=re.I),
    _r("ADDRESS", r"\b(?:flat|house|plot|door|apt|apartment|suite|unit)\s*(?:no\.?|number|#)?\s*[\w\-/]+,?(?:\s+[A-Za-z][\w.'\-]*){1,6}", ok=_has_digit(), conf=0.7, flags=re.I),
    _r("ADDRESS", rf"\b(?i:lives in|living in|resident of|residing in|resides in|city|hometown|village|district|town of|born in|native of|located in|based in)\s*[:\-]?\s+({_NAME})", 1, ok=_person_like, conf=0.7),
    _r("ZIP", rf"\b(?:zip(?:[\s_-]?code)?|postal[\s_-]?code|postcode){_KW}(\d{{5}}(?:-\d{{4}})?)\b", 1, conf=0.9, flags=re.I),
    _r("ZIP", rf"\b(?:{'|'.join(_STATES)})\s+(\d{{5}}(?:-\d{{4}})?)\b", 1, conf=0.85),
    _r("PIN", rf"\b(?:pin[\s_-]?code|pincode|pin){_KW}(\d{{6}})\b", 1, conf=0.9, flags=re.I),
    # --- money ---
    _r("SALARY", rf"\b(?:salary|salaries|income|ctc|wage|wages|earnings?|earns|earned|compensation|stipend|remuneration|paycheck|take[- ]home)\b[^\n\d₹$€£]{{0,30}}?({_AMOUNT})", 1, _money, 0.85, re.I),
    _r("SALARY", rf"({_AMOUNT})\s*(?:per\s+(?:annum|year|month)|p\.?a\.?|annually|monthly|/\s?(?:month|yr|year)|ctc|lpa)\b", 1, _money, 0.8, re.I),
    # --- people (cue based; the name part is case-sensitive so "patient records" never matches) ---
    _r("NAME", rf"\b(?i:dr|mr|mrs|ms|miss|mx|prof|shri|smt|sri|mister|doctor|nurse)\b\.?\s+({_NAME_ANY})", 1, conf=0.9),
    _r("NAME", rf"\b(?i:s/o|d/o|w/o|c/o|son of|daughter of|wife of|husband of|spouse|guardian|father|mother|parent|brother|sister|nominee|next of kin|emergency contact)\b\s*(?:name)?\s*[:\-]?\s*({_NAME_ANY})", 1, conf=0.85),
    _r("NAME", rf"\b(?i:patient|name|insured|policyholder|claimant|applicant|subscriber|beneficiary|physician|surgeon|referred by|seen by|treated by|attending)\s*(?:is|was|:|-|=)?\s+({_NAME_ANY})", 1, conf=0.8),
    _r("NAME", rf"\b(?i:named|called|employee|client|customer|resident|owner|holder|requested by|assigned to)\s*(?:is|was|:|-|=)?\s+({_NAME_ANY})", 1, ok=_named, conf=0.75),
    _r("NAME", rf"\b(?i:my name is|call me)\s+({_NAME})", 1, conf=0.85),
    _r("NAME", rf"\b(?i:i am|i'm|this is|dear|hi|hello|hey)\s+({_NAME})", 1, ok=_named, conf=0.7),
    _r("NAME", rf"\b(?i:regards|thanks|thank you|sincerely|signed|best wishes|cheers)[,\s]+({_NAME})", 1, ok=_named, conf=0.7),
    _r("NAME", rf"\b(?i:my name is|name is|name:)\s+([a-z]+(?:\s+[a-z]+){{1,2}})", 1, ok=lambda v: v.split()[0].lower() in FIRST_NAMES, conf=0.8),
    _r("NAME", rf"\b{_CAP},\s+[A-Z][a-z]+\b", 0, ok=lambda v: v.split(",")[-1].strip().lower() in FIRST_NAMES, conf=0.7),
]

# --- key/value pairs ---------------------------------------------------------------------------------------------------
_KV = re.compile(
    r"""(?P<kq>["']?)(?P<key>[A-Za-z][A-Za-z0-9_ \-.]{0,40}?)(?P=kq)\s*[:=]\s*
        (?:"(?P<dq>[^"\n]{1,160})"|'(?P<sq>[^'\n]{1,160})'|(?P<raw>[^\s,;}\]\)\n][^,;}\]\n]{0,100}))""",
    re.X,
)

_KEYS: dict[str, str] = {}
for _t, _names in {
    "SSN": "ssn social_security social_security_number",
    "AADHAAR": "aadhaar aadhar aadhaar_number aadhar_number adhaar uidai uid",
    "PAN": "pan pan_number pan_card pan_no",
    "DOB": "dob date_of_birth birth_date birthdate birthday born",
    "DATE": "admission_date discharge_date date_of_admission date_of_discharge date_of_death death_date appointment_date visit_date service_date",
    "PHONE": "phone phone_number phone_no mobile mobile_number mobile_no cell cell_phone cellphone telephone tel contact_number contact_no fax fax_number whatsapp",
    "EMAIL": "email email_address e_mail email_id emailid mail",
    "NAME": "name full_name patient_name first_name last_name middle_name surname given_name family_name guardian_name parent_name father_name mother_name spouse_name employee_name customer_name doctor_name nominee_name next_of_kin contact_name emergency_contact",
    "ADDRESS": "address street_address home_address mailing_address residential_address billing_address shipping_address street addr city town village district county residence",
    "ZIP": "zip zipcode zip_code postal_code postcode",
    "PIN": "pin pincode pin_code",
    "MRN": "mrn medical_record_number medical_record_no patient_id chart_number uhid record_number",
    "NPI": "npi npi_number",
    "PASSPORT": "passport passport_number passport_no",
    "ACCOUNT": "account account_number account_no acct bank_account bank_account_number iban ifsc ifsc_code routing_number",
    "CREDIT_CARD": "card card_number credit_card credit_card_number debit_card cc_number",
    "IP": "ip ip_address ipv4 ipv6",
    "MAC": "mac mac_address",
    "VIN": "vin vehicle_identification_number",
    "PLATE": "license_plate plate plate_number registration_number vehicle_number",
    "IMEI": "imei",
    "DEVICE_ID": "device_id serial_number serial_no advertising_id ad_id android_id idfa gaid udid browser_info user_agent",
    "UPI": "upi upi_id vpa",
    "HEALTH_ID": "policy_number policy_no member_id subscriber_id insurance_id beneficiary_id health_plan_id medicare_id insurance_number group_number",
    "LICENSE": "license licence license_number licence_number driving_license driving_licence driver_license driving_license_number dl_number dl_no certificate_number certificate_no",
    "VOTER_ID": "voter_id voter_id_number epic_number",
    "SALARY": "salary income annual_income monthly_income ctc wage compensation annual_salary monthly_salary gross_salary net_salary",
    "EMPLOYEE_ID": "employee_id emp_id emp_no staff_id student_id roll_no roll_number enrollment_number",
    "USERNAME": "username user_name screen_name",
    "GPS": "gps gps_coordinates coordinates latitude longitude lat lng lon location_history geo",
    "URL": "url website homepage profile_url",
}.items():
    for _n in _names.split():
        _KEYS[_n] = _t

_KV_OK: dict[str, Callable[[str], bool]] = {
    "SSN": _nd(9), "AADHAAR": _nd(12), "PAN": lambda v: bool(re.fullmatch(r"[A-Za-z]{5}\d{4}[A-Za-z]", v.strip())),
    "DOB": _has_digit(), "DATE": _has_digit(), "PHONE": _nd(7, 15), "EMAIL": lambda v: "@" in v or " at " in v.lower() or "[at]" in v.lower(),
    "NAME": _person_like, "ADDRESS": lambda v: len(v.strip()) >= 3 and any(c.isalpha() for c in v) and v.strip().lower() not in NOT_NAME_WORDS,
    "ZIP": _nd(5, 9), "PIN": _nd(6), "MRN": _has_digit(3), "NPI": _nd(10), "PASSPORT": _has_digit(6),
    "ACCOUNT": lambda v: len(_digits(v)) >= 6 or _iban(v), "CREDIT_CARD": _nd(13, 19), "IP": _is_ip,
    "MAC": lambda v: bool(re.fullmatch(r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}", v.strip())), "VIN": lambda v: len(v.strip()) == 17,
    "PLATE": _has_digit(4), "IMEI": _nd(15), "DEVICE_ID": lambda v: len(v.strip()) >= 6, "UPI": lambda v: "@" in v,
    "HEALTH_ID": _has_digit(4), "LICENSE": _has_digit(5), "VOTER_ID": _has_digit(8), "SALARY": _has_digit(), "EMPLOYEE_ID": _has_digit(3),
    "USERNAME": lambda v: len(v.strip().lstrip("@")) >= 3, "GPS": _has_digit(), "URL": lambda v: "." in v,
}

_DIGIT_WORDS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
                "seven": "7", "eight": "8", "nine": "9"}
_SPELLED = re.compile(r"\b(?:(?:" + "|".join(_DIGIT_WORDS) + r")[\s,\-]+){8,}(?:" + "|".join(_DIGIT_WORDS) + r")\b", re.I)
_SPELLED_TYPE = {9: "SSN", 10: "PHONE", 12: "AADHAAR", 15: "IMEI", 16: "CREDIT_CARD"}

_B64 = re.compile(r"(?<![\w+/=\-])[A-Za-z0-9+/_\-]{24,}={0,2}(?![\w+/=])")
_HEX = re.compile(r"(?<![\w])(?:[0-9a-fA-F]{2}){12,}(?![\w])")
_PCT = re.compile(r"\S*%[0-9A-Fa-f]{2}\S*")
_ENT = re.compile(r"\S*&(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z]+);\S*")
_UESC = re.compile(r"\S*\\u[0-9a-fA-F]{4}\S*")

_RANK = {"EMAIL": 0, "UPI": 0, "URL": 0, "SSN": 1, "AADHAAR": 1, "CREDIT_CARD": 1, "PAN": 1, "MAC": 1, "IP": 2}


# ---------------------------------------------------------------------------------------------------------------------
# scanning
# ---------------------------------------------------------------------------------------------------------------------
def _scan_rules(norm: str) -> list[Entity]:
    out: list[Entity] = []
    for etype, rx, group, ok, conf in _RULES:
        for m in rx.finditer(norm):
            s, e = m.start(group), m.end(group)
            value = norm[s:e]
            if not value or _MASK in value:
                continue
            if etype == "NAME":
                trimmed = _trim_name(value)
                if trimmed is None:
                    continue
                e, value = s + len(trimmed), trimmed
            if ok and not ok(value):
                continue
            out.append(Entity(etype, s, e, value, conf))
    return out


def _key_type(key: str) -> str | None:
    words = [w for w in re.split(r"[\s_\-.]+", key.lower()) if w]
    for n in (3, 2, 1):
        if len(words) >= n and (t := _KEYS.get("_".join(words[-n:]))):
            return t
    return None


def _scan_kv(norm: str) -> list[Entity]:
    out: list[Entity] = []
    for m in _KV.finditer(norm):
        etype = _key_type(m.group("key"))
        if etype is None:
            continue
        name = "dq" if m.group("dq") is not None else "sq" if m.group("sq") is not None else "raw"
        s, value = m.start(name), m.group(name)
        if name == "raw":
            cut = re.search(r"\s+[A-Za-z_][\w ]{1,20}\s*[:=]", value)
            if cut:
                value = value[: cut.start()]
            stripped = value.rstrip(" .;\"'")
            value = stripped
        if not value.strip() or _MASK in value or value.strip().lower() in {"null", "none", "n/a", "na", "unknown", "true", "false"}:
            continue
        if etype == "NAME":
            trimmed = _trim_name(value)
            if trimmed is None:
                continue
            value = trimmed
            if m.group("key").strip().lower() == "name" and not (value[:1].isupper() or value.split()[0].lower() in FIRST_NAMES):
                continue
        if _KV_OK[etype](value):
            out.append(Entity(etype, s, s + len(value), value, 0.9))
    return out


def _scan_names(norm: str) -> list[Entity]:
    """Runs of capitalised words that contain a known first name ("Rahul Verma", "PRIYA SHARMA", "Will Smith")."""
    out: list[Entity] = []
    for m in re.finditer(_RUN, norm):
        words = list(re.finditer(r"\S+", m.group(0)))
        for i, w in enumerate(words):
            if w.group(0).strip(".,").lower() in FIRST_NAMES:
                tail = _trim_name(m.group(0)[w.start():])
                if tail and len(tail.split()) >= 2:
                    s = m.start() + w.start()
                    out.append(Entity("NAME", s, s + len(tail), tail, 0.7))
                break
    return out


def _scan_spelled(norm: str) -> list[Entity]:
    out: list[Entity] = []
    for m in _SPELLED.finditer(norm):
        digits = "".join(_DIGIT_WORDS[w.lower()] for w in re.findall(r"[A-Za-z]+", m.group(0)))
        out.append(Entity(_SPELLED_TYPE.get(len(digits), "ACCOUNT"), m.start(), m.end(), m.group(0), 0.75))
    return out


def _printable(raw: bytes) -> str | None:
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if len(s) < 6:
        return None
    return s if sum(c.isprintable() or c in "\n\t\r" for c in s) / len(s) >= 0.9 else None


def _scan_encoded(norm: str, depth: int) -> list[Entity]:
    """Values hidden inside base64 / hex / percent / HTML-entity / \\u escapes: decode, scan, flag the whole wrapper."""
    if depth >= 2:
        return []
    cands: list[tuple[int, int, str | None]] = []
    for m in _B64.finditer(norm):
        raw = m.group(0)
        if _MASK in raw or TOKEN_RX.search(raw):
            continue
        try:
            pad = raw + "=" * (-len(raw) % 4)
            data = base64.urlsafe_b64decode(pad) if ("-" in raw or "_" in raw) else base64.b64decode(pad, validate=True)
        except (binascii.Error, ValueError):
            continue
        cands.append((m.start(), m.end(), _printable(data)))
    for m in _HEX.finditer(norm):
        try:
            cands.append((m.start(), m.end(), _printable(bytes.fromhex(m.group(0)))))
        except ValueError:
            continue
    for rx, dec in ((_PCT, unquote), (_ENT, html.unescape), (_UESC, lambda t: t.encode().decode("unicode_escape", "ignore"))):
        for m in rx.finditer(norm):
            decoded = dec(m.group(0))
            if decoded != m.group(0):
                cands.append((m.start(), m.end(), decoded))
    out = []
    for s, e, decoded in cands:
        if decoded and _scan(decoded, depth + 1):
            out.append(Entity("ENCODED", s, e, norm[s:e], 0.85))
    return out


def _merge_overlaps(found: list[Entity]) -> list[Entity]:
    """Union overlapping hits into one span so no value is left half-visible; the best-ranked member names it."""
    found = sorted(found, key=lambda e: (e.start, -e.end))
    groups: list[list[Entity]] = []
    for e in found:
        if groups and e.start < max(x.end for x in groups[-1]):
            groups[-1].append(e)
        else:
            groups.append([e])
    return groups_to_entities(groups)


def groups_to_entities(groups: list[list[Entity]]) -> list[Entity]:
    out = []
    for g in groups:
        best = min(g, key=lambda e: (_RANK.get(e.type, 3), -(e.end - e.start), -e.confidence))
        out.append(Entity(best.type, min(x.start for x in g), max(x.end for x in g), "", best.confidence))
    return out


def _scan(norm: str, depth: int = 0) -> list[Entity]:
    found = _scan_rules(norm) + _scan_kv(norm) + _scan_names(norm) + _scan_spelled(norm) + _scan_encoded(norm, depth)
    merged = _merge_overlaps(found)
    return [Entity(e.type, e.start, e.end, norm[e.start:e.end], e.confidence) for e in merged]


def _mask_tokens(norm: str, trusted: set[str] | None) -> str:
    if not trusted:
        return norm
    return TOKEN_RX.sub(lambda m: _MASK * len(m.group(0)) if m.group(0) in trusted else m.group(0), norm)


def _back(ents: list[Entity], idx: list[int], text: str) -> list[Entity]:
    out = []
    for e in ents:
        s, t = idx[e.start], idx[e.end - 1] + 1
        out.append(Entity(e.type, s, t, text[s:t], e.confidence))
    return out


def detect(text: str, types: set[str] | None = None, trusted_tokens: set[str] | None = None) -> list[Entity]:
    """Return non-overlapping entities found in ``text`` (offsets refer to ``text``).

    ``types`` restricts the entity codes. ``trusted_tokens`` are vault tokens known to be genuine: they are skipped.
    A token-shaped string that is not trusted is scanned like any other text (so a crafted fake token cannot smuggle a value).
    """
    norm, idx = normalize(text)
    ents = _back(_scan(_mask_tokens(norm, trusted_tokens)), idx, text)
    ents = _merge_overlaps(ents)
    ents = [Entity(e.type, e.start, e.end, text[e.start:e.end], e.confidence) for e in ents]
    return [e for e in ents if types is None or e.type in types]


# ---------------------------------------------------------------------------------------------------------------------
# values already seen in the session
# ---------------------------------------------------------------------------------------------------------------------
_DIGIT_TYPES = {"SSN", "AADHAAR", "PHONE", "CREDIT_CARD", "ACCOUNT", "MRN", "NPI", "ZIP", "PIN", "IMEI", "PASSPORT", "EMPLOYEE_ID",
                "HEALTH_ID", "LICENSE", "VOTER_ID", "DEVICE_ID"}


def _known_patterns(etype: str, value: str) -> list["re.Pattern[str]"]:
    pats: list[re.Pattern[str]] = []
    v = value.strip()
    if "tok_" in v or re.fullmatch(r"[\[<{(].*[\]>})]", v) or not any(c.isalnum() for c in v):
        return pats  # a vault token or template text ("[Name]") is not a real value to look for
    if etype in _DIGIT_TYPES and len(_digits(v)) >= 6:
        parts = [re.escape(c) for c in re.sub(r"[^0-9A-Za-z]", "", v)]
        pats.append(re.compile(r"(?<![0-9A-Za-z])" + r"[\s.\-_/]*".join(parts) + r"(?![0-9A-Za-z])", re.I))
    elif len(v) >= 4:
        pats.append(re.compile(r"(?<!\w)" + re.escape(v) + r"(?!\w)", re.I))
    if etype == "NAME":
        for w in v.split():
            if len(w) >= 3 and w.lower() not in NOT_NAME_WORDS:
                pats.append(re.compile(rf"(?<!\w)(?:{re.escape(w.capitalize())}|{re.escape(w.upper())})(?!\w)"))
    return pats


def find_known(text: str, known: list[tuple[str, str]]) -> list[Entity]:
    """Entities for values already seen in this session (``known`` = [(type, value)]), whatever the formatting.

    Numbers match with any separators ("123456789" finds a known "123-45-6789"); names also match by part
    ("Alice Smith" finds a later "Smith"); everything is checked on the normalised view of ``text``.
    """
    norm, idx = normalize(text)
    out: list[Entity] = []
    for etype, value in known:
        for pat in _known_patterns(etype, value):
            out += [Entity(etype, m.start(), m.end(), m.group(0), 0.9) for m in pat.finditer(norm)]
    return _back(out, idx, text)


def merge(primary: list[Entity], extra: list[Entity], text: str) -> list[Entity]:
    """Combine two entity lists over ``text``; overlapping spans are unioned so nothing is left half-visible."""
    merged = _merge_overlaps(sorted(primary + extra, key=lambda e: (e.start, -e.end)))
    return [Entity(e.type, e.start, e.end, text[e.start:e.end], e.confidence) for e in merged]
