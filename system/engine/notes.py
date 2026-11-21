"""Customer note -> NoteFacts. Module B.

parse(note) -> NoteFacts. `note` is a raw notes.jsonl row (load.py keeps the
dict, including channel and note_id) or a plain string.

resolve.py reads verified, rejected, name, dob (PartialDate or str),
doc_country, lived_in (list of country names) and date. It stamps
note["note_id"] onto the Facts it builds, which is what explain.py cites.
`source` on NoteFacts is that same NOTE- id so the id travels with the parse
result too.

Slots, not sentence templates. channel decides which slots apply:

- kyc: a successful check. Name is the longest run of 2+ ALL-CAPS tokens
  (accents allowed; placeholder-only runs like N/A or 0000 are skipped).
  dob is the date nearest DOB/born/date of birth, else a date in parentheses.
  The other date, nearest "on" / "as of", is the check date (`date`).
  doc_country is countries.normalise of the phrase after from / in / issued in /
  issued by / originating from / ctry, or before a document type, or in
  brackets. verified needs a success word, no failure word, and all three slots.
  rejected / failed / expired / could not -> rejected, and those slots are
  not evidence.
- email, phone: if a real country (capitalised span, countries.normalise)
  AND a residence or work word appear, lived_in is that country. verified stays
  false. A country may be named first ("Nigeria was the location where...").
- app, or no channel: ignore. Unknown stays unknown.

Slash dates are day first; dates.parse does that. countries.normalise returns
None for anything it does not know, including "It" once we refuse 1-3 letter
tokens (those are "It"/"In", which normalise to Italy/India).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from .model import PartialDate

try:
    from .countries import normalise as _normalise_country
except ImportError:  # module C not importable
    def _normalise_country(value):
        return None

try:
    from .dates import parse as _parse_date
except ImportError:
    def _parse_date(value):
        return None


@dataclass
class NoteFacts:
    verified: bool = False
    rejected: bool = False
    name: Optional[str] = None
    dob: Optional[PartialDate] = None
    doc_country: Optional[str] = None
    lived_in: List[str] = field(default_factory=list)
    date: Optional[object] = None  # PartialDate of the check, or created_at str
    source: Optional[str] = None   # NOTE-... the facts came from


_SUCCESS = re.compile(
    r"(?i)\b(?:verified|confirmed|validated|passed|cleared|matches|processed|approved|completed)\b"
    r"|\bsuccessful(?:\s+check)?\b")
_FAILURE = re.compile(
    r"(?i)\b(?:rejected|failed|expired|could not|couldn't|unable|declined|mismatch)\b")
_NEGATED = re.compile(r"(?i)\b(?:not|never|no|un)\b(?:\s+\w+){0,2}\s*$")
_DOB_KW = re.compile(
    r"(?i)(?:\bb\.(?!\w)|\b(?:d\.?o\.?b\.?|date of birth|birth date|born)\b)")
_AMBIGUOUS_BIRTH = re.compile(
    r"(?i)\b(?:born|b\.|d\.?o\.?b\.?|date of birth|birth date)\b\s*(?:in\s+)?"
    r"\d{4}\s*(?:or|/|and)\s*\d{4}")
_CHECKED = re.compile(r"(?i)\b(?:was|were)\s+checked\b")
_CHECK_KW = re.compile(r"(?i)\b(?:as of|on)\b")
_DOC = re.compile(
    r"(?i)\b(?:passports?|driving licences?|driving licenses?|national ids?|"
    r"national identity cards?|identity cards?|id cards?)\b")
_RESIDENCE = re.compile(
    r"(?i)live|lived|living|resid|home|based|settled|relocat|work|employ|job|position")
_DATE_RES = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{4}-\d{2}(?!-\d)\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b"),
    re.compile(r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b"),
    re.compile(r"\b[A-Za-z]+\s+\d{1,2},\s*\d{4}\b"),
    re.compile(r"\b[A-Za-z]+\s+\d{4}\b"),
)
_CUES = (
    re.compile(r"(?i)\boriginating from\s+"),
    re.compile(r"(?i)\bissued in\s+"),
    re.compile(r"(?i)\bissued by\s+"),
    re.compile(r"(?i)\bfrom the\s+"),
    re.compile(r"(?i)\bctry\s+"),
    re.compile(r"(?i)\bfrom\s+"),
    re.compile(r"(?i)\bin\s+"),
    re.compile(r"(?i)\b(?:issuing country|issuing authority|country of issue|country of issuance|origin country)\s*(?:is|of|:)?\s*(?:the\s+)?"),
    re.compile(r"(?i)\b(?:document\s+)?country\s+is\s+(?:the\s+)?"),
    re.compile(r"(?i)\bcountry\s+of\s+origin\s*:?\s*(?:the\s+)?"),
    re.compile(r"(?i)\bdocument\s+(?:country|origin)\s*:?\s*(?:is\s+)?(?:the\s+)?"),
    re.compile(r"(?i)\bfor the country\s+"),
    re.compile(r"(?i)\ba citizen of\s+"),
    re.compile(r"(?i)\bnationality as\s+"),
    re.compile(r"(?i)\bthe country as\s+"),
    re.compile(r"(?i)\bsubmitted by\s+"),
    re.compile(r"(?i)\bprovided by\s+"),
    re.compile(r"(?i)\borigin\s+"),
    re.compile(r"(?i)\bwithin\s+"),
    re.compile(r"(?i)\bfor\s+"),
)
_WORD = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’\-]*")
# Latin Extended-A/B so accented capitals (Ć, Š, …) stay inside the name token.
_TOKEN = re.compile(r"[0-9A-Za-z\u00C0-\u024F\u1E00-\u1EFF'’/\-]+")
_PLACEHOLDERS = {"na", "n/a", "n.a", "n.a.", "none", "unknown", "test", "xxx", "null", "nil", "0000"}
# All-caps cue words sit next to the name. They are not name tokens.
_NAME_BREAKS = {"dob", "d.o.b", "d.o.b.", "born", "date", "birth", "of", "id"}


def parse(note) -> NoteFacts:
    """Slots from one note. A missing slot stays missing."""
    text, created, channel, source = _parts(note)
    if channel == "app" or not text:
        return NoteFacts(source=source)
    if channel == "kyc":
        return _parse_kyc(text, created, source)
    if channel in ("email", "phone"):
        return _parse_residence(text, created, source)
    return NoteFacts(source=source, date=created)


def _parts(note):
    if isinstance(note, str):
        return note, None, "", None
    if not isinstance(note, dict):
        return "", None, "", None
    text = "" if note.get("text") is None else str(note.get("text"))
    created = note.get("created_at")
    created = str(created).strip() if created is not None and str(created).strip() else None
    channel = str(note.get("channel") or "").strip().casefold()
    source = note.get("note_id")
    source = str(source).strip() if source is not None and str(source).strip() else None
    return text, created, channel, source


def _flag(pattern, text):
    for match in pattern.finditer(text):
        window = text[max(0, match.start() - 24):match.start()]
        if _NEGATED.search(window):
            continue
        return True
    return False


def _is_placeholder(token):
    folded = token.casefold().strip(".")
    if folded in _PLACEHOLDERS or folded.replace("/", "") in {"na", "na."}:
        return True
    return folded.isdigit()


def _name_token(token):
    """Drop a possessive so SMITH's / SMITHs still counts as a caps token."""
    token = re.sub(r"['’]s$", "", token, flags=re.IGNORECASE)
    if re.fullmatch(r"[A-ZÀ-ÖØ-Þ]{2,}s", token):
        token = token[:-1]
    return token


