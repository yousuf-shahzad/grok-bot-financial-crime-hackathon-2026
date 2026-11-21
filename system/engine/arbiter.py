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


def _clean(s: str, limit: int = 220) -> str:
    s = re.sub(r"[.!?;:]+", ",", str(s or "")).strip(" ,")
    s = re.sub(r"\s+", " ", s)
    return s[:limit].rstrip(" ,")


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
            "explanation": str(got.get("explanation") or "").strip()}


def resolve_one(det: Decision, view: Optional[dict], screen: Optional[dict], screen_failed: bool = False) -> tuple:
    """Pure resolution: (final Decision, path). Unit-tested; holds the safety rule."""
    if view is None:
        return det, "llm_unavailable"
    if view["decision"] == det.decision:
        return det, "agree"
    who = {"deterministic": "the rules engine", "llm": "the Grok review", "neither": "neither view",
           "both": "both views"}
    s1 = ("The rules engine decided %s (%s), but an independent Grok review decided %s (%s)."
          % (_human(det.decision), det.reason_code, _human(view["decision"]), view["reason_code"]))
    if screen is None:
        s2 = "A screening agent could not settle the disagreement."
        error_in = None
    else:
        error_in = screen["error_in"]
        expl = _clean(screen.get("explanation") or "")
        s2 = "A screening agent compared both and found the error in %s%s." % (who[error_in], (": " + expl) if expl else "")
    missed = sorted({i for m in (screen or {}).get("significant_missed_facts", []) for i in m["evidence_ids"]
                     if not i.startswith(NO_CITE)})
    evidence = sorted(set(det.evidence) | set(missed))

    if error_in == "llm":
        s4 = _first_sentence(det.reason)
        reason = " ".join(x for x in (s1, s2, "The rules engine's decision stands.", s4) if x)
        return replace(det, reason=reason, evidence=evidence), "error_in_llm_keep_rules"
    if error_in == "deterministic" and view["decision"] in (SAME, REVIEW):
        ev = sorted(set(evidence) | {i for i in view.get("evidence_ids", []) if not i.startswith(NO_CITE)})
        reason = " ".join((s1, s2, "The Grok review's decision is taken."))
        return replace(det, decision=view["decision"], reason_code=view["reason_code"], reason=reason,
                       evidence=ev), "error_in_rules_take_llm"
    if error_in == "deterministic":  # the LLM wants a clearance the rules did not make
        reason = " ".join((s1, s2, "A clearance can only come from the rules engine, so an analyst decides."))
        return replace(det, decision=REVIEW, reason_code="INSUFFICIENT_DATA", reason=reason,
                       evidence=evidence), "error_in_rules_llm_clear_blocked"
    reason = " ".join((s1, s2, "An analyst decides."))
    return (replace(det, decision=REVIEW, reason_code="INSUFFICIENT_DATA", reason=reason, evidence=evidence),
            "screen_failed" if screen is None else "error_in_%s_review" % error_in)


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
        final, path = resolve_one(det, views.get(hid), screens.get(hid))
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
