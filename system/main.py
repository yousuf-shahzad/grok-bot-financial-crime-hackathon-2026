"""Entry point: main.py <data folder> <output file>. One JSON line per hit.

Pipeline: load once -> per alert resolve once -> per hit extract -> decide -> write.
Never crashes on a single hit: any error becomes REVIEW / INSUFFICIENT_DATA.
"""
from __future__ import annotations

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import model  # noqa: E402
from engine.model import Decision, HitProfile, Resolution  # noqa: E402


def log(msg: str) -> None:
    sys.stderr.write(msg + "\n")


def _optional(name: str):
    """Import a teammate's module; while it is not merged yet the pipeline still runs."""
    try:
        return __import__("engine." + name, fromlist=[name])
    except ModuleNotFoundError as e:
        if e.name != "engine." + name:
            raise
        log("main: engine/%s.py not present yet, using fallback" % name)
        return None


load = _optional("load")
resolve = _optional("resolve")
hitfacts = _optional("hitfacts")
judge = _optional("judge")

# Optional LLM cross-examiner (Yousuf's Claude). Any import problem means rules only, never a crash.
crossexam = None
if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine", "crossexam.py")):
    try:
        from engine import crossexam  # type: ignore
    except Exception as _e:  # noqa: BLE001
        crossexam = None
        log("main: crossexam unavailable (%s: %s), rules only" % (type(_e).__name__, _e))

REVIEW_CODES = ("INSUFFICIENT_DATA", "AMBIGUOUS_CUSTOMER_RECORD")
CODES = {"DIFFERENT_ENTITY": ("TEMPORAL_IMPOSSIBILITY", "DOB_MISMATCH", "LOCATION_MISMATCH",
                              "NAME_MISMATCH_VERIFIED", "ENTITY_TYPE_MISMATCH", "DECEASED"),
         "SAME_ENTITY": ("NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH", "NAME_LOCATION_MATCH"),
         "REVIEW": REVIEW_CODES}

# Optional dual decision path (rules vs Grok judge + screening agent). Rules only if absent or broken.
arbiter = None
if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine", "arbiter.py")):
    try:
        from engine import arbiter  # type: ignore
    except Exception as _e:  # noqa: BLE001
        arbiter = None
        log("main: arbiter unavailable (%s: %s), rules only" % (type(_e).__name__, _e))


def _arbiter_ok(old: Decision, new) -> bool:
    """The hard safety rule, enforced here too: the dual path may change a line in any way EXCEPT
    create a clearance. A DIFFERENT_ENTITY out must already have been DIFFERENT_ENTITY in."""
    if not isinstance(new, Decision) or new.hit_id != old.hit_id or new.alert_id != old.alert_id:
        return False
    if new.decision not in CODES or new.reason_code not in CODES[new.decision]:
        return False
    if new.decision == "DIFFERENT_ENTITY" and (old.decision != "DIFFERENT_ENTITY" or new.reason_code != old.reason_code):
        return False
    return True


DUAL_MODE_DEFAULT = "advisory"  # flip to "enforce" once enforce scores >= rules-only with 0 unsafe


def dual_mode() -> str:
    """DUAL_MODE: 'enforce' applies the dual path's (guarded) changes; 'advisory' computes its trace for
    the GUI but never changes an output line; 'rules' makes no judge/screener calls at all ('off' is an
    alias). Anything else falls back to the default."""
    m = str(os.environ.get("DUAL_MODE") or DUAL_MODE_DEFAULT).strip().lower()
    m = "rules" if m == "off" else m
    return m if m in ("advisory", "enforce", "rules") else DUAL_MODE_DEFAULT


