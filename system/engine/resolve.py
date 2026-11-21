"""Customer resolver: alert -> the real customer(s) behind it (SOP principles 2, 3, 4).

    resolve(alert: dict, data: Data) -> Resolution

1. Candidate records: follow the alert's link (account_ref, login_handle, email). A link can
   reach several records (joint accounts); the screened details then pick between them. With no
   link, search the system of record for records that fit every screened detail present.
2. One person, one picture: records sharing a phone AND the same full date of birth, or whose
   approved identity checks carry the same document number, are one person (transitively).
3. Facts per person: names, declared dates of birth and countries from every record; verified
   name, date of birth and document country from the most recent approved check, whether it is a
   KYC provider row or an onboarding note. Rejected and expired checks are never evidence.

Owner: module A (Yousuf's Claude). Uses C's names/dates/countries and B's notes when merged, and
small conservative fallbacks until then. Deterministic: every collection is sorted before use.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .model import Fact, PartialDate, Person, Resolution


# --------------------------------------------------------------------------------------------
# Teammates' modules, with fallbacks so the resolver runs before they are merged.
# --------------------------------------------------------------------------------------------

def _try_import(name):
    try:
        return __import__("engine." + name, fromlist=[name])
    except Exception:  # not merged yet, or a stub that fails to import
        try:
            return __import__(__package__ + "." + name, fromlist=[name])
        except Exception:
            return None


def _works(mod, probe) -> bool:
    """Use a teammate's module only once it answers an obvious case right (stubs return nothing)."""
    if mod is None:
        return False
    try:
        return bool(probe(mod))
    except Exception:
        return False


_names = _try_import("names")
_dates = _try_import("dates")
_countries = _try_import("countries")
_notes = _try_import("notes")

if not _works(_names, lambda m: m.names_agree("John Smith", "Smith, John") and m.names_agree("Mohammed Ali", "Muhammad Ali")
              and not m.names_agree("John Smith", "Peter Jones") and "smith" in m.parts("John Smith")):
    _names = None
if not _works(_dates, lambda m: m.parse("2000-01-02") == PartialDate(2000, 1, 2)
              and m.parse("19/05/2004") == PartialDate(2004, 5, 19)
              and m.same_in_shared_parts(PartialDate(2000, None, None), PartialDate(2000, 1, 2))):
    _dates = None
if not _works(_countries, lambda m: m.normalise("GB") == m.normalise("United Kingdom") == m.normalise("British")
              and m.normalise("GB") is not None and m.normalise("International") is None):
    _countries = None

_PLACEHOLDERS = {"na", "n/a", "test", "unknown", "xxx", "none", "null", "nil"}
_LEGAL_FORMS = {
    "ab", "ag", "as", "asa", "bv", "co", "company", "corp", "corporation", "gmbh", "inc", "kg",
    "limited", "llc", "llp", "lp", "ltd", "na", "nv", "oy", "oyj", "plc", "sa", "sarl", "sas",
    "se", "sf", "sl", "spa", "srl",
}
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"])}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower()


def _fb_parts(name: str, company: bool = False) -> List[str]:
    s = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", _fold(name))
    s = re.sub(r"[^a-z0-9\s]", " ", s.replace("/", ""))
    out: List[str] = []
    for p in s.split():
        if len(p) < 2 or p.isdigit() or p in _PLACEHOLDERS or (company and p in _LEGAL_FORMS):
            continue
        p = re.sub(r"\d+", "", p)
        if len(p) >= 2 and p not in out:
            out.append(p)
    return out


