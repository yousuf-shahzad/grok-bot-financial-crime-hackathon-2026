"""Cross-examiner: a language model re-reads the free text behind a clearance (owner: Yousuf's Claude).

The rules engine decides every hit. This module only looks at hits the rules CLEAR
(DIFFERENT_ENTITY) and asks the model to read, as a careful clerk, the text our parsers may have
misread or skipped:
  - the resolved customer's notes that our parser could not read (no verification, no lived-in place)
  - for date-based clearances, the hit text the birth date or dated report came from
The model only extracts facts as JSON. Our own code compares those facts with the SOP rule that
cleared the hit, and if any extracted fact would have blocked that rule, the hit becomes REVIEW.

It can never create a clearance or a confirmation, so the worst it can do is send a hit to an
analyst. With no LLM key, or on any model error, every decision is left exactly as the rules made it.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

from . import countries, dates, llm, names
from .model import BirthClaim, Decision, PartialDate

try:
    from . import notes as _notes
except Exception:  # pragma: no cover
    _notes = None

DIFF, REVIEW = "DIFFERENT_ENTITY", "REVIEW"
MAX_NOTES = 8
WORKERS = 8
_RESIDENCE = re.compile(r"\b(liv(e|ed|es|ing)|resid\w*|home|based|settled|relocat\w*|moved|employ\w*|work(ed|ing|s)?|job|position|citizen\w*)\b", re.I)
_IDENTITY = re.compile(r"\b(passport|licen[cs]e|national id|id card|identity|verif\w*|dob|born|birth)\b", re.I)

SYSTEM = (
    "You are a careful clerk in a bank's sanctions screening team. You only EXTRACT facts that are "
    "explicitly stated in the texts you are given. Never guess, never infer from names, never use "
    "outside knowledge. If a fact is not clearly stated, return null or an empty list. Dates must be "
    "written as YYYY-MM-DD, YYYY-MM or YYYY, using only the parts the text gives. When a text gives a "
    "person's age at a dated event (for example '45 in March 2019'), the birth year candidates are the "
    "two possible years (1973 and 1974). Countries must be written as plain English country names."
)

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["notes", "hit_texts"],
    "properties": {
        "notes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "is_successful_identity_check", "verified_name", "date_of_birth",
                         "document_country", "lived_in_countries"],
            "properties": {
                "id": {"type": "string"},
                "is_successful_identity_check": {"type": "boolean"},
                "verified_name": {"type": ["string", "null"]},
                "date_of_birth": {"type": ["string", "null"]},
                "document_country": {"type": ["string", "null"]},
                "lived_in_countries": {"type": "array", "items": {"type": "string"}},
            }}},
        "hit_texts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "about_this_person", "birth_year_candidates", "birth_month", "birth_day",
                         "earliest_dated_report"],
            "properties": {
                "id": {"type": "string"},
                "about_this_person": {"type": "boolean"},
                "birth_year_candidates": {"type": "array", "items": {"type": "integer"}},
                "birth_month": {"type": ["integer", "null"]},
                "birth_day": {"type": ["integer", "null"]},
                "earliest_dated_report": {"type": ["string", "null"]},
            }}},
    },
}


# --------------------------------------------------------------------------------------------
# Gathering the texts worth a second read
# --------------------------------------------------------------------------------------------

def _search_by_id(data) -> Dict[str, dict]:
    m = getattr(data, "_crossexam_sr", None)
    if m is None:
        m = {str(r.get("result_id")): r for rows in data.search_by_query.values() for r in rows}
        try:
            setattr(data, "_crossexam_sr", m)
        except Exception:
            pass
    return m


def _unread_notes(person, data) -> List[dict]:
    out, seen = [], set()
    for rid in person.record_ids:
        email = str((data.customers.get(rid) or {}).get("email") or "").strip().lower()
        for note in data.notes_by_email.get(email, []) if email else []:
            nid = str(note.get("note_id"))
            if nid in seen or str(note.get("channel") or "").lower() == "app":
                continue
            seen.add(nid)
            text = str(note.get("text") or "")
            nf = _notes.parse(note) if _notes is not None else None
            read_ok = nf is not None and (getattr(nf, "verified", False) or getattr(nf, "rejected", False)
                                          or (getattr(nf, "lived_in", None) or []))
            if read_ok:
                continue
            if _RESIDENCE.search(text) or _IDENTITY.search(text):
                out.append({"id": nid, "channel": note.get("channel"), "text": text[:1500]})
    return sorted(out, key=lambda n: n["id"])[:MAX_NOTES]


def _hit_texts(decision: Decision, prof, data) -> List[dict]:
    if decision.reason_code not in ("DOB_MISMATCH", "TEMPORAL_IMPOSSIBILITY"):
        return []
    hit = data.hits.get(prof.hit_id) or {}
    out, srs = [], _search_by_id(data)
    sources = {b.source for b in prof.births}
    if prof.earliest_report is not None:
        sources.add(prof.earliest_report.source)
    for src in sorted(sources):
        if src.startswith("SR-") and src in srs:
            out.append({"id": src, "text": str(srs[src].get("snippet") or "")[:1500]})
        elif src == prof.hit_id:
            notes_txt = str(hit.get("profile_notes") or "")
            dobs = hit.get("dobs")
            out.append({"id": src, "text": ("Listed dates of birth: %s\n\n" % dobs if dobs else "") + notes_txt[:3000]})
    return out


# --------------------------------------------------------------------------------------------
# Comparing what the model read with the rule that cleared the hit
# --------------------------------------------------------------------------------------------

def _pd(s) -> Optional[PartialDate]:
    if not s:
        return None
    try:
        return dates.parse(str(s))
    except Exception:
        return None


def _cust_dobs(person) -> List[PartialDate]:
    facts = [person.verified_dob] if person.verified_dob else list(person.dobs)
    return [f.value for f in facts if f is not None and isinstance(f.value, PartialDate) and f.value.year]


def _blocker(decision: Decision, prof, person, answer: dict) -> Optional[Tuple[str, str]]:
    """(record id, why) for the first extracted fact that would have blocked the clearing rule."""
    code = decision.reason_code
    company = str(prof.entity_type or "").lower().startswith("comp")
    notes_read = [n for n in answer.get("notes", []) if isinstance(n, dict)]
    hit_read = [h for h in answer.get("hit_texts", []) if isinstance(h, dict)]

    if code == "LOCATION_MISMATCH":
        hit_c = {str(f.value).lower() for f in prof.countries}
        for n in notes_read:
            places = list(n.get("lived_in_countries") or [])
            if n.get("is_successful_identity_check") and n.get("document_country"):
                places.append(n["document_country"])
            for place in places:
                c = countries.normalise(str(place))
                if c and c.lower() in hit_c:
                    return n.get("id", ""), "ties the customer to %s, a country tied to the hit" % c

    if code == "NAME_MISMATCH_VERIFIED":
        for n in notes_read:
            vn = n.get("verified_name")
            if n.get("is_successful_identity_check") and vn and names.real_part_count(str(vn), company) >= 2:
                if any(names.names_agree(str(vn), str(h.value), company) for h in prof.names):
                    return n.get("id", ""), "records a verified name, %s, that agrees with the hit's name" % vn

    if code in ("DOB_MISMATCH", "TEMPORAL_IMPOSSIBILITY"):
        cust = _cust_dobs(person)
        for n in notes_read:
            d = _pd(n.get("date_of_birth")) if n.get("is_successful_identity_check") else None
            if d is not None and d.year:
                cust.append(d)
        if code == "DOB_MISMATCH":
            claims = list(prof.births)
            for h in hit_read:
                if not h.get("about_this_person"):
                    continue
                years = tuple(sorted({int(y) for y in h.get("birth_year_candidates") or [] if 1850 < int(y) < 2030}))
                if years:
                    claims.append(BirthClaim(years=years, month=h.get("birth_month"), day=h.get("birth_day"), source=h.get("id", "")))
            for c in cust:
                for b in claims:
                    if not dates.birth_contradicted(c, b):
                        return b.source if b.source.startswith(("SR-", "H-")) else "", \
                            "gives a birth date (%s) that the customer's date of birth does not contradict" % (
                                "/".join(str(y) for y in b.years))
        if code == "TEMPORAL_IMPOSSIBILITY" and not company:
            for h in hit_read:
                rep = _pd(h.get("earliest_dated_report"))
                if rep is not None and rep.year and cust and not all(dates.younger_than(c, rep, 16) for c in cust):
                    return h.get("id", ""), "dates the earliest report to %s, when the customer was not certainly under 16" % h.get("earliest_dated_report")
    return None


def _downgrade(decision: Decision, src: str, why: str) -> Decision:
    reason = ("Our rules would clear this hit (%s), but on a second read %s %s. A wrong clearance is the "
              "costliest mistake, so the hit is left for an analyst to decide." % (
                  decision.reason_code, src or "the record", why))
    ev = sorted(set(list(decision.evidence or []) + ([src] if src and not src.startswith("H-") else [])))
    return Decision(hit_id=decision.hit_id, alert_id=decision.alert_id, decision=REVIEW,
                    reason_code="INSUFFICIENT_DATA", customer_record_id=decision.customer_record_id,
                    reason=reason, evidence=ev)


# --------------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------------

def _examine(item, data) -> Optional[Decision]:
    decision, prof, res, alert = item
    if decision.decision != DIFF or res is None or not res.people:
        return None
    if decision.reason_code in ("ENTITY_TYPE_MISMATCH", "DECEASED"):
        return None  # structured fields only; nothing in free text can undo these
    hit_texts = _hit_texts(decision, prof, data)
    for person in sorted(res.people, key=lambda p: p.person_id):
        note_texts = _unread_notes(person, data)
        if not note_texts and not hit_texts:
            continue
        hit_names = ", ".join(sorted({str(f.value) for f in prof.names}))
        user = json.dumps({
            "task": ("Extract facts from each customer note (about the customer) and each hit text (about the "
                     "listed person named %s). For hit texts, set about_this_person to false if the text is "
                     "about someone else." % hit_names),
            "customer_notes": note_texts, "hit_texts": hit_texts}, ensure_ascii=False, sort_keys=True)
        answer = llm.ask_json(SYSTEM, user, SCHEMA, name="clerk_extraction")
        if not answer:
            continue
        found = _blocker(decision, prof, person, answer)
        if found:
            return _downgrade(decision, found[0], found[1])
    return None


def review_all(items, data, log=None) -> Dict[str, Decision]:
    """items: list of (decision, profile, resolution, alert). Returns {hit_id: new Decision} for downgrades."""
    if not llm.available():
        if log:
            log("crossexam: no LLM key, rules-only decisions kept")
        return {}
    todo = [it for it in items if it[0].decision == DIFF]
    if log:
        log("crossexam: %s, examining %d clearances" % (llm.describe(), len(todo)))
    out: Dict[str, Decision] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for item, res in zip(todo, pool.map(lambda it: _safe(it, data), todo)):
            if res is not None:
                out[item[0].hit_id] = res
    if log:
        log("crossexam: %d clearances sent to review; model calls %s" % (len(out), json.dumps(llm.STATS)))
    return out


def _safe(item, data):
    try:
        return _examine(item, data)
    except Exception:
        return None
