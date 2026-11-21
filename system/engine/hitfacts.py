"""Hit row -> HitProfile (SOP principle 5). Module B.

extract(hit, data) -> HitProfile.
hit is a raw hits.jsonl dict. data is load.load(folder) (PLAN 5A):
search_by_query is keyed by the query, already strip().lower().

Fact.source and BirthClaim.source are the record the fact came from:
H-... for the hit row (name, alias, dobs, profile notes, countries, reports,
death, incorporation) and SR-... for a search result. explain.py drops H-
and ACC- from cited evidence; this module does not strip them.

List fields go through load.as_list when load.py imports. No fact here is a
phone number, so digits() is not called.

countries.normalise is used once it maps GB / United Kingdom / British to
one name and International to None (the same check resolve.py uses). Until
module C passes that check, a small fallback matching resolve.py's own
fallback keeps both sides on the same canonical name. dates.parse is used
once it parses 2000-01-02 and day-first 19/05/2004; otherwise a local parser
does those shapes. A missing fact stays missing.
"""
from __future__ import annotations

import re
import unicodedata

from .model import BirthClaim, Fact, HitProfile, PartialDate


_LISTING = {
    "sanctions": "a sanctioned individual",
    "pep": "a politically exposed person",
    "enforcement": "the subject of enforcement action",
    "adverse media": "named in adverse media",
    "soe": "a state-owned enterprise official",
}
_DEFAULT_LISTING = "named on a watchlist"
_NOT_COUNTRIES = {"international", "europe", "global", "worldwide"}
_DEATH_WORDS = {"deceased", "dead", "died"}

# Same small map as resolve.normalise_country's fallback, so a hit country and
# a customer country agree until countries.py passes its self-check.
_FB_COUNTRY = {
    "us": "United States", "usa": "United States", "united states": "United States",
    "american": "United States", "united states of america": "United States",
    "gb": "United Kingdom", "uk": "United Kingdom", "united kingdom": "United Kingdom",
    "british": "United Kingdom", "great britain": "United Kingdom",
    "ng": "Nigeria", "nigeria": "Nigeria", "nigerian": "Nigeria",
    "de": "Germany", "germany": "Germany", "german": "Germany",
    "es": "Spain", "spain": "Spain", "spanish": "Spain",
    "fr": "France", "france": "France", "french": "France",
    "it": "Italy", "italy": "Italy", "italian": "Italy",
    "bd": "Bangladesh", "bangladesh": "Bangladesh", "bangladeshi": "Bangladesh",
    "ie": "Ireland", "ireland": "Ireland", "irish": "Ireland",
    "pl": "Poland", "poland": "Poland", "polish": "Poland",
    "in": "India", "india": "India", "indian": "India",
    "ca": "Canada", "canada": "Canada", "canadian": "Canada",
    "au": "Australia", "australia": "Australia", "australian": "Australia",
    "nl": "Netherlands", "netherlands": "Netherlands", "dutch": "Netherlands",
    "at": "Austria", "austria": "Austria", "austrian": "Austria",
    "ke": "Kenya", "kenya": "Kenya", "kenyan": "Kenya",
}