def arbitrate_all(decisions: list, items: list, data) -> dict:
    """{hit_id: Decision} from the dual path, guarded; {} on any failure, without the module/key,
    or unless DUAL_MODE=enforce."""
    mode = dual_mode()
    if arbiter is None or not items or mode == "rules":
        return {}
    by_id = {d.hit_id: d for d in decisions}
    current = [(by_id.get(d.hit_id, d),) + tuple(rest) for d, *rest in items]
    try:
        got = arbiter.review_all(current, data, log=log) or {}
    except Exception:  # noqa: BLE001
        log("main: arbiter failed, keeping the decisions so far\n" + traceback.format_exc())
        return {}
    out = {}
    for hid in sorted(str(k) for k in got) if isinstance(got, dict) else []:
        old = by_id.get(hid)
        if old is not None and _arbiter_ok(old, got[hid]):
            out[hid] = got[hid]
        elif old is not None:
            log("main: arbiter change for %s ignored (it would create a clearance or is malformed)" % hid)
    if mode != "enforce":
        if out:
            log("main: DUAL_MODE=advisory: %d dual-path change(s) traced, none applied" % len(out))
        return {}
    return out


def _accept(old: Decision, new) -> bool:
    """The lead's rule, enforced here: the cross-examiner may only turn a clearance into REVIEW."""
    return (old.decision == "DIFFERENT_ENTITY" and isinstance(new, Decision) and new.decision == "REVIEW"
            and new.reason_code in REVIEW_CODES and new.hit_id == old.hit_id and new.alert_id == old.alert_id)


def cross_examine_all(items: list, data) -> dict:
    """items: [(decision, profile, resolution, alert)] for every judged hit, in output order.
    Returns {hit_id: Decision} for the decisions to replace (guarded). Any failure: {} (rules only)."""
    if crossexam is None or not items:
        return {}
    try:
        if hasattr(crossexam, "review_all"):
            got = crossexam.review_all(items, data, log=log) or {}
        else:  # per-hit API
            got = {}
            for d, profile, res, alert in items:
                if d.decision == "DIFFERENT_ENTITY":
                    got[d.hit_id] = crossexam.review(d, profile, res, alert, data)
    except Exception:  # noqa: BLE001
        log("main: crossexam failed, keeping the rules' decisions\n" + traceback.format_exc())
        return {}
    if not isinstance(got, dict):
        log("main: crossexam returned %s, not a dict; ignored" % type(got).__name__)
        return {}
    by_id = {d.hit_id: d for d, _, _, _ in items}
    out = {}
    for hid in sorted(str(k) for k in got):
        old, new = by_id.get(hid), got.get(hid)
        if old is None or new is None or new is old:
            continue
        if _accept(old, new):
            out[hid] = new
        else:
            log("main: crossexam change for %s ignored (only DIFFERENT_ENTITY -> REVIEW is allowed)" % hid)
    if out:
        log("main: crossexam sent %d clearance(s) to REVIEW" % len(out))
    return out


def read_table(folder: str, name: str) -> list:
    """Rows of <name>.jsonl (or <name>.json): JSON Lines, or one JSON array / {key: [rows]} object.
    Tolerates a UTF-8 BOM, blank and malformed lines. Fallback only: load.py is the main reader."""
    for ext in (".jsonl", ".json"):
        path = os.path.join(folder, name + ext)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
        stripped = text.lstrip()
        if stripped.startswith(("[", "{")):
            try:
                obj = json.loads(stripped)  # whole-file JSON; multi-line JSONL fails here and is read below
            except ValueError:
                obj = None
            if isinstance(obj, dict):
                if name.rstrip("s") + "_id" in obj:   # a one-row JSONL file
                    obj = [obj]
                else:                                 # a {"hits": [...]} style wrapper
                    obj = next((v for k, v in sorted(obj.items()) if isinstance(v, list)), [])
            if isinstance(obj, list):
                return [r for r in obj if isinstance(r, dict)]
        rows = []
        for n, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                log("main: %s line %d is not valid JSON, skipped" % (name + ext, n))
                continue
            if isinstance(r, dict):
                rows.append(r)
        return rows
    log("main: no %s.jsonl or %s.json in the data folder" % (name, name))
    return []


def fallback_decision(hit_id: str, alert_id: str, why: str = "") -> Decision:
    reason = ("The automated checks could not reach a decision for this hit%s. "
              "It is sent to an analyst for review." % (" (" + why + ")" if why else ""))
    return Decision(hit_id=hit_id, alert_id=alert_id, decision="REVIEW",
                    reason_code="INSUFFICIENT_DATA", customer_record_id=None,
                    reason=reason, evidence=[])