def _is_caps(token):
    token = _name_token(token)
    if token.casefold().strip(".") in _NAME_BREAKS:
        return False
    letters = [ch for ch in token if ch.isalpha()]
    if letters and all(ch.isupper() for ch in letters):
        return True
    return _is_placeholder(token)


def _inside_parens(text, pos):
    return text[:pos].count("(") > text[:pos].count(")")


def _name(text):
    """Longest caps run outside brackets. Placeholders stay in the run but are dropped."""
    runs = []
    current = []
    current_at = None
    prev_end = 0
    for match in _TOKEN.finditer(text):
        if current and re.search(r"[()]", text[prev_end:match.start()]):
            runs.append((current_at, current))
            current = []
            current_at = None
        token = _name_token(match.group(0))
        if _is_caps(match.group(0)):
            if current_at is None:
                current_at = match.start()
            current.append(token)
        elif current:
            runs.append((current_at, current))
            current = []
            current_at = None
        prev_end = match.end()
    if current:
        runs.append((current_at, current))
    ranked = []
    for start, tokens in runs:
        real = [token for token in tokens if not _is_placeholder(token)]
        if not real:
            continue
        ranked.append((_inside_parens(text, start), -len(real), start, real))
    ranked.sort()
    if not ranked:
        return None
    return " ".join(ranked[0][3])


