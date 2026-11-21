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


def read_jsonl(path: str) -> list:
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                log("main: %s line %d is not valid JSON, skipped" % (os.path.basename(path), n))
    return rows


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

    alerts = {}
    for a in read_jsonl(os.path.join(folder, "alerts.jsonl")):
        aid = a.get("alert_id")
        if aid:
            alerts[str(aid)] = a
    hits = [h for h in read_jsonl(os.path.join(folder, "hits.jsonl")) if h.get("hit_id")]
    hits.sort(key=lambda h: (str(h.get("alert_id") or ""), str(h.get("hit_id"))))
    log("main: %d alerts, %d hits" % (len(alerts), len(hits)))

    data = None
    if load is not None:
        try:
            data = load.load(folder)
        except Exception:
            log("main: load failed, every hit falls back to REVIEW\n" + traceback.format_exc())
            data = None

    # install name_variants.json (if the loader found one) so names.py uses it over its built-in table
    if data is not None:
        try:
            from engine import names as _names
            if hasattr(_names, "use_variants"):
                _names.use_variants(getattr(data, "name_variants", None))
        except Exception:
            log("main: could not install name variants, using built-in table\n" + traceback.format_exc())

    lines = []
    resolved = {}  # alert_id -> Resolution, resolve once per alert
    for hit in hits:
        hit_id, alert_id = str(hit["hit_id"]), str(hit.get("alert_id") or "")
        alert = alerts.get(alert_id, {"alert_id": alert_id})
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
            else:
                d = fallback_decision(hit_id, alert_id)
        except Exception:
            log("main: error on %s, writing REVIEW\n%s" % (hit_id, traceback.format_exc()))
            d = fallback_decision(hit_id, alert_id)
        # the output always carries the file's own IDs
        d.hit_id, d.alert_id = hit_id, alert_id
        lines.append(to_line(d))

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