def to_line(d: Decision) -> str:
    out = {
        "hit_id": d.hit_id,
        "alert_id": d.alert_id,
        "decision": d.decision,
        "reason_code": d.reason_code,
        "customer_record_id": d.customer_record_id,
        "reason": d.reason,
        "evidence": sorted(set(d.evidence or [])),
    }
    return json.dumps(out, ensure_ascii=False, sort_keys=False)


def main(argv: list) -> int:
    if len(argv) != 3:
        log("usage: main.py <data folder> <output file>")
        return 2
    folder, out_path = os.path.abspath(argv[1]), os.path.abspath(argv[2])

    data = None
    if load is not None:
        try:
            data = load.load(folder)
        except Exception:
            log("main: load failed, every hit falls back to REVIEW\n" + traceback.format_exc())
            data = None

    # alerts and hits: from the loader when it has them (it handles every file shape), else our own reader
    alert_rows = list((getattr(data, "alerts", None) or {}).values()) if data is not None else []
    hit_rows = list((getattr(data, "hits", None) or {}).values()) if data is not None else []
    if not alert_rows:
        alert_rows = read_table(folder, "alerts")
    if not hit_rows:
        hit_rows = read_table(folder, "hits")
    alerts = {}
    for a in alert_rows:
        aid = a.get("alert_id")
        if aid not in (None, ""):
            alerts[str(aid)] = a
    hits = [h for h in hit_rows if h.get("hit_id") not in (None, "")]
    hits.sort(key=lambda h: (str(h.get("alert_id") or ""), str(h.get("hit_id"))))
    log("main: %d alerts, %d hits" % (len(alerts), len(hits)))

    # install name_variants.json (if the loader found one) so names.py uses it over its built-in table
    if data is not None:
        try:
            from engine import names as _names
            if hasattr(_names, "use_variants"):
                _names.use_variants(getattr(data, "name_variants", None))
        except Exception:
            log("main: could not install name variants, using built-in table\n" + traceback.format_exc())

    decisions = []  # in output order
    items = []      # (decision, profile, resolution, alert) for every hit the judge decided
    resolved = {}   # alert_id -> Resolution, resolve once per alert
    for hit in hits:
        hit_id, alert_id = str(hit["hit_id"]), str(hit.get("alert_id") or "")
        alert = alerts.get(alert_id, {"alert_id": alert_id})
        judged = None
        try:
            if alert_id not in resolved:
                if resolve is not None and data is not None:
                    resolved[alert_id] = resolve.resolve(alert, data)
                else:
                    resolved[alert_id] = Resolution(people=[], note="resolver not available")
            res = resolved[alert_id]
            if hitfacts is not None and data is not None:
                profile = hitfacts.extract(hit, data)
            else:
                profile = HitProfile(hit_id=hit_id, alert_id=alert_id,
                                     entity_type=str(hit.get("entity_type") or ""))
            if judge is not None:
                d = judge.decide(profile, res, alert)
                judged = (profile, res, alert)
            else:
                d = fallback_decision(hit_id, alert_id)
        except Exception:
            log("main: error on %s, writing REVIEW\n%s" % (hit_id, traceback.format_exc()))
            d = fallback_decision(hit_id, alert_id)
            judged = None
        # the output always carries the file's own IDs
        d.hit_id, d.alert_id = hit_id, alert_id
        decisions.append(d)
        if judged is not None:
            items.append((d,) + judged)

    # optional LLM cross-examiner, one batch so calls can run in parallel; guarded in cross_examine_all
    replace = cross_examine_all(items, data)
    decisions = [replace.get(d.hit_id, d) for d in decisions]
    # optional dual path: Grok judge on every hit, screening agent on disagreement (after crossexam)
    dual = arbitrate_all(decisions, items, data)
    lines = [to_line(dual.get(d.hit_id, d)) for d in decisions]

    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for line in lines:
            f.write(line + "\n")
    log("main: wrote %d lines to %s" % (len(lines), out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