def _dates(text):
    found = []
    occupied = []

    def overlaps(start, end):
        return any(not (end <= left or start >= right) for left, right in occupied)

    for pattern in _DATE_RES:
        for match in pattern.finditer(text):
            if overlaps(match.start(), match.end()):
                continue
            parsed = _parse_date(match.group(0))
            if parsed is None or parsed.year is None:
                continue
            found.append((match.start(), match.end(), parsed))
            occupied.append((match.start(), match.end()))
    # A bare year is a birth date only when it is the single year glued to a
    # birth cue ("born in 1970", "b. 1970"). "1970 or 1971" is a guess.
    for cue in _DOB_KW.finditer(text):
        window = text[cue.end():cue.end() + 20]
        years = re.match(
            r"\s*(?:in\s+)?(\d{4})\b(?:\s*(?:or|/|and)\s*(\d{4})\b)?", window)
        if years is None or years.group(2):
            continue
        start = cue.end() + years.start(1)
        end = cue.end() + years.end(1)
        if overlaps(start, end):
            continue
        parsed = _parse_date(years.group(1))
        if parsed is None or parsed.year is None:
            continue
        found.append((start, end, parsed))
        occupied.append((start, end))
    return found


def _gap(start, end, other_start, other_end):
    if end <= other_start:
        return other_start - end
    if other_end <= start:
        return start - other_end
    return 0


def _nearest(candidates, anchors, limit):
    best = None
    for candidate in candidates:
        distance = min(_gap(candidate[0], candidate[1], anchor[0], anchor[1]) for anchor in anchors)
        after = 0 if candidate[0] >= min(anchor[1] for anchor in anchors) else 1
        key = (distance, after, candidate[0])
        if best is None or key < best[0]:
            best = (key, candidate)
    if best is None or best[0][0] > limit:
        return None
    return best[1]


def _pick_dates(text, found):
    dob = None
    ambiguous = _AMBIGUOUS_BIRTH.search(text) is not None
    keywords = [(match.start(), match.end()) for match in _DOB_KW.finditer(text)]
    if keywords and not ambiguous:
        dob = _nearest(found, keywords, 80)
    if dob is None:
        paren = []
        for match in re.finditer(r"\(([^)]*)\)", text):
            for item in found:
                if match.start() <= item[0] and item[1] <= match.end():
                    paren.append(item)
        if len(paren) == 1:
            dob = paren[0]
    rest = [item for item in found if dob is None or item[0] != dob[0]]
    checks = [(match.start(), match.end()) for match in _CHECK_KW.finditer(text)]
    check = _nearest(rest, checks, 40) if checks and rest else None
    if dob is None and check is not None and not ambiguous:
        others = [item for item in found if item[0] != check[0]]
        if len(others) == 1:
            dob = others[0]
    elif dob is not None and check is None:
        others = [item for item in found if item[0] != dob[0]]
        if len(others) == 1:
            check = others[0]
    return dob, check


def _country_token(token):
    """Skip lowercase words. 2-3 letter tokens only when ALL CAPS ('UK', not 'In')."""
    letters = [ch for ch in token if ch.isalpha()]
    if not letters or token[:1].islower():
        return False
    if len(letters) <= 3 and not all(ch.isupper() for ch in letters):
        return False
    return True


