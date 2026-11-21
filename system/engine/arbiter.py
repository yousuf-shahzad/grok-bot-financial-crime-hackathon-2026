"""Dual decision path: rules engine vs an independent Grok judge, with a screening agent (owner:
Thomas's Claude).

    review_all(items, data, log=None) -> {hit_id: Decision}   (only the lines that change)
    trace(hit_id) -> {deterministic, llm, screener, final, path} or None   (for demo/app.py)

For every hit the LLM judge (llm_judge.py) decides independently.
- Same decision as the rules: the rules' line is kept unchanged.
- Different: a screening agent sees both answers, the facts and the raw texts, and says where the
  error is. Resolution (lead's rules, with a HARD SAFETY RULE: the LLM can never create a clearance):
    error in the LLM            -> keep the rules' decision
    error in the rules          -> take the LLM decision only if SAME_ENTITY or REVIEW;
                                   if the LLM said DIFFERENT_ENTITY -> REVIEW / INSUFFICIENT_DATA
    neither, both, or a failure -> REVIEW / INSUFFICIENT_DATA
  So a final DIFFERENT_ENTITY only ever comes from the rules engine.
- The LLM judge failing (no answer, invalid answer) is not a disagreement: the rules' line stands.
No key (or LLM_DISABLE=1): returns {} at once, so the output is byte-identical to rules only.
"""
from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Dict, List, Optional

from . import llm, llm_judge
from .model import Decision
from .sop import SOP

# A reason code has to belong to the decision we actually return. If the model
# names a code from the other view, fall back to one that fits.
_DEFAULT_CODE = {
    "SAME_ENTITY": "NAME_DOB_MATCH",
    "REVIEW": "INSUFFICIENT_DATA",
}

WORKERS = 8
DIFF, SAME, REVIEW = "DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW"
NO_CITE = ("H-", "ACC-")
_TRACE: Dict[str, dict] = {}
_LOCK = threading.Lock()
STATS: Dict[str, int] = {}

SCREEN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["error_in", "significant_missed_facts", "explanation"],
    "properties": {
        "error_in": {"type": "string", "enum": ["deterministic", "llm", "neither", "both"]},
        "significant_missed_facts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["fact", "evidence_ids"],
            "properties": {"fact": {"type": "string"},
                           "evidence_ids": {"type": "array", "items": {"type": "string"}}}}},
        "explanation": {"type": "string"},
    },
}
SCREEN_PROMPT = (
    "You are the senior screening analyst at a bank. Two reviewers decided whether a watchlist hit is the "
    "bank's customer and they disagree: 'deterministic' (a rules engine applying the SOP to parsed fields) "
    "and 'llm' (a language model that also read the raw texts). Using ONLY the facts and texts given and "
    "the SOP below, say where the error is: 'deterministic', 'llm', 'neither' (both are defensible: the "
    "evidence does not settle it) or 'both'. List significant facts a reviewer missed, each with the IDs "
    "of the records that show it, copied exactly; never invent an ID or a fact. explanation: at most two "
    "short sentences.\n\n"
    "The input 'rules' is case['rules']: the rules engine's decision plus a per-person comparison table "
    "('checks': name, date_of_birth, country with agree / contradict / unknown / neither, and "
    "location_exception_applies). You may answer 'deterministic', 'neither' or 'both' ONLY if a supplied "
    "record shows a fact that table missed or got wrong, and you MUST list that record's ID in "
    "significant_missed_facts; otherwise answer 'llm'.\n"
    "RULES THE LLM REVIEWER OFTEN MISAPPLIES, follow them exactly:\n"
    "1. LOCATION: if every country tied to the customer differs from every country tied to the hit, the hit "
    "IS cleared (DIFFERENT_ENTITY / LOCATION_MISMATCH). The ONLY exception is when the name AND the date of "
    "birth BOTH agree. If the date of birth is unknown on either side, or does not agree, the exception does "
    "NOT apply and the country difference clears the hit.\n"
    "2. SAME_ENTITY for a person needs the name AND the date of birth to agree (birth year is one of the "
    "hit's possible years and every part both give is equal). Name alone, or name and country, is NOT "
    "enough. For a company: name AND country. Otherwise the answer is REVIEW.\n"
    "3. UNKNOWN IS NEVER AGREEMENT and never a contradiction: a missing date of birth or country cannot "
    "support SAME_ENTITY, and cannot by itself support DIFFERENT_ENTITY.\n"
    "4. The 'rules' table stands unless a cited supplied record disproves it. To say the error is in the "
    "rules you must list that record's ID in significant_missed_facts.\n\nSOP:\n" + SOP)


