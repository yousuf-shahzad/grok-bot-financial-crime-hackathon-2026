"""LLM court for the human-in-the-loop reviewer (owner: Thomas's Claude). Demo only, never imported
by system/.

    argue(role, case, records, prior=None) -> dict

The rules engine only RECOMMENDS; a human makes every final call. The human ticks the records the
agents may look at, then asks for:
  prosecution  argues the hit IS the customer,
  defence      argues the hit is NOT the customer,
  adjudicator  weighs both against the SOP and suggests CLEAR / CONFIRM / ESCALATE.

Guarantees, enforced here and not left to the model:
- the agents see only the case facts and the records the human ticked;
- every cited ID that was not supplied is dropped before returning;
- the adjudicator cannot suggest CLEAR unless the defence cited supplied evidence, nor CONFIRM
  unless the prosecution did: otherwise its suggestion becomes ESCALATE;
- temperature 0 and a strict JSON schema (engine.llm.ask_json); no key -> {"error": ...}.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Dict, List, Optional

_SYSTEM_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "system")
if _SYSTEM_DIR not in sys.path:
    sys.path.insert(0, _SYSTEM_DIR)

from engine import llm  # noqa: E402

ROLES = ("prosecution", "defence", "adjudicator")
DISPOSITIONS = ("CLEAR", "CONFIRM", "ESCALATE")
CONFIDENCE = ("low", "medium", "high")
MAX_RECORDS = 40
MAX_RECORD_CHARS = 2000
ID_RE = re.compile(r"\b[A-Z]{1,5}-[A-Z0-9]{2,}(?:-[A-Z0-9]+)*\b")

# Our condensed reading of the bank's identity SOP (SPEC.md sections 3 to 5), in our own words.
SOP = """Identity only: is this watchlist hit the bank's customer? Never judge how serious the listing is.
Wrongly clearing a real match is by far the worst error, so when in doubt the answer is ESCALATE.
CLEAR (different entity) only on a contradiction the SOP names:
- type: one is a person, the other a company;
- death: the profile gives a date of death before the customer was screened;
- time: the customer was under 16 (or the company not yet incorporated) at the earliest dated report;
- date of birth: EVERY birth date the hit gives is contradicted (customer year more than 1 year outside it,
  or same year with a different month or day); one agreeing date blocks this;
- name: the customer's VERIFIED legal name agrees with none of the hit's names or aliases;
- location: every country tied to the customer (residence, nationality, verified document country, places
  notes say they lived) differs from every country tied to the hit; BUT if name and date of birth agree,
  a country difference does not clear.