def _span_country(fragment):
    words = _WORD.findall(fragment)
    for size in range(min(4, len(words)), 0, -1):
        for index in range(0, len(words) - size + 1):
            chunk = words[index:index + size]
            if not all(_country_token(word) for word in chunk):
                continue
            name = _normalise_country(" ".join(chunk))
            if name:
                return name
    return None


def _document_country(text):
    found = []

    def add(name):
        if name and name not in found:
            found.append(name)

    for pattern in _CUES:
        for match in pattern.finditer(text):
            fragment = text[match.end():match.end() + 48]
            fragment = re.split(r"[,.;:\n]", fragment, maxsplit=1)[0]
            add(_span_country(fragment))
    for match in _DOC.finditer(text):
        words = _WORD.findall(text[max(0, match.start() - 48):match.start()])
        for word in reversed(words[-3:]):
            head = word.split("-")[0]
            if not _country_token(head):
                continue
            name = _normalise_country(head)
            if name:
                add(name)
                break
        for size in (3, 2, 1):
            if len(words) < size:
                continue
            chunk = words[-size:]
            if not all(_country_token(word) for word in chunk):
                continue
            name = _normalise_country(" ".join(chunk))
            if name:
                add(name)
                break
    for match in re.finditer(r"\(([^)]{2,48})\)", text):
        inner = match.group(1).strip()
        if _parse_date(inner) is not None:
            continue
        # A bracketed caps alias, "(JOHNNY SMITH)", is not a document country.
        real_caps = [tok for tok in _TOKEN.findall(inner)
                     if _is_caps(tok) and not _is_placeholder(_name_token(tok))]
        if len(real_caps) >= 2:
            continue
        add(_span_country(inner))
    for match in re.finditer(
            r"(?i)\b((?:[A-Z][A-Za-zÀ-ÿ'’\-]+\s+){0,3}[A-Z][A-Za-zÀ-ÿ'’\-]+)\s+"
            r"(?:national\b|documentation\b|document\b|citizen\b)", text):
        add(_span_country(match.group(1)) or _normalise_country(match.group(1)))
    return found[0] if found else None


def _countries_in(text):
    tokens = _WORD.findall(text)
    found = []
    seen = []
    occupied = [False] * len(tokens)
    for size in (4, 3, 2, 1):
        if size > len(tokens):
            continue
        for index in range(0, len(tokens) - size + 1):
            if any(occupied[index:index + size]):
                continue
            if not all(_country_token(tokens[index + offset]) for offset in range(size)):
                continue
            name = _normalise_country(" ".join(tokens[index:index + size]))
            if not name:
                continue
            for mark in range(index, index + size):
                occupied[mark] = True
            key = name.casefold()
            if key in seen:
                continue
            seen.append(key)
            found.append(name)
    return found


def _success(text):
    if _flag(_SUCCESS, text):
        return True
    # "A passport ... was checked" is a completed check. "Checked the post" is not.
    return bool(_CHECKED.search(text) and _DOC.search(text) and not _flag(_FAILURE, text))


def _negated_success(text):
    for match in _SUCCESS.finditer(text):
        window = text[max(0, match.start() - 24):match.start()]
        if _NEGATED.search(window):
            return True
    return False


def _parse_kyc(text, created, source):
    # A KYC-channel note is a verification unless it says the check failed.
    failure = _flag(_FAILURE, text)
    if failure:
        return NoteFacts(rejected=True, date=created, source=source)
    if _negated_success(text):
        return NoteFacts(date=created, source=source)
    name = _name(text)
    found = _dates(text)
    dob_item, check_item = _pick_dates(text, found)
    country = _document_country(text)
    dob = dob_item[2] if dob_item is not None else None
    check = check_item[2] if check_item is not None else None
    when = check if check is not None else created
    if name and dob is not None and country:
        return NoteFacts(
            verified=True, name=name, dob=dob, doc_country=country,
            date=when, source=source)
    return NoteFacts(date=when, source=source)


def _parse_residence(text, created, source):
    if not _RESIDENCE.search(text):
        return NoteFacts(date=created, source=source)
    return NoteFacts(lived_in=_countries_in(text), date=created, source=source)
