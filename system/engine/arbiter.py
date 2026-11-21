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
    "short sentences.\n\nSOP:\n" + SOP)


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


def resolve_one(det: Decision, view: Optional[dict], screen: Optional[dict], screen_failed: bool = False,
                allowed_ids=None) -> tuple:
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
    if error_in not in who:
        s2 = "A screening agent could not settle the disagreement."
        error_in = None
    else:
        expl = _clean(_scrub_explanation(screen.get("explanation") or "", allowed_ids))
        s2 = "A screening agent compared both and found the error in %s%s." % (
            who[error_in], (": " + expl) if expl else "")
    missed = []
    for fact in (screen or {}).get("significant_missed_facts") or []:
        if isinstance(fact, dict):
            missed.extend(fact.get("evidence_ids") or [])
    # The line's evidence is the rules' IDs plus IDs the screener says were missed.
    # The model's own evidence list is not copied: it can name records that are not in the case.
    evidence = _cite(list(det.evidence or []) + list(missed))

    if error_in == "llm":
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
    if llm_view is not None and llm_view.get("decision") != det.decision:
        try:
            screen = _screen(case, det, llm_view)
        except Exception:  # noqa: BLE001
            screen = None
    allowed = case.get("allowed_ids") if isinstance(case, dict) else None
    final, path = resolve_one(det, llm_view, screen, allowed_ids=allowed)
    final = _limit(final, det, case)
    return final, {"deterministic": {"decision": det.decision, "reason_code": det.reason_code},
                   "llm": llm_view, "screener": screen,
                   "final": {"decision": final.decision, "reason_code": final.reason_code}, "path": path}


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
        final, path = resolve_one(det, views.get(hid), screens.get(hid),
                                  allowed_ids=cases[hid][1].get("allowed_ids"))
        final = _limit(final, det, cases[hid][1])
        _bump(path)
        with _LOCK:
            _TRACE[hid] = {"deterministic": {"decision": det.decision, "reason_code": det.reason_code},
                           "llm": views.get(hid), "screener": screens.get(hid),
                           "final": {"decision": final.decision, "reason_code": final.reason_code},
                           "path": path}
        if final is not det:
            out[hid] = final
    n = len(ids)
    agree = STATS.get("agree", 0)
    log("arbiter: %d hits, %d with an LLM view, agreement %d (%.1f%%), disagreements %d -> %s; model calls %s"
        % (n, n - STATS.get("llm_unavailable", 0), agree, 100.0 * agree / max(1, n - STATS.get("llm_unavailable", 0)),
           len(disagree), json.dumps({k: v for k, v in sorted(STATS.items()) if k not in ("agree", "llm_unavailable")}),
           json.dumps(llm.STATS)))
    return out