CONFIRM (same entity) only on agreement with nothing contradicting: a person needs name AND date of birth
to agree (birth year is one of the hit's possible years and every part both give is equal); a company needs
name AND country to agree.
Names agree when at least two name parts match, or every part of the shorter name matches; parts match if
identical, known variants, joined/split, or 1 edit (4-6 letters) / 2 edits (7+). Initials and placeholders
are not parts; a person with fewer than 2 real name parts can be neither confirmed nor cleared on name.
Unknown stays unknown: a missing field or a missing part of a date is never a mismatch.
Verified beats declared: an approved identity check outranks what the customer typed; rejected or expired
checks are not evidence."""

_POINTS = {
    "type": "array",
    "items": {
        "type": "object", "additionalProperties": False, "required": ["claim", "evidence_ids"],
        "properties": {"claim": {"type": "string"},
                       "evidence_ids": {"type": "array", "items": {"type": "string"}}},
    },
}
ADVOCATE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["position", "points", "gaps"],
    "properties": {"position": {"type": "string"}, "points": _POINTS,
                   "gaps": {"type": "array", "items": {"type": "string"}}},
}
ADJUDICATOR_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["position", "points", "gaps", "summary", "suggested_disposition", "confidence",
                 "what_would_settle", "sop_rule"],
    "properties": {
        "position": {"type": "string"}, "points": _POINTS,
        "gaps": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "suggested_disposition": {"type": "string", "enum": list(DISPOSITIONS)},
        "confidence": {"type": "string", "enum": list(CONFIDENCE)},
        "what_would_settle": {"type": "array", "items": {"type": "string"}},
        "sop_rule": {"type": "string"},
    },
}

_COMMON = (
    "You are part of a review panel at a bank. The panel decides one thing: is a watchlist hit the bank's "
    "customer? You see ONLY the case facts and the records a human analyst selected. Use nothing else: no "
    "outside knowledge about real people, no guesses. Every point must cite the IDs of the supplied records "
    "or case facts it rests on, copied exactly; never invent an ID or a fact. If something needed is not in "
    "the material, say so in gaps. Follow the bank's SOP below exactly.\n\nSOP:\n" + SOP + "\n\n"
)
PROMPTS = {
    "prosecution": _COMMON + (
        "Your role: PROSECUTION. Make the strongest honest case that the hit IS the customer: names, dates of "
        "birth and countries that agree, using verified facts first. Do not hide weaknesses: list in gaps what "
        "is unknown or what would undercut your case. position = one sentence."),
    "defence": _COMMON + (
        "Your role: DEFENCE. Make the strongest honest case that the hit is NOT the customer, using only the "
        "contradictions the SOP names (type, death, time, every date of birth contradicted, verified name, "
        "every country different). A missing fact is not a contradiction: list it in gaps instead. "
        "position = one sentence."),
    "adjudicator": _COMMON + (
        "Your role: ADJUDICATOR. Weigh the prosecution and the defence (given as 'prior') against the SOP. "
        "Suggest CLEAR only if a contradiction the SOP names is supported by cited evidence; CONFIRM only if "
        "the SOP's agreement test is met with nothing contradicting; otherwise ESCALATE. Be neutral. "
        "position = one sentence; summary = 3 to 5 sentences; sop_rule = the SOP rule your suggestion rests "
        "on; what_would_settle = the specific facts that would decide it; confidence = low, medium or high. "
        "The human analyst makes the final decision; you only advise."),
}


def _error(msg: str) -> dict:
    return {"error": msg}


def _ids_in(obj) -> set:
    """Every ID-shaped string anywhere in the case facts (record IDs, sources, evidence)."""
    return set(ID_RE.findall(json.dumps(obj, ensure_ascii=False, sort_keys=True)))


def _clean_records(records) -> List[dict]:
    out = []
    for r in records or []:
        if not isinstance(r, dict) or not str(r.get("id") or "").strip():
            continue
        out.append({"id": str(r["id"]).strip(), "kind": str(r.get("kind") or ""),
                    "text": str(r.get("text") or "")[:MAX_RECORD_CHARS]})
    out.sort(key=lambda r: r["id"])
    seen, uniq = set(), []
    for r in out:
        if r["id"] not in seen:
            seen.add(r["id"])
            uniq.append(r)
    return uniq[:MAX_RECORDS]


def _strs(v, limit: int = 12) -> List[str]:
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()][:limit]


def _points(v, allowed: set) -> List[dict]:
    out = []
    for p in v if isinstance(v, list) else []:
        if not isinstance(p, dict) or not str(p.get("claim") or "").strip():
            continue
        ids = sorted({str(i).strip() for i in p.get("evidence_ids") or [] if str(i).strip() in allowed})
        out.append({"claim": str(p["claim"]).strip(), "evidence_ids": ids})
    return out[:12]


def _cited(side: Optional[dict]) -> bool:
    return bool(side) and any(p.get("evidence_ids") for p in side.get("points") or [])


def argue(role: str, case: dict, records: list, prior: Optional[dict] = None) -> dict:
    if role not in ROLES:
        return _error("role must be one of %s" % ", ".join(ROLES))
    if not isinstance(case, dict) or not isinstance(case.get("hit"), dict):
        return _error("case must include the hit")
    if role == "adjudicator" and not (isinstance(prior, dict) and prior.get("prosecution") and prior.get("defence")):
        return _error("the adjudicator needs prior = {prosecution, defence} from this panel")
    if not llm.available():
        return _error("no LLM key configured")

    recs = _clean_records(records)
    allowed = _ids_in(case) | {r["id"] for r in recs}
    payload = {"case": {k: case.get(k) for k in ("hit", "customer", "rules")}, "records": recs}
    if role == "adjudicator":
        # only the advocates' sanitised output goes to the adjudicator
        payload["prior"] = {side: {"position": str(prior[side].get("position") or ""),
                                   "points": _points(prior[side].get("points"), allowed),
                                   "gaps": _strs(prior[side].get("gaps"))}
                            for side in ("prosecution", "defence")}
    user = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    schema = ADJUDICATOR_SCHEMA if role == "adjudicator" else ADVOCATE_SCHEMA
    got = llm.ask_json(PROMPTS[role], user, schema, name="court_" + role, timeout=60.0)
    if not isinstance(got, dict):
        return _error("model call failed")

    out = {"role": role, "position": str(got.get("position") or "").strip(),
           "points": _points(got.get("points"), allowed), "gaps": _strs(got.get("gaps"))}
    if role == "adjudicator":
        disp = str(got.get("suggested_disposition") or "").upper()
        disp = disp if disp in DISPOSITIONS else "ESCALATE"
        conf = str(got.get("confidence") or "").lower()
        conf = conf if conf in CONFIDENCE else "low"
        settle = _strs(got.get("what_would_settle"))
        sides = payload["prior"]
        # the asymmetric cost: never let the panel clear or confirm on uncited argument
        if disp == "CLEAR" and not _cited(sides["defence"]):
            disp, conf = "ESCALATE", "low"
            settle = settle + ["The defence cited no supplied record for a contradiction, so clearing is not supported."]
        if disp == "CONFIRM" and not _cited(sides["prosecution"]):
            disp, conf = "ESCALATE", "low"
            settle = settle + ["The prosecution cited no supplied record for the agreement, so confirming is not supported."]
        out.update({"summary": str(got.get("summary") or "").strip(), "suggested_disposition": disp,
                    "confidence": conf, "what_would_settle": settle,
                    "sop_rule": str(got.get("sop_rule") or "").strip()})
    out["model"] = llm.describe()
    return out
