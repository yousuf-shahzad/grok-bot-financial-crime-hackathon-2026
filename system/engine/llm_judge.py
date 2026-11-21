"""LLM judge: an independent Grok decision for one hit (owner: Thomas's Claude).

    build_case(decision, profile, resolution, alert, data) -> dict   (facts + raw texts + allowed IDs)
    judge(case) -> {decision, reason_code, compared, evidence_ids} or None

It sees the same structured facts as judge.py (every value with its source ID) plus the raw texts
behind them: the hit's profile first paragraph and listed dates of birth, the search snippets the
rules kept, and the customer's KYC rows and support notes. It applies our condensed SOP. Temperature
0 and a strict JSON schema (engine.llm). Any cited ID that was not supplied is dropped; a reason code
that does not belong to the decision makes the whole answer invalid (None). The arbiter decides what
to do with it; this module never changes an output line on its own.
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from . import llm
from .model import BirthClaim, Decision, Fact, PartialDate
from .sop import SOP

DECISIONS = ("DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW")
CODES = {
    "DIFFERENT_ENTITY": ["TEMPORAL_IMPOSSIBILITY", "DOB_MISMATCH", "LOCATION_MISMATCH",
                         "NAME_MISMATCH_VERIFIED", "ENTITY_TYPE_MISMATCH", "DECEASED"],
    "SAME_ENTITY": ["NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH", "NAME_LOCATION_MATCH"],
    "REVIEW": ["INSUFFICIENT_DATA", "AMBIGUOUS_CUSTOMER_RECORD"],
}
ALL_CODES = [c for d in DECISIONS for c in CODES[d]]
MAX_NOTES_PER_PERSON = 8
MAX_TEXT = 1500
ID_RE = re.compile(r"\b[A-Z]{1,5}-[A-Z0-9]{2,}(?:-[A-Z0-9]+)*\b")

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["decision", "reason_code", "compared", "evidence_ids"],
    "properties": {
        "decision": {"type": "string", "enum": list(DECISIONS)},
        "reason_code": {"type": "string", "enum": ALL_CODES},
        "compared": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["field", "customer", "hit", "verdict"],
            "properties": {"field": {"type": "string"}, "customer": {"type": "string"},
                           "hit": {"type": "string"},
                           "verdict": {"type": "string", "enum": ["agree", "contradict", "unknown"]}}}},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
}

PROMPT = (
    "You are a sanctions-screening analyst at a bank. Decide one thing: is this watchlist hit the bank's "
    "customer? Answer with decision DIFFERENT_ENTITY (cleared), SAME_ENTITY (confirmed) or REVIEW (a human "
    "decides; this is the SOP's ESCALATE), and a reason_code that belongs to that decision:\n"
    "DIFFERENT_ENTITY: TEMPORAL_IMPOSSIBILITY, DOB_MISMATCH, LOCATION_MISMATCH, NAME_MISMATCH_VERIFIED, "
    "ENTITY_TYPE_MISMATCH, DECEASED. SAME_ENTITY: NAME_DOB_LOCATION_MATCH, NAME_DOB_MATCH, "
    "NAME_LOCATION_MATCH (companies). REVIEW: INSUFFICIENT_DATA, AMBIGUOUS_CUSTOMER_RECORD (several "
    "customers fit and lead to different decisions).\n"
    "Use ONLY the facts and texts given. Read the raw texts yourself: they may hold facts the structured "
    "fields missed (a verified date of birth in a KYC note, a place the customer lived, an age in the hit's "
    "profile). In 'compared' list each field you compared (name, date of birth, country, type, death, "
    "earliest report) with the customer's and the hit's value and agree / contradict / unknown. "
    "evidence_ids: the IDs, copied exactly, of the records that decide it; never invent one.\n\n"
    "RULES THAT ARE OFTEN MISAPPLIED, follow them exactly:\n"
    "1. LOCATION: if every country tied to the customer differs from every country tied to the hit, the hit "
    "IS cleared (DIFFERENT_ENTITY / LOCATION_MISMATCH). The ONLY exception is when the name AND the date of "
    "birth BOTH agree. If the date of birth is unknown on either side, or does not agree, the exception does "
    "NOT apply and the country difference clears the hit.\n"
    "2. SAME_ENTITY for a person needs the name AND the date of birth to agree (birth year is one of the "
    "hit's possible years and every part both give is equal). Name alone, or name and country, is NOT "
    "enough. For a company: name AND country. Otherwise answer REVIEW.\n"
    "3. UNKNOWN IS NEVER AGREEMENT and never a contradiction: a missing date of birth or country cannot "
    "support SAME_ENTITY, and cannot by itself support DIFFERENT_ENTITY.\n"
    "4. The input 'rules' holds the rules engine's decision and its comparison table ('checks': name, "
    "date_of_birth, country with agree / contradict / unknown / neither, and whether the location exception "
    "applies). Treat that table as correct unless a supplied record shows a fact it missed or got wrong; if "
    "you decide differently from the rules, your evidence_ids MUST include that record.\n"
    "5. DATED REPORT: only a line of the form 'According to <source>; <date>: <text>' is a dated report. "
    "An appointment, election, birth or any other date in the profile is NOT a dated report and can never "
    "support TEMPORAL_IMPOSSIBILITY.\n\n"
    "WORKED EXAMPLES (invented):\n"
    "A. Person. Names agree, both tied to Spain, the hit gives NO date of birth anywhere. Answer: REVIEW / "
    "INSUFFICIENT_DATA. Not SAME_ENTITY: a person needs name AND date of birth to agree, and an unknown date "
    "of birth is not agreement.\n"
    "B. Person. Names agree, dates of birth agree (1971-04-02 and 1971), customer tied only to Ireland, hit "
    "tied only to Brazil. Answer: REVIEW / INSUFFICIENT_DATA. Not DIFFERENT_ENTITY (name and date of birth "
    "agree, so the country difference does not clear) and not SAME_ENTITY (the countries contradict).\n"
    "C. Person. Names agree, customer tied only to France, hit tied only to Kenya, the hit gives no date of "
    "birth. Answer: DIFFERENT_ENTITY / LOCATION_MISMATCH: the exception needs the date of birth to agree, "
    "and it is unknown.\n\nSOP:\n" + SOP)


def _val(v) -> str:
    if isinstance(v, PartialDate):
        if not v.year:
            return "unknown"
        return "-".join(["%04d" % v.year] + (["%02d" % v.month] if v.month else []) +
                        (["%02d" % v.day] if v.month and v.day else []))
    return str(v)


def _fact(f: Optional[Fact]) -> Optional[dict]:
    if f is None:
        return None
    return {"value": _val(f.value), "source": f.source, "kind": f.kind}


def _claim(b: BirthClaim) -> dict:
    return {"years": sorted(set(b.years)), "month": b.month, "day": b.day, "source": b.source}


def _search_by_id(data) -> Dict[str, dict]:
    m = getattr(data, "_llm_judge_sr", None)
    if m is None:
        m = {str(r.get("result_id")): r for rows in getattr(data, "search_by_query", {}).values() for r in rows}
        try:
            setattr(data, "_llm_judge_sr", m)
        except Exception:
            pass
    return m


def _first_paragraph(text: str) -> str:
    for para in re.split(r"\n\s*\n", text or ""):
        if para.strip():
            return para.strip()
    return ""


def _hit_texts(profile, data) -> List[dict]:
    hit = (getattr(data, "hits", None) or {}).get(profile.hit_id) or {}
    out = []
    first = _first_paragraph(str(hit.get("profile_notes") or ""))
    dobs = hit.get("dobs")
    if first or dobs:
        out.append({"id": profile.hit_id, "kind": "hit profile (first paragraph) and listed dates of birth",
                    "text": (("Listed dates of birth: %s\n" % dobs) if dobs else "") + first[:MAX_TEXT * 2]})
    srs = _search_by_id(data)
    for src in sorted({b.source for b in profile.births if str(b.source).startswith("SR-")}):
        if src in srs:
            out.append({"id": src, "kind": "search result kept by the rules",
                        "text": str(srs[src].get("snippet") or "")[:MAX_TEXT]})
    return out


def _customer_texts(person, data) -> List[dict]:
    out, seen = [], set()
    for rid in sorted(person.record_ids):
        cust = (getattr(data, "customers", None) or {}).get(rid) or {}
        # approved identity checks reached through onboarding
        for ob in sorted(getattr(data, "onboarding_by_customer", {}).get(rid, []) or [],
                         key=lambda r: str(r.get("kyc_applicant_id"))):
            for k in getattr(data, "kyc_by_applicant", {}).get(str(ob.get("kyc_applicant_id") or ""), []) or []:
                cid = str(k.get("check_id") or "")
                if not cid or cid in seen:
                    continue
                seen.add(cid)
                fields = {x: k.get(x) for x in ("verified_name", "verified_dob", "document_type",
                                                 "document_country", "result", "checked_at")}
                out.append({"id": cid, "kind": "KYC check", "text": json.dumps(fields, ensure_ascii=False)})
        email = str(cust.get("email") or "").strip().lower()
        notes = [n for n in (getattr(data, "notes_by_email", {}).get(email, []) if email else [])
                 if str(n.get("channel") or "").lower() != "app"]
        for n in sorted(notes, key=lambda n: str(n.get("note_id")))[:MAX_NOTES_PER_PERSON]:
            nid = str(n.get("note_id") or "")
            if nid and nid not in seen:
                seen.add(nid)
                out.append({"id": nid, "kind": "customer note (%s)" % (n.get("channel") or "?"),
                            "text": str(n.get("text") or "")[:MAX_TEXT]})
    return out


def rules_checks(profile, person) -> dict:
    """The rules engine's own comparison for one person, computed with judge.py's matchers, so the LLM
    and the screener see exactly what the rules saw. Verdicts: agree / contradict / unknown / neither."""
    from . import judge  # local import: judge imports nothing from here
    if judge.names is None or judge.dates is None:
        return {}
    cnames, hnames = judge._cust_names(person), [f for f in profile.names if str(f.value or "").strip()]
    nf, hf = judge.name_match(profile, person)
    name = {"customer": [_val(f.value) for f in cnames], "hit": [_val(f.value) for f in hnames],
            "verdict": "agree" if nf is not None else ("unknown" if not cnames or not hnames else "neither"),
            "using": "verified legal name" if person.verified_name is not None else "record names"}
    cdobs, births = judge._cust_dobs(person), judge._hit_births(profile)
    if not cdobs or not births:
        dv = "unknown"
    elif any(judge.dates.birth_agrees(f.value, b) for f in cdobs for b in births):
        dv = "agree"
    elif all(judge.dates.birth_contradicted(f.value, b) for f in cdobs for b in births):
        dv = "contradict"
    else:
        dv = "neither"
    dob = {"customer": [_val(f.value) for f in cdobs], "hit": [_claim(b) for b in births], "verdict": dv,
           "using": "verified date of birth" if person.verified_dob is not None else "declared dates of birth"}
    cc = sorted({_val(f.value).lower() for f in person.countries if str(f.value or "").strip()})
    hc = sorted({_val(f.value).lower() for f in profile.countries if str(f.value or "").strip()})
    country = {"customer": cc, "hit": hc,
               "verdict": "unknown" if not cc or not hc else ("agree" if set(cc) & set(hc) else "contradict")}
    return {"person_id": person.person_id, "name": name, "date_of_birth": dob, "country": country,
            "location_exception_applies": name["verdict"] == "agree" and dv == "agree"}


def build_case(decision: Decision, profile, resolution, alert: dict, data) -> dict:
    people = []
    for p in sorted(resolution.people or [], key=lambda p: p.person_id):
        people.append({
            "person_id": p.person_id, "record_ids": list(p.record_ids), "entity_type": p.entity_type,
            "names": [_fact(f) for f in p.names], "verified_name": _fact(p.verified_name),
            "dobs": [_fact(f) for f in p.dobs], "verified_dob": _fact(p.verified_dob),
            "countries": [_fact(f) for f in p.countries],
            "texts": _customer_texts(p, data) if data is not None else [],
        })
    hit = {
        "hit_id": profile.hit_id, "entity_type": profile.entity_type, "listing_kind": profile.listing_kind,
        "names": [_fact(f) for f in profile.names], "births": [_claim(b) for b in profile.births],
        "countries": [_fact(f) for f in profile.countries], "earliest_report": _fact(profile.earliest_report),
        "deceased": _fact(profile.deceased), "incorporated": _fact(profile.incorporated),
        "missing": list(profile.missing),
        "texts": _hit_texts(profile, data) if data is not None else [],
    }
    screened = {k: alert.get(k) for k in ("customer_name", "entity_type", "dob", "country", "city", "screened_at")}
    rules = {"decision": decision.decision, "reason_code": decision.reason_code, "reason": decision.reason,
             "evidence": list(decision.evidence),
             "checks": [c for c in (rules_checks(profile, p) for p in sorted(resolution.people or [],
                                                                               key=lambda p: p.person_id)) if c]}
    case = {"alert_id": decision.alert_id, "screened": screened, "hit": hit, "customers": people, "rules": rules,
            "note": "several customers fit this alert" if len(people) > 1 else
                    ("no customer record was found" if not people else "")}
    case["allowed_ids"] = sorted(set(ID_RE.findall(json.dumps(case, ensure_ascii=False, sort_keys=True))))
    return case


def judge(case: dict) -> Optional[dict]:
    if not llm.available():
        return None
    payload = {k: v for k, v in case.items() if k != "allowed_ids"}
    got = llm.ask_json(PROMPT, json.dumps(payload, ensure_ascii=False, sort_keys=True), SCHEMA,
                       name="llm_judge", timeout=45.0)
    if not isinstance(got, dict):
        return None
    decision, code = got.get("decision"), got.get("reason_code")
    if decision not in DECISIONS or code not in CODES[decision]:
        return None
    allowed = set(case.get("allowed_ids") or [])
    compared = []
    for c in got.get("compared") or []:
        if isinstance(c, dict) and c.get("verdict") in ("agree", "contradict", "unknown"):
            compared.append({k: str(c.get(k) or "") for k in ("field", "customer", "hit", "verdict")})
    ev = sorted({str(i).strip() for i in got.get("evidence_ids") or [] if str(i).strip() in allowed})
    return {"decision": decision, "reason_code": code, "compared": compared[:12], "evidence_ids": ev}