def _lev(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _fb_part_match(a: str, b: str) -> bool:
    if a == b:
        return True
    short = min(len(a), len(b))
    if short < 4:
        return False
    return _lev(a, b) <= (1 if short <= 6 else 2)


def _fb_names_agree(a: str, b: str, company: bool = False) -> bool:
    pa, pb = _fb_parts(a, company), _fb_parts(b, company)
    if not pa or not pb:
        return False
    shorter, longer = (pa, pb) if len(pa) <= len(pb) else (pb, pa)
    matched = [p for p in shorter if any(_fb_part_match(p, q) for q in longer)]
    # joined/split parts: "abdulsalam" vs "abdul salam"
    joined = {x + y for x, y in zip(longer, longer[1:])}
    matched += [p for p in shorter if p not in matched and p in joined]
    return len(matched) >= 2 or (len(matched) == len(shorter) and len(shorter) >= 1)


def name_parts(name: str, company: bool = False) -> List[str]:
    if _names is not None and hasattr(_names, "parts"):
        try:
            return list(_names.parts(name, company=company))
        except Exception:
            pass
    return _fb_parts(name, company)


def names_agree(a: str, b: str, company: bool = False) -> bool:
    if not a or not b:
        return False
    if _names is not None and hasattr(_names, "names_agree"):
        try:
            return bool(_names.names_agree(a, b, company=company))
        except Exception:
            pass
    return _fb_names_agree(a, b, company)


def _fb_parse_date(s) -> Optional[PartialDate]:
    if s is None:
        return None
    t = str(s).strip()
    if not t:
        return None
    m = re.fullmatch(r"(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?(?:[T ].*)?", t)
    if m:
        y, mo, d = m.groups()
        return PartialDate(int(y), int(mo) if mo else None, int(d) if d else None)
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
    if m:  # dev data is always day first
        return PartialDate(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.fullmatch(r"([A-Za-z]+)\.? (\d{1,2}),? (\d{4})", t)
    if m and m.group(1).lower() in _MONTHS:
        return PartialDate(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
    m = re.fullmatch(r"(\d{1,2}) ([A-Za-z]+)\.?,? (\d{4})", t)
    if m and m.group(2).lower() in _MONTHS:
        return PartialDate(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.fullmatch(r"([A-Za-z]+)\.?,? (\d{4})", t)
    if m and m.group(1).lower() in _MONTHS:
        return PartialDate(int(m.group(2)), _MONTHS[m.group(1).lower()], None)
    return None


def parse_date(s) -> Optional[PartialDate]:
    if _dates is not None and hasattr(_dates, "parse"):
        try:
            return _dates.parse(s)
        except Exception:
            pass
    return _fb_parse_date(s)


def _same_in_shared_parts(a: PartialDate, b: PartialDate) -> bool:
    if _dates is not None and hasattr(_dates, "same_in_shared_parts"):
        try:
            return bool(_dates.same_in_shared_parts(a, b))
        except Exception:
            pass
    for x, y in ((a.year, b.year), (a.month, b.month), (a.day, b.day)):
        if x is not None and y is not None and x != y:
            return False
    return True


def _is_full(d: Optional[PartialDate]) -> bool:
    return d is not None and d.year is not None and d.month is not None and d.day is not None


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


def normalise_country(s) -> Optional[str]:
    """Canonical country name, or None when unknown or not a country."""
    if s is None or not str(s).strip():
        return None
    if _countries is not None and hasattr(_countries, "normalise"):
        try:
            return _countries.normalise(str(s))
        except Exception:
            pass
    key = _fold(str(s)).strip().strip(".")
    if key in ("international", "europe", "global", "worldwide"):
        return None
    return _FB_COUNTRY.get(key, str(s).strip().title())


def _parse_note(note: dict):
    """B's notes.parse(note) -> NoteFacts, or None when B is not merged / cannot read it."""
    if _notes is None or not hasattr(_notes, "parse"):
        return None
    try:
        return _notes.parse(note)
    except Exception:
        return None


# --------------------------------------------------------------------------------------------
# Small helpers on the Data contract (PLAN.md section 5A)
# --------------------------------------------------------------------------------------------

def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _low(s) -> str:
    return str(s or "").strip().lower()


def _get(d: dict, key: str):
    v = d.get(key)
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _record_names(rec: dict) -> List[Tuple[str, str]]:
    out = []
    for kind in ("full_name", "preferred_name", "login_name"):
        v = _get(rec, kind)
        if v:
            out.append((kind, str(v)))
    return out


def _cache(data) -> dict:
    c = getattr(data, "_resolve_cache", None)
    if c is None:
        c = {}
        try:
            setattr(data, "_resolve_cache", c)
        except Exception:
            pass
    return c


def _applicant_to_customers(data) -> Dict[str, List[str]]:
    c = _cache(data)
    if "app2cus" not in c:
        m: Dict[str, Set[str]] = {}
        for cid in sorted(data.onboarding_by_customer):
            for row in data.onboarding_by_customer[cid]:
                app = _get(row, "kyc_applicant_id")
                if app:
                    m.setdefault(str(app), set()).add(cid)
        c["app2cus"] = {k: sorted(v) for k, v in m.items()}
    return c["app2cus"]


def _checks_for_record(data, rid: str) -> List[dict]:
    """All KYC check rows (any result) reachable from one customer record via onboarding."""
    out, seen = [], set()
    for row in data.onboarding_by_customer.get(rid, []):
        app = _get(row, "kyc_applicant_id")
        if not app:
            continue
        for chk in data.kyc_by_applicant.get(str(app), []):
            cid = str(chk.get("check_id"))
            if cid not in seen:
                seen.add(cid)
                out.append(chk)
    return sorted(out, key=lambda r: str(r.get("check_id")))


def _approved(chk: dict) -> bool:
    return _low(chk.get("result")) == "approved"


# --------------------------------------------------------------------------------------------
# Fit test: does a customer record fit what was screened? (principle 2)
# --------------------------------------------------------------------------------------------

def _fits(alert: dict, rec: dict, check_name: bool = True) -> bool:
    a_type, r_type = _low(alert.get("entity_type")), _low(rec.get("entity_type"))
    if a_type and r_type and a_type != r_type:
        return False
    company = a_type == "company" or r_type == "company"

    a_dob = parse_date(alert.get("dob"))
    if a_dob is not None:
        r_dob = parse_date(rec.get("dob"))
        if r_dob is not None and not _same_in_shared_parts(a_dob, r_dob):
            return False

    a_country = normalise_country(alert.get("country"))
    if a_country:
        rc = {normalise_country(rec.get("residence_country")), normalise_country(rec.get("nationality"))}
        rc.discard(None)
        if rc and a_country not in rc:
            return False

    a_city = _fold(str(alert.get("city") or "")).strip()
    if a_city:
        hay = " ".join(_fold(str(rec.get(k) or "")) for k in ("city", "address")).strip()
        if hay and a_city not in hay:
            return False

    if check_name:
        screened = _get(alert, "customer_name")
        if screened:
            names = [n for _, n in _record_names(rec)]
            if names and not any(names_agree(screened, n, company) for n in names):
                return False
            if not names:
                return False
    return True


# --------------------------------------------------------------------------------------------
# No-link search: name blocking index over the system of record
# --------------------------------------------------------------------------------------------

def _deletes(p: str) -> List[str]:
    return [p[:i] + p[i + 1:] for i in range(len(p))] if len(p) >= 4 else []


def _name_index(data) -> Dict[str, List[str]]:
    c = _cache(data)
    if "name_index" in c:
        return c["name_index"]
    idx: Dict[str, Set[str]] = {}
    for rid in sorted(data.customers):
        rec = data.customers[rid]
        company = _low(rec.get("entity_type")) == "company"
        for _, n in _record_names(rec):
            parts = name_parts(n, company)
            keys = set()
            for p in parts:
                keys.add("p:" + p)
                for d in _deletes(p):
                    keys.add("d:" + d)
            for x, y in zip(parts, parts[1:]):
                keys.add("p:" + x + y)
            for k in keys:
                idx.setdefault(k, set()).add(rid)
    c["name_index"] = {k: sorted(v) for k, v in idx.items()}
    return c["name_index"]


def _use_file_variants(data) -> None:
    """Once per Data: point C's matcher at name_variants.json when the folder has one."""
    c = _cache(data)
    if c.get("variants_loaded"):
        return
    c["variants_loaded"] = True
    nv = getattr(data, "name_variants", None)
    if nv and _names is not None and hasattr(_names, "use_variants"):
        try:
            _names.use_variants(nv)
        except Exception:
            pass


def _variant_forms(part: str, data) -> List[str]:
    _use_file_variants(data)
    if _names is not None and hasattr(_names, "variant_forms"):
        try:
            return sorted(set(_names.variant_forms(part)) | {part})
        except Exception:
            pass
    forms = {part}
    groups = getattr(_names, "VARIANTS", None) if _names is not None else None
    if not groups and getattr(data, "name_variants", None):
        nv = data.name_variants
        groups = nv.get("groups") or nv.get("given_names") or nv.get("variants") if isinstance(nv, dict) else nv
    for g in groups or []:
        g = list(g) if not isinstance(g, str) else [x.strip() for x in g.split(",")]
        if part in g:
            forms.update(g)
    return sorted(forms)


def _search(alert: dict, data) -> List[str]:
    screened = _get(alert, "customer_name")
    if not screened:
        return []
    company = _low(alert.get("entity_type")) == "company"
    parts = name_parts(str(screened), company)
    if not parts:
        return []
    idx = _name_index(data)
    cand: Set[str] = set()
    for p in parts:
        for f in _variant_forms(p, data):
            cand.update(idx.get("p:" + f, []))
            cand.update(idx.get("d:" + f, []))      # one deletion on the record side
            for d in _deletes(f):
                cand.update(idx.get("p:" + d, []))  # one deletion on the screened side
                cand.update(idx.get("d:" + d, []))  # one substitution
    for x, y in zip(parts, parts[1:]):
        cand.update(idx.get("p:" + x + y, []))
    out = []
    for rid in sorted(cand):
        rec = data.customers.get(rid)
        # cheap checks first, the name last
        if rec is not None and _fits(alert, rec, check_name=False) and _fits(alert, rec, check_name=True):
            out.append(rid)
    return out


# --------------------------------------------------------------------------------------------
# One person, one picture (principle 3)
# --------------------------------------------------------------------------------------------

def _same_person_neighbours(data, rid: str) -> List[str]:
    rec = data.customers.get(rid) or {}
    out: Set[str] = set()
    dob = parse_date(rec.get("dob"))
    ph = _digits(rec.get("phone"))
    if ph and _is_full(dob):
        for other in data.customers_by_phone.get(ph, []):
            if other == rid:
                continue
            odob = parse_date((data.customers.get(other) or {}).get("dob"))
            if _is_full(odob) and (odob.year, odob.month, odob.day) == (dob.year, dob.month, dob.day):
                out.add(other)
    app2cus = _applicant_to_customers(data)
    for chk in _checks_for_record(data, rid):
        if not _approved(chk):
            continue
        num = str(chk.get("document_number") or "").strip().upper()
        if not num:
            continue
        for other_chk in data.kyc_by_docnum.get(num, []):
            for other in app2cus.get(str(other_chk.get("applicant_id")), []):
                if other != rid:
                    out.add(other)
    return sorted(out)


def _expand(data, seeds: Iterable[str]) -> List[List[str]]:
    """Group seed records into people, pulling in every record linked to them."""
    parent: Dict[str, str] = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            if rb < ra:
                ra, rb = rb, ra
            parent[rb] = ra

    queue = sorted(set(seeds))
    for s in queue:
        parent.setdefault(s, s)
    i = 0
    while i < len(queue):
        rid = queue[i]
        i += 1
        for other in _same_person_neighbours(data, rid):
            if other not in parent:
                parent[other] = other
                queue.append(other)
            union(rid, other)
    groups: Dict[str, List[str]] = {}
    for rid in parent:
        groups.setdefault(find(rid), []).append(rid)
    seed_set = set(seeds)
    out = [sorted(g) for g in groups.values() if seed_set.intersection(g)]
    return sorted(out, key=lambda g: g[0])


# --------------------------------------------------------------------------------------------
# Facts per person (principle 4)
# --------------------------------------------------------------------------------------------

def _date_key(d: Optional[PartialDate]) -> Tuple[int, int, int]:
    if d is None:
        return (0, 0, 0)
    return (d.year or 0, d.month or 0, d.day or 0)


def _country_fact(raw, source: str, kind: str) -> Optional[Fact]:
    if raw is None or not str(raw).strip():
        return None
    c = normalise_country(raw)
    if c is None:
        return None
    return Fact(value=c, source=source, kind=kind)


def _build_person(data, record_ids: List[str], path_prefix: List[str]) -> Person:
    recs = [(rid, data.customers.get(rid) or {}) for rid in record_ids]
    etype = next((str(r.get("entity_type")) for _, r in recs if r.get("entity_type")), "")
    names: List[Fact] = []
    dobs: List[Fact] = []
    countries: List[Fact] = []
    path = list(path_prefix)
    verifications = []  # (date_key, source_id, name, dob, doc_country)

    for rid, rec in recs:
        for kind, n in _record_names(rec):
            names.append(Fact(value=n, source=rid, kind=kind))
        d = parse_date(rec.get("dob"))
        if d is not None:
            dobs.append(Fact(value=d, source=rid, kind="dob"))
        for kind, key in (("residence", "residence_country"), ("nationality", "nationality")):
            f = _country_fact(rec.get(key), rid, kind)
            if f:
                countries.append(f)

        for row in data.onboarding_by_customer.get(rid, []):
            for k in ("account_id", "kyc_applicant_id"):
                v = _get(row, k)
                if v and v not in path:
                    path.append(str(v))
        for chk in _checks_for_record(data, rid):
            if not _approved(chk):
                continue  # rejected and expired checks are not evidence
            cid = str(chk.get("check_id"))
            verifications.append((
                _date_key(parse_date(chk.get("checked_at"))), cid,
                _get(chk, "verified_name"), parse_date(chk.get("verified_dob")),
                _get(chk, "document_country")))

        email = _low(rec.get("email"))
        for note in data.notes_by_email.get(email, []) if email else []:
            nf = _parse_note(note)
            if nf is None:
                continue
            nid = str(note.get("note_id"))
            for place in getattr(nf, "lived_in", None) or []:
                f = _country_fact(place, nid, "lived_in")
                if f:
                    countries.append(f)
            if getattr(nf, "verified", False) and not getattr(nf, "rejected", False):
                nd = getattr(nf, "date", None) or parse_date(note.get("created_at"))
                if not isinstance(nd, PartialDate):
                    nd = parse_date(nd)
                dob = getattr(nf, "dob", None)
                if dob is not None and not isinstance(dob, PartialDate):
                    dob = parse_date(dob)
                verifications.append((_date_key(nd), nid, getattr(nf, "name", None), dob,
                                      getattr(nf, "doc_country", None)))

    # most recent approved check first; ties broken by ID so the choice never changes
    verifications.sort(key=lambda v: (v[0], v[1]), reverse=True)
    verified_name = next((Fact(value=str(v[2]), source=v[1], kind="verified_name")
                          for v in verifications if v[2]), None)
    verified_dob = next((Fact(value=v[3], source=v[1], kind="verified_dob")
                         for v in verifications if v[3] is not None), None)
    doc = next(((v[4], v[1]) for v in verifications if v[4]), None)
    if doc:
        f = _country_fact(doc[0], doc[1], "doc_country")
        if f:
            countries.append(f)
    for v in verifications:
        if v[1] not in path:
            path.append(v[1])

    countries = sorted(set(countries), key=lambda f: (str(f.value), f.source, f.kind))
    return Person(
        person_id=record_ids[0], record_ids=list(record_ids), entity_type=etype,
        names=names, verified_name=verified_name, dobs=dobs, verified_dob=verified_dob,
        countries=countries, path=path)


# --------------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------------

def _linked_records(alert: dict, data) -> Tuple[List[str], List[str], bool]:
    """(record_ids, path, has_link)"""
    rids: Set[str] = set()
    path: List[str] = []
    has_link = False
    acc = _get(alert, "account_ref")
    if acc:
        has_link = True
        path.append(str(acc))
        for row in data.accounts_by_id.get(str(acc), []):
            if _get(row, "customer_id"):
                rids.add(str(row["customer_id"]))
    login = _get(alert, "login_handle")
    if login:
        has_link = True
        for row in data.accounts_by_login.get(_low(login), []):
            if _get(row, "customer_id"):
                rids.add(str(row["customer_id"]))
            if _get(row, "account_id") and row["account_id"] not in path:
                path.append(str(row["account_id"]))
    email = _get(alert, "email")
    if email:
        has_link = True
        rids.update(data.customers_by_email.get(_low(email), []))
    return sorted(r for r in rids if r in data.customers), path, has_link


def resolve(alert: dict, data) -> Resolution:
    _use_file_variants(data)
    linked, path, has_link = _linked_records(alert, data)
    if has_link and linked:
        seeds = [r for r in linked if _fits(alert, data.customers[r])] if len(linked) > 1 else linked
        how = "link"
        if not seeds:
            seeds, how = linked, "link (no holder fits the screened details, all kept)"
    elif has_link:
        seeds, how = _search(alert, data), "link leads nowhere, searched by screened details"
    else:
        seeds, how = _search(alert, data), "no link, searched by screened details"

    groups = _expand(data, seeds)
    people = [_build_person(data, g, path) for g in groups]
    people.sort(key=lambda p: p.person_id)
    note = "%s: %d record(s) -> %d person(s)" % (how, len(seeds), len(people))
    return Resolution(people=people, note=note)