def _bump(key: str) -> None:
    with _LOCK:
        STATS[key] = STATS.get(key, 0) + 1


def trace(hit_id: str) -> Optional[dict]:
    with _LOCK:
        t = _TRACE.get(str(hit_id))
        return json.loads(json.dumps(t)) if t is not None else None


def _human(decision: str) -> str:
    return {DIFF: "different entity", SAME: "same entity", REVIEW: "review"}.get(decision, decision.lower())


# Same shape as the IDs in the files: NOTE-T9, KYC-1, CUS-T1, H-292F2E, ACC-100.
_ID_LIKE = re.compile(r"\b[A-Za-z]{1,5}-[A-Za-z0-9]{2,}(?:-[A-Za-z0-9]+)*\b")


def _clean(s: str, limit: int = 220) -> str:
    s = re.sub(r"[.!?;:]+", ",", str(s or "")).strip(" ,")
    s = re.sub(r"\s+", " ", s)
    return s[:limit].rstrip(" ,")


def _scrub_explanation(text: str, allowed) -> str:
    """Take the screener's explanation down to one sentence with only case IDs in it.

    H- and ACC- ids are never cited. Any other id-like token that is not in the case's
    allowed_ids is replaced with 'a record'. One sentence, so the reason stays at 2 to 4.
    """
    allow = {str(i).upper() for i in (allowed or [])}

    def repl(match):
        key = match.group(0).upper()
        if key.startswith("H-") or key.startswith("ACC-") or key not in allow:
            return "a record"
        return key

    cleaned = _ID_LIKE.sub(repl, str(text or ""))
    cleaned = re.sub(r"(?:\ba record\b\s*){2,}", "a record ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return _first_sentence(cleaned) or cleaned


def _cap_reason(text: str) -> str:
    """A changed line's reason is 2 to 4 sentences. The templates already supply at least two."""
    parts = [p.strip() for p in re.findall(r"[^.!?]*[.!?]", text.strip()) if p.strip()]
    if len(parts) > 4:
        parts = parts[:4]
    return " ".join(parts).strip() if parts else text.strip()


def _first_sentence(text: str) -> str:
    m = re.match(r"^(.*?[.!?])(?=\s|$)", (text or "").strip())
    return m.group(1) if m else ""


def _screen(case: dict, det: Decision, view: dict) -> Optional[dict]:
    payload = {k: v for k, v in case.items() if k != "allowed_ids"}
    payload["deterministic"] = {"decision": det.decision, "reason_code": det.reason_code,
                                "reason": det.reason, "evidence": list(det.evidence)}
    payload["llm"] = view
    got = llm.ask_json(SCREEN_PROMPT, json.dumps(payload, ensure_ascii=False, sort_keys=True), SCREEN_SCHEMA,
                       name="screening_agent", timeout=45.0)
    if not isinstance(got, dict) or got.get("error_in") not in ("deterministic", "llm", "neither", "both"):
        return None
    allowed = set(case.get("allowed_ids") or [])
    missed = []
    for m in got.get("significant_missed_facts") or []:
        if isinstance(m, dict) and str(m.get("fact") or "").strip():
            missed.append({"fact": str(m["fact"]).strip(),
                           "evidence_ids": sorted({str(i) for i in m.get("evidence_ids") or [] if str(i) in allowed})})
    return {"error_in": got["error_in"], "significant_missed_facts": missed[:8],
            "explanation": _scrub_explanation(got.get("explanation") or "", allowed)}


def _cite(ids) -> List[str]:
    """Evidence that may be shown: real IDs only, never an H- or ACC- id."""
    out = []
    seen = set()
    for raw in ids or []:
        item = str(raw or "").strip()
        if not item or item.startswith(NO_CITE) or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return sorted(out)


def _code_for(decision: str, code: str, det: Decision) -> str:
    allowed = llm_judge.CODES.get(decision) or []
    if code in allowed:
        return code
    if decision == det.decision and det.reason_code in allowed:
        return det.reason_code
    return _DEFAULT_CODE.get(decision, "INSUFFICIENT_DATA")


def _guard(final: Decision, det: Decision) -> Decision:
    """Last line: a clearance can only be the rules' own clearance, with a legal code."""
    if final is det:
        return det
    if final.decision == DIFF and det.decision != DIFF:
        final = replace(final, decision=REVIEW, reason_code="INSUFFICIENT_DATA")
    code = _code_for(final.decision, final.reason_code, det)
    evidence = _cite(final.evidence)
    if final.decision == DIFF:
        code = det.reason_code
    if code != final.reason_code or evidence != list(final.evidence or []):
        final = replace(final, reason_code=code, evidence=evidence)
    return final


def _missed_ids(screen) -> List[str]:
    out = []
    for fact in (screen or {}).get("significant_missed_facts") or []:
        if isinstance(fact, dict):
            out.extend(fact.get("evidence_ids") or [])
    return out


def _has_new_citation(missed, allowed_ids, evidence) -> bool:
    """True when this call is not applying the citation gate, or a new supplied id is cited.

    A supplied allow-list makes 'deterministic' count only for an id that is on that list,
    is not an H- or ACC- id, and is not already among the rules' evidence.
    """
    if allowed_ids is None:
        return True
    allowed = {str(i) for i in allowed_ids}
    already = {str(i) for i in (evidence or [])}
    for raw in missed or []:
        item = str(raw or "").strip()
        if not item or item.startswith(NO_CITE) or item in already or item not in allowed:
            continue
        return True
    return False


def _parse_partial(value):
    from .model import PartialDate
    if isinstance(value, PartialDate):
        return value
    text = str(value or "")
    match = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", text)
    if not match:
        return None
    year, month, day = match.groups()
    return PartialDate(int(year), int(month) if month else None, int(day) if day else None)


def _as_fact(raw):
    from .model import Fact
    if not isinstance(raw, dict) or raw.get("value") in (None, ""):
        return None
    value = raw.get("value")
    parsed = _parse_partial(value)
    if parsed is not None:
        value = parsed
    return Fact(value=value, source=str(raw.get("source") or ""), kind=str(raw.get("kind") or ""))


def _same_supported(case) -> bool:
    """True when the matchers, not the model, support SAME_ENTITY.

    A person needs judge.name_match and dates.birth_agrees. A verified name with fewer
    than two real parts cannot confirm. A company needs that name match and a shared country.
    """
    if not isinstance(case, dict):
        return False
    hit = case.get("hit") if isinstance(case.get("hit"), dict) else {}
    customers = case.get("customers") if isinstance(case.get("customers"), list) else []
    if not hit or not customers:
        return False
    from . import judge
    from .model import BirthClaim, HitProfile, Person
    births = []
    for raw in hit.get("births") or []:
        if isinstance(raw, dict) and raw.get("years"):
            births.append(BirthClaim(years=tuple(int(y) for y in raw["years"]),
                                     month=raw.get("month"), day=raw.get("day"),
                                     source=str(raw.get("source") or "")))
    profile = HitProfile(
        hit_id=str(hit.get("hit_id") or ""), alert_id=str(case.get("alert_id") or ""),
        entity_type=str(hit.get("entity_type") or ""),
        names=[f for f in (_as_fact(n) for n in hit.get("names") or []) if f],
        births=births,
        countries=[f for f in (_as_fact(c) for c in hit.get("countries") or []) if f],
        incorporated=_as_fact(hit.get("incorporated")))
    for raw in customers:
        if not isinstance(raw, dict):
            continue
        person = Person(
            person_id=str(raw.get("person_id") or ""), record_ids=list(raw.get("record_ids") or []),
            entity_type=str(raw.get("entity_type") or ""),
            names=[f for f in (_as_fact(n) for n in raw.get("names") or []) if f],
            verified_name=_as_fact(raw.get("verified_name")),
            dobs=[f for f in (_as_fact(n) for n in raw.get("dobs") or []) if f],
            verified_dob=_as_fact(raw.get("verified_dob")),
            countries=[f for f in (_as_fact(c) for c in raw.get("countries") or []) if f])
        company = judge._is_company(profile.entity_type) or judge._is_company(person.entity_type)
        if company and not judge._is_company(profile.entity_type):
            profile = replace(profile, entity_type=person.entity_type)
        matched, _hit_name = judge.name_match(profile, person)
        if matched is None:
            continue
        verified = person.verified_name
        if verified is not None and judge.names and judge.names.real_part_count(str(verified.value), company) < 2:
            continue
        if company:
            cust = {str(f.value).strip().lower() for f in person.countries if str(f.value or "").strip()}
            listed = {str(f.value).strip().lower() for f in profile.countries if str(f.value or "").strip()}
            if cust and listed and cust & listed:
                return True
            continue
        if judge.dates is None:
            continue
        if any(judge.dates.birth_agrees(f.value, claim) for f in judge._cust_dobs(person)
               for claim in judge._hit_births(profile)):
            return True
    return False


def _guard_label(screen, allowed_ids, det, view, case, path):
    """Why a deterministic blame was kept as the rules' line, if it was."""
    if path != "error_in_llm_keep_rules" or not isinstance(screen, dict):
        return None
    if screen.get("error_in") != "deterministic":
        return None
    if allowed_ids is not None and not _has_new_citation(_missed_ids(screen), allowed_ids, det.evidence):
        return "no_new_cited_record"
    if (isinstance(view, dict) and view.get("decision") == SAME and det.decision != SAME
            and case is not None and not _same_supported(case)):
        return "same_without_name_and_dob"
    return None


def resolve_one(det: Decision, view: Optional[dict], screen: Optional[dict], screen_failed: bool = False,
                allowed_ids=None, case=None) -> tuple:
    """Pure resolution: (final Decision, path). Unit-tested; holds the safety rule."""
    # an LLM answer the judge would have rejected (unknown decision, missing or foreign reason code) is
    # "no second view", exactly as llm_judge.judge() treats it: the rules' line stands
    if (not isinstance(view, dict) or view.get("decision") not in (DIFF, SAME, REVIEW)
            or view.get("reason_code") not in llm_judge.CODES.get(view.get("decision"), [])):
        return det, "llm_unavailable"
    if view["decision"] == det.decision:
        return det, "agree"
    if screen_failed:
        screen = None
    who = {"deterministic": "the rules engine", "llm": "the Grok review", "neither": "neither view",
           "both": "both views"}
    s1 = ("The rules engine decided %s (%s), but an independent Grok review decided %s (%s)."
          % (_human(det.decision), det.reason_code, _human(view["decision"]), view["reason_code"]))
    error_in = screen.get("error_in") if isinstance(screen, dict) else None
    missed = _missed_ids(screen)
    # 'deterministic' counts only with a supplied id the rules did not already cite.
    # Otherwise this is the same as the screener saying the error is in the LLM: keep the rules.
    if error_in == "deterministic" and not _has_new_citation(missed, allowed_ids, det.evidence):
        error_in = "llm"
    if (error_in == "deterministic" and view["decision"] == SAME and det.decision != SAME
            and case is not None and not _same_supported(case)):
        error_in = "llm"
    if error_in not in who:
        s2 = "A screening agent could not settle the disagreement."
        error_in = None
    else:
        expl = _clean(_scrub_explanation(screen.get("explanation") or "", allowed_ids))
        s2 = "A screening agent compared both and found the error in %s%s." % (
            who[error_in], (": " + expl) if expl else "")
    # The line's evidence is the rules' IDs plus IDs the screener says were missed.
    # The model's own evidence list is not copied: it can name records that are not in the case.
    evidence = _cite(list(det.evidence or []) + list(missed))

    # Lead's rule: the screener may only side against the rules (or call it unsettled) by citing a
    # supplied record that disproves the rules' comparison. Without one, the rules' line stands.
    uncited = error_in in ("deterministic", "neither", "both") and not _cite(missed)
    if uncited:
        s2 = ("A screening agent questioned the rules engine but cited no supplied record that disproves "
              "its comparison.")
        s4 = _first_sentence(det.reason)
        reason = _cap_reason(" ".join(x for x in (s1, s2, "The rules engine's decision stands.", s4) if x))
        final, path = replace(det, reason=reason), "uncited_keep_rules"
    elif error_in == "llm":
        s4 = _first_sentence(det.reason)
        reason = _cap_reason(" ".join(x for x in (s1, s2, "The rules engine's decision stands.", s4) if x))
        final, path = replace(det, reason=reason, evidence=evidence), "error_in_llm_keep_rules"
    elif error_in == "deterministic" and view["decision"] in (SAME, REVIEW):
        reason = _cap_reason(" ".join((s1, s2, "The Grok review's decision is taken.")))
        final, path = replace(det, decision=view["decision"], reason_code=_code_for(view["decision"], view.get("reason_code"), det),
                              reason=reason, evidence=evidence), "error_in_rules_take_llm"
    elif error_in == "deterministic":  # the LLM wants a clearance the rules did not make
        reason = _cap_reason(" ".join((s1, s2, "A clearance can only come from the rules engine, so an analyst decides.")))
        final, path = replace(det, decision=REVIEW, reason_code="INSUFFICIENT_DATA", reason=reason,
                              evidence=evidence), "error_in_rules_llm_clear_blocked"
    else:
        reason = _cap_reason(" ".join((s1, s2, "An analyst decides.")))
        # An unrecognised error_in is a screener failure, same as a missing screen.
        label = "screen_failed" if error_in not in who else "error_in_%s_review" % error_in
        final, path = replace(det, decision=REVIEW, reason_code="INSUFFICIENT_DATA", reason=reason,
                              evidence=evidence), label
    return _guard(final, det), path


def _limit(final: Decision, det: Decision, case: dict) -> Decision:
    """Drop any cited ID the case did not supply. Shared by resolve and review_all."""
    if final is det or not isinstance(case, dict) or "allowed_ids" not in case:
        return final
    allowed = {str(i) for i in (case.get("allowed_ids") or [])}
    final = replace(final, evidence=_cite(i for i in (final.evidence or []) if i in allowed))
    return _guard(final, det)


def resolve(det: Decision, llm_view: Optional[dict], case: dict) -> tuple:
    """The lead's single-hit contract: (final Decision, trace). Makes the screening call only on a
    disagreement; any screener failure resolves to REVIEW (never a crash, never a clearance)."""
    screen = None
    # resolve_one already keeps the rules line when the view is missing or invalid. Do not spend a
    # screener call on that view: it is not a second opinion.
    decision = llm_view.get("decision") if isinstance(llm_view, dict) else None
    code = llm_view.get("reason_code") if isinstance(llm_view, dict) else None
    usable = decision in (DIFF, SAME, REVIEW) and code in (llm_judge.CODES.get(decision) or [])
    if usable and decision != det.decision:
        try:
            screen = _screen(case, det, llm_view)
        except Exception:  # noqa: BLE001
            screen = None
    allowed = case.get("allowed_ids") if isinstance(case, dict) else None
    final, path = resolve_one(det, llm_view, screen, allowed_ids=allowed, case=case)
    final = _limit(final, det, case)
    trace = {"deterministic": {"decision": det.decision, "reason_code": det.reason_code},
             "llm": llm_view, "screener": screen,
             "final": {"decision": final.decision, "reason_code": final.reason_code}, "path": path}
    label = _guard_label(screen, allowed, det, llm_view, case, path)
    if label:
        trace["guard"] = label
    return final, trace


def review_all(items: list, data, log=None) -> Dict[str, Decision]:
    log = log or (lambda m: None)
    if not items or not llm.available():
        return {}
    STATS.clear()
    cases = {}
    for d, profile, res, alert in items:
        try:
            cases[d.hit_id] = (d, llm_judge.build_case(d, profile, res, alert, data))
        except Exception as e:  # noqa: BLE001
            log("arbiter: could not build the case for %s (%s), rules decision kept" % (d.hit_id, type(e).__name__))
    ids = sorted(cases)

    def judge_one(hid):
        try:
            return hid, llm_judge.judge(cases[hid][1])
        except Exception:  # noqa: BLE001
            return hid, None

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        views = dict(pool.map(judge_one, ids))
    disagree = [h for h in ids if views.get(h) is not None and views[h]["decision"] != cases[h][0].decision]

    def screen_one(hid):
        try:
            return hid, _screen(cases[hid][1], cases[hid][0], views[hid])
        except Exception:  # noqa: BLE001
            return hid, None

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        screens = dict(pool.map(screen_one, disagree))

    out = {}
    with _LOCK:
        _TRACE.clear()
    for hid in ids:
        det = cases[hid][0]
        allowed = cases[hid][1].get("allowed_ids")
        final, path = resolve_one(det, views.get(hid), screens.get(hid),
                                  allowed_ids=allowed, case=cases[hid][1])
        final = _limit(final, det, cases[hid][1])
        _bump(path)
        traced = {"deterministic": {"decision": det.decision, "reason_code": det.reason_code},
                  "llm": views.get(hid), "screener": screens.get(hid),
                  "final": {"decision": final.decision, "reason_code": final.reason_code},
                  "path": path}
        label = _guard_label(screens.get(hid), allowed, det, views.get(hid), cases[hid][1], path)
        if label:
            traced["guard"] = label
        with _LOCK:
            _TRACE[hid] = traced
        if final is not det:
            out[hid] = final
    n = len(ids)
    agree = STATS.get("agree", 0)
    log("arbiter: %d hits, %d with an LLM view, agreement %d (%.1f%%), disagreements %d -> %s; model calls %s"
        % (n, n - STATS.get("llm_unavailable", 0), agree, 100.0 * agree / max(1, n - STATS.get("llm_unavailable", 0)),
           len(disagree), json.dumps({k: v for k, v in sorted(STATS.items()) if k not in ("agree", "llm_unavailable")}),
           json.dumps(llm.STATS)))
    return out