_MONTHS = {m: i + 1 for i, m in enumerate([
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december"])}
_MONTHS.update({"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
                "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12})

_YEAR_RANGE = re.compile(r"^(\d{4})\s*(?:/|\u2013|\u2014|-|\bor\b)\s*(\d{4})$", re.IGNORECASE)
_REPORT_LINE = re.compile(r"^According to ([^;]+);\s*([^:]+):\s*(\S.*)$")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
# An age has to be tied to an age word. A bare number, or "was 50" with no
# person, is not an age (a fine or a count must not become a birth year).
_AGE_RES = (
    re.compile(r"\baged\s+(\d{2,3})\b", re.I),
    re.compile(r"\bage\s+of\s+(\d{2,3})\b", re.I),
    re.compile(r"\b(?:he|she|they)\s+was\s+(\d{2,3})\b", re.I),
    re.compile(r"\b(\d{2,3})\s*-\s*year\s*-\s*old\b", re.I),
    re.compile(r"\b(\d{2,3})\s+years?\s+old\b", re.I),
    re.compile(r"(?:,|\()\s*(\d{2,3})\s*(?:,|\))"),
)
# "then 45" / "then a 45-year-old" points at the previous sentence's one date.
_THEN_AGE = re.compile(
    r"\bthen\s+(?:a\s+)?(\d{2,3})(?:\s*-\s*year\s*-\s*old|\s+years?\s+old)?\b", re.I)
_BIRTH_RE = re.compile(
    r"(?i)\b(?:was\s+born\s+on|born(?:\s+on|\s+in)?|b\.|date\s+of\s+birth|birth\s+date|d\.?o\.?b\.?)"
    r"\s*[:\-]?\s*([^.;\n]{1,60})",
)
_SENT_DATE = re.compile(
    r"(?i)\b(\d{4}-\d{2}-\d{2}|(?<![\d-])\d{4}-\d{2}(?!-\d)|\d{1,2}/\d{1,2}/\d{4}|"
    r"\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},\s*\d{4}|[A-Za-z]+\s+\d{4})\b")
_DEATH_CUE = re.compile(
    r"(?i)\b(?:died|passed\s+away|deceased)(?:\s+(?:on|in|since))?\s+([^.;\n]{1,48})"
)
_ALIVE_STATUS = {"alive", "living"}


def extract(hit: dict, data) -> HitProfile:
    """Facts for one hit. Does not invent a birth, country or date."""
    row = hit if isinstance(hit, dict) else {}
    hit_id = str(row.get("hit_id") or "")
    alert_id = str(row.get("alert_id") or "")
    entity_type = str(row.get("entity_type") or "").strip()
    company = _is_company(entity_type)
    names = _names(row, hit_id)
    listing = _listing_kind(row)
    countries = _countries(row, hit_id)
    notes = row.get("profile_notes")
    if company:
        births = []
        incorporated = _incorporated(row, hit_id)
    else:
        births = _births(row, data, countries, listing, hit_id)
        incorporated = None
    earliest = _earliest_report(notes, hit_id)
    deceased, death_note = _deceased(row, hit_id, company)
    missing = _missing(names, births, countries, earliest, incorporated, company, death_note)
    return HitProfile(
        hit_id=hit_id, alert_id=alert_id, entity_type=entity_type,
        names=names, births=births, countries=countries,
        earliest_report=earliest, deceased=deceased, incorporated=incorporated,
        listing_kind=listing, missing=missing)


def _is_company(entity_type):
    """Same buckets as judge._etype, so incorporation and births follow the judge."""
    text = str(entity_type or "").strip().lower()
    if text.startswith("indiv") or text == "person":
        return False
    return text.startswith("comp") or text in ("organisation", "organization", "entity")


def _engine(name):
    try:
        return __import__("engine." + name, fromlist=[name])
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if missing == "engine." + name or missing.endswith("." + name):
            return None
        raise


def _as_list(value):
    """PLAN 5A as_list. load.as_list when load.py is importable."""
    mod = _engine("load")
    fn = getattr(mod, "as_list", None) if mod is not None else None
    if fn is not None:
        return fn(value)
    return _as_list_local(value)


def _as_list_local(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def _dates_ready(mod):
    if mod is None or not hasattr(mod, "parse"):
        return False
    try:
        return (mod.parse("2000-01-02") == PartialDate(2000, 1, 2)
                and mod.parse("19/05/2004") == PartialDate(2004, 5, 19))
    except Exception:
        return False


def _parse_date(value):
    if value is None:
        return None
    text = " ".join(str(value).strip().split())
    if not text:
        return None
    mod = _engine("dates")
    if _dates_ready(mod):
        try:
            return mod.parse(text)
        except Exception:
            return None
    return _parse_date_local(text)


def _parse_date_local(text):
    text = text.strip().strip(".")
    match = re.fullmatch(r"(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?(?:[T ].*)?", text)
    if match:
        year, month, day = match.groups()
        return _partial(int(year), int(month) if month else None, int(day) if day else None)
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        return _partial(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    match = re.fullmatch(r"([A-Za-z]+)\.? (\d{1,2}),? (\d{4})", text)
    if match and match.group(1).lower() in _MONTHS:
        return _partial(int(match.group(3)), _MONTHS[match.group(1).lower()], int(match.group(2)))
    match = re.fullmatch(r"(\d{1,2}) ([A-Za-z]+)\.?,? (\d{4})", text)
    if match and match.group(2).lower() in _MONTHS:
        return _partial(int(match.group(3)), _MONTHS[match.group(2).lower()], int(match.group(1)))
    match = re.fullmatch(r"([A-Za-z]+)\.?,? (\d{4})", text)
    if match and match.group(1).lower() in _MONTHS:
        return _partial(int(match.group(2)), _MONTHS[match.group(1).lower()], None)
    return None


def _partial(year, month, day):
    if year is None or not (1000 <= year <= 2100):
        return None
    if month is not None and not (1 <= month <= 12):
        return None
    if day is not None and not (1 <= day <= 31):
        return None
    return PartialDate(year=year, month=month, day=day)


def _before(left, right):
    mod = _engine("dates")
    if mod is not None and hasattr(mod, "before") and _dates_ready(mod):
        try:
            return mod.before(left, right)
        except Exception:
            pass
    if left is None or right is None or left.year is None or right.year is None:
        return None
    if left.year != right.year:
        return left.year < right.year
    if left.month is None or right.month is None:
        return None
    if left.month != right.month:
        return left.month < right.month
    if left.day is None or right.day is None:
        return None
    if left.day != right.day:
        return left.day < right.day
    return False


def _fold(text):
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def _countries_ready(mod):
    if mod is None or not hasattr(mod, "normalise"):
        return False
    try:
        canon = mod.normalise("GB")
        return (canon is not None and canon == mod.normalise("United Kingdom") == mod.normalise("British")
                and mod.normalise("International") is None)
    except Exception:
        return False


def _normalise(value):
    if value is None or not str(value).strip():
        return None
    mod = _engine("countries")
    if _countries_ready(mod):
        try:
            return mod.normalise(str(value))
        except Exception:
            return None
    key = _fold(str(value)).strip().strip(".")
    if key in _NOT_COUNTRIES:
        return None
    return _FB_COUNTRY.get(key, str(value).strip().title())


def _find_date(fragment):
    """Most specific date inside a short fragment, leftmost on a tie."""
    if not fragment:
        return None
    words = [word.strip(" .;:") for word in fragment.replace(",", " ").split()]
    words = [word for word in words if word]
    best = None
    best_score = None
    for length in range(min(6, len(words)), 0, -1):
        for start in range(0, len(words) - length + 1):
            parsed = _parse_date(" ".join(words[start:start + length]))
            if parsed is None or parsed.year is None:
                continue
            score = ((parsed.month is not None) + (parsed.day is not None), length, -start)
            if best_score is None or score > best_score:
                best = parsed
                best_score = score
    return best


def _names(row, hit_id):
    facts = []
    seen = []
    primary = " ".join(str(row.get("name") or "").split()).strip()
    if primary:
        facts.append(Fact(value=primary, source=hit_id, kind="full_name"))
        seen.append(primary.casefold())
    for alias in _as_list(row.get("aliases")):
        alias = " ".join(alias.split()).strip()
        if not alias or alias.casefold() in seen:
            continue
        seen.append(alias.casefold())
        facts.append(Fact(value=alias, source=hit_id, kind="alias"))
    return facts


def _listing_kind(row):
    chosen = _as_list(row.get("primary_category")) or _as_list(row.get("categories"))
    if not chosen:
        return _DEFAULT_LISTING
    key = " ".join(chosen[0].strip().casefold().replace("_", " ").replace("-", " ").split())
    return _LISTING.get(key, _DEFAULT_LISTING)


def _countries(row, hit_id):
    facts = []
    seen = []

    def add_place(raw, kind):
        """A country, or '<city>, <region>, <Country>': whole value, else the last part."""
        name = _normalise(raw)
        if not name:
            last = _last_part(raw)
            if last and last != str(raw).strip():
                name = _normalise(last)
        if not name:
            return
        key = name.casefold()
        if key in seen:
            return
        seen.append(key)
        facts.append(Fact(value=name, source=hit_id, kind=kind))

    for value in _as_list(row.get("countries")):
        add_place(value, "country")
    for value in _as_list(row.get("nationality")):
        add_place(value, "nationality")
    for value in _as_list(row.get("citizenship")):
        add_place(value, "citizenship")
    for address in _as_list(row.get("addresses")):
        add_place(address, "address")
    for place in _as_list(row.get("place_of_birth")):
        add_place(place, "place_of_birth")
    return facts


def _last_part(value):
    parts = [part.strip() for part in str(value).split(",") if part.strip()]
    return parts[-1] if parts else ""


def _births(row, data, countries, listing, hit_id):
    from_dobs = _claims_from_dobs(_as_list(row.get("dobs")), hit_id)
    if from_dobs:
        return from_dobs
    from_notes = _births_from_text(_first_paragraph(row.get("profile_notes")), hit_id)
    if from_notes:
        return from_notes
    return _births_from_search(row, data, countries, listing)


def _claims_from_dobs(tokens, source):
    claims = []
    for token in tokens:
        text = token.strip()
        ranged = _YEAR_RANGE.fullmatch(text)
        if ranged:
            years = tuple(sorted({int(ranged.group(1)), int(ranged.group(2))}))
            claims.append(BirthClaim(years=years, month=None, day=None, source=source))
            continue
        parsed = _parse_date(text)
        if parsed is None or parsed.year is None:
            continue
        claims.append(BirthClaim(years=(parsed.year,), month=parsed.month, day=parsed.day, source=source))
    return _dedupe_claims(claims)


def _births_from_text(text, source):
    if not text:
        return []
    claims = []
    occupied = []

    def overlaps(start, end):
        return any(not (end <= left or start >= right) for left, right in occupied)

    previous_dates = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        dates = _sentence_dates(sentence)
        for match in _age_matches(sentence):
            if overlaps(match[0], match[1]):
                continue
            _add_age(claims, occupied, match, _nearest_date(match[0], match[1], dates), source)
        # "then 45" / "then a 45-year-old". Same sentence if it has a date;
        # otherwise the previous sentence, and only when that sentence has one date.
        for match in _then_ages(sentence):
            if overlaps(match[0], match[1]):
                continue
            if dates:
                when = _nearest_date(match[0], match[1], dates)
            elif len(previous_dates) == 1:
                when = previous_dates[0][2]
            else:
                when = None
            _add_age(claims, occupied, match, when, source)
        previous_dates = dates
    for match in _BIRTH_RE.finditer(text):
        if overlaps(match.start(), match.end()):
            continue
        when = _find_date(match.group(1))
        if when is None or when.year is None:
            continue
        claims.append(BirthClaim(years=(when.year,), month=when.month, day=when.day, source=source))
        occupied.append((match.start(), match.end()))
    return _dedupe_claims(claims)


def _add_age(claims, occupied, match, when, source):
    if when is None or when.year is None or when.month is None:
        return
    years = tuple(sorted((when.year - match[2] - 1, when.year - match[2])))
    if years[0] < 1000:
        return
    # The reference month is not a birth month. SPEC: two possible years.
    claims.append(BirthClaim(years=years, month=None, day=None, source=source))
    occupied.append((match[0], match[1]))


def _then_ages(sentence):
    found = []
    for match in _THEN_AGE.finditer(sentence):
        age = int(match.group(1))
        if 10 <= age <= 130:
            found.append((match.start(), match.end(), age))
    return found


def _age_matches(sentence):
    found = []
    seen = []
    for pattern in _AGE_RES:
        for match in pattern.finditer(sentence):
            age = int(match.group(1))
            if not 10 <= age <= 130:
                continue
            if (match.start(), match.end()) in seen:
                continue
            seen.append((match.start(), match.end()))
            found.append((match.start(), match.end(), age))
    return found


_MONTH_WORD = re.compile(r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\b", re.I)
_BARE_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def _separated_month_year(sentence, occupied):
    """A year and a month name in either order, not already inside one date.

    '2019 notice from March' and 'March bulletin in 2019' are the same anchor
    as 'March 2019': year plus month, no day.
    """
    def taken(start, end):
        return any(not (end <= left or start >= right) for left, right in occupied)

    months = []
    for match in _MONTH_WORD.finditer(sentence):
        word = match.group(1)
        if not word[:1].isupper() or taken(match.start(), match.end()):
            continue
        months.append((match.start(), match.end(), _MONTHS[word.lower()]))
    years = []
    for match in _BARE_YEAR.finditer(sentence):
        if taken(match.start(), match.end()):
            continue
        year = int(match.group(1))
        if 1000 <= year <= 2100:
            years.append((match.start(), match.end(), year))
    used = set()
    found = []
    for start, end, month in months:
        best = None
        best_gap = None
        for index, (year_start, year_end, year) in enumerate(years):
            if index in used:
                continue
            gap = year_start - end if year_start >= end else start - year_end
            if best_gap is None or gap < best_gap:
                best = index
                best_gap = gap
        if best is None:
            continue
        used.add(best)
        year_start, year_end, year = years[best]
        found.append((min(start, year_start), max(end, year_end), PartialDate(year, month, None)))
    return found


def _sentence_dates(sentence):
    found = []
    for match in _SENT_DATE.finditer(sentence):
        parsed = _parse_date(match.group(1))
        if parsed is None or parsed.year is None or parsed.month is None:
            continue
        found.append((match.start(), match.end(), parsed))
    found.extend(_separated_month_year(sentence, [(item[0], item[1]) for item in found]))
    found.sort(key=lambda item: item[0])
    return found


def _nearest_date(start, end, dates):
    best = None
    best_key = None
    for item in dates:
        if item[1] <= start:
            distance = start - item[1]
        elif end <= item[0]:
            distance = item[0] - end
        else:
            distance = 0
        key = (distance, item[0])
        if best_key is None or key < best_key:
            best = item[2]
            best_key = key
    return best


def _births_from_search(row, data, countries, listing):
    """Only when dobs and the first paragraph gave nothing.

    A result counts only if its title or snippet has the listing phrase and a
    country tied to the hit. The birth is read from the snippet. Source is the
    SR- id. No tied country means no result qualifies.
    """
    if not countries:
        return []
    index = _search_index(data)
    rows = _search_rows(index, str(row.get("name") or ""))
    rows.sort(key=lambda item: str(item.get("result_id") or ""))
    country_names = [fact.value for fact in countries if isinstance(fact.value, str)]
    claims = []
    for result in rows:
        title = str(result.get("title") or "")
        snippet = str(result.get("snippet") or "")
        blob = title + "\n" + snippet
        if listing.casefold() not in blob.casefold():
            continue
        if not _mentions_country(blob, country_names):
            continue
        claims.extend(_births_from_text(snippet, str(result.get("result_id") or "")))
    return _dedupe_claims(claims)


def _name_query(name):
    """Lowercase words, sorted, space-joined."""
    return " ".join(sorted(_WORD.findall(name.lower())))


def _folded_query(name):
    """NFKD, drop combining marks, then the same lowercase sorted words.

    load.py keys search_by_query by query.strip().lower(). The file's query
    is already accent-folded, so 'Raković' looks up as 'rakovic'.
    """
    return _name_query(_fold(name))


def _search_rows(index, name):
    if not name or not index:
        return []
    folded = _folded_query(name)
    raw = _name_query(name)
    rows = list(index.get(folded) or [])
    if not rows and raw != folded:
        rows = list(index.get(raw) or [])
    rows = [item for item in rows if isinstance(item, dict)]
    rows.sort(key=lambda item: str(item.get("result_id") or ""))
    return rows


def _search_index(data):
    if data is None:
        return {}
    index = getattr(data, "search_by_query", None)
    if index is None and isinstance(data, dict):
        index = data.get("search_by_query")
    return index or {}


def _country_token(token):
    """A token worth passing to countries.normalise.

    Lowercase words are skipped entirely: 'in' is India, 'and' is Andorra,
    'id' is Indonesia. A 2-3 letter token counts only when it is ALL CAPS
    ('UK', 'ID'), so title-case 'In' at the start of a sentence does not.
    """
    letters = [ch for ch in token if ch.isalpha()]
    if not letters or all(ch.islower() for ch in letters):
        return False
    if len(letters) <= 3 and not all(ch.isupper() for ch in letters):
        return False
    return True


def _mentions_country(text, country_names):
    """True when the text names one of the hit's countries.

    The canonical name is matched as a whole word (so 'India' does not match
    inside 'in'). Other forms ('British', 'United Kingdom') are normalised
    only from capitalised runs.
    """
    if not country_names:
        return False
    folded = text.casefold()
    for name in country_names:
        if len(name) < 4:
            continue
        if re.search(r"\b" + re.escape(name.casefold()) + r"\b", folded):
            return True
    tokens = _WORD.findall(text)[:80]
    wanted = {name.casefold() for name in country_names}
    run = []

    def run_matches(words):
        limit = len(words)
        for size in range(min(4, limit), 0, -1):
            for start in range(0, limit - size + 1):
                norm = _normalise(" ".join(words[start:start + size]))
                if norm and norm.casefold() in wanted:
                    return True
        return False

    for token in tokens:
        if _country_token(token):
            run.append(token)
            continue
        if run and run_matches(run):
            return True
        run = []
    return bool(run) and run_matches(run)


def _first_paragraph(text):
    cleaned = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return ""
    return re.split(r"\n\s*\n", cleaned, maxsplit=1)[0]


def _incorporated(row, hit_id):
    """Companies: dobs only. Earliest date we can prove.

    A year range is not one incorporation date, so it is skipped. When two
    dates cannot be ordered, the earlier bound is kept so 'incorporated after
    the report' does not fire on a date we cannot prove.
    """
    dates = []
    for token in _as_list(row.get("dobs")):
        if _YEAR_RANGE.fullmatch(token.strip()):
            continue
        parsed = _parse_date(token)
        if parsed is not None and parsed.year is not None:
            dates.append(parsed)
    picked = _pick_date(dates, prefer_late=False)
    if picked is None:
        return None
    return Fact(value=picked, source=hit_id, kind="incorporated")


def _earliest_report(text, hit_id):
    dates = []
    cleaned = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    for line in cleaned.split("\n"):
        match = _REPORT_LINE.match(line.strip())
        if not match:
            continue
        parsed = _parse_date(match.group(2).strip())
        if parsed is None or parsed.year is None:
            continue
        dates.append(parsed)
    # Incomparable dates: keep the later bound so a customer is not cleared as
    # under 16 at a report date we cannot prove is the earliest.
    picked = _pick_date(dates, prefer_late=True)
    if picked is None:
        return None
    return Fact(value=picked, source=hit_id, kind="dated_report")


def _pick_date(dates, prefer_late):
    if not dates:
        return None
    keep = []
    for index, candidate in enumerate(dates):
        if any(index != other_i and _before(other, candidate) is True for other_i, other in enumerate(dates)):
            continue
        keep.append(candidate)
    missing = 99 if prefer_late else 0

    def sort_key(item):
        return (item.year or (9999 if prefer_late else 0),
                item.month if item.month is not None else missing,
                item.day if item.day is not None else missing)

    keep.sort(key=sort_key)
    return keep[-1] if prefer_late else keep[0]


def _deceased(row, hit_id, company=False):
    """Death date for HitProfile.deceased. Judge clears only when this PartialDate
    is certainly before screened_at. No date means no DECEASED clear.
    Alive/living beats a death phrase in the prose (it may be someone else).
    Companies are not given a death date from prose: a person mentioned in the
    profile is not the company.
    """
    status = str(row.get("life_status") or "").strip().casefold()
    raw = row.get("deceased_date")
    parsed = _parse_date(raw) if str(raw or "").strip() else None
    if status in _ALIVE_STATUS:
        return None, None
    if parsed is not None and parsed.year is not None:
        return Fact(value=parsed, source=hit_id, kind="deceased"), None
    from_text = None if company else _death_from_text(row.get("profile_notes"))
    if from_text is not None:
        return Fact(value=from_text, source=hit_id, kind="deceased"), None
    if str(raw or "").strip():
        return None, "no usable date of death"
    if status in _DEATH_WORDS or _death_words_without_date(row.get("profile_notes")):
        return None, "deceased but no date of death"
    return None, None


def _death_from_text(text):
    if not text:
        return None
    found = []
    seen = []
    for match in _DEATH_CUE.finditer(str(text)):
        parsed = _find_date(match.group(1))
        if parsed is None or parsed.year is None:
            continue
        key = (parsed.year, parsed.month, parsed.day)
        if key in seen:
            continue
        seen.append(key)
        found.append(parsed)
    if len(found) == 1:
        return found[0]
    return None


def _death_words_without_date(text):
    if not text:
        return False
    return re.search(r"(?i)\b(?:died|passed\s+away|deceased|the\s+late)\b", str(text)) is not None


def _missing(names, births, countries, earliest, incorporated, company, death_note):
    missing = []
    if not names:
        missing.append("no name")
    if company:
        if incorporated is None:
            missing.append("no incorporation date in dobs")
    elif not births:
        missing.append("no date of birth in dobs, notes or search results")
    if not countries:
        missing.append("no country")
    if earliest is None:
        missing.append("no dated report")
    if death_note:
        missing.append(death_note)
    return missing


def _dedupe_claims(claims):
    out = []
    seen = []
    for claim in claims:
        key = (claim.years, claim.month, claim.day, claim.source)
        if key in seen:
            continue
        seen.append(key)
        out.append(claim)
    return out
