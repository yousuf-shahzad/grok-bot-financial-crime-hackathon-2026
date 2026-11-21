"""Score an output file against the practice labels (our stand-in for the organisers' validate.py).

Usage: py -3 -X utf8 tools/score.py output/dev.jsonl data/dev/practice_labels.jsonl [--all]

Prints: format problems, decision cost and score (cost saved versus all-REVIEW), unsafe clearances,
review rate, reason-code / customer_record_id / evidence accuracy on correct decisions, and a
per-hit table of every miss with the label's path. Prints IDs and codes only, never record text.
--all also lists the hits we got right.
"""
from __future__ import annotations

import json
import re
import sys

COST = {  # COST[truth][ours]
    "DIFFERENT_ENTITY": {"DIFFERENT_ENTITY": 0, "SAME_ENTITY": 3, "REVIEW": 3},
    "SAME_ENTITY": {"DIFFERENT_ENTITY": 60, "SAME_ENTITY": 0, "REVIEW": 2},
    "REVIEW": {"DIFFERENT_ENTITY": 60, "SAME_ENTITY": 2, "REVIEW": 0},
}
CODES = {
    "DIFFERENT_ENTITY": {"TEMPORAL_IMPOSSIBILITY", "DOB_MISMATCH", "LOCATION_MISMATCH",
                         "NAME_MISMATCH_VERIFIED", "ENTITY_TYPE_MISMATCH", "DECEASED"},
    "SAME_ENTITY": {"NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH", "NAME_LOCATION_MATCH"},
    "REVIEW": {"INSUFFICIENT_DATA", "AMBIGUOUS_CUSTOMER_RECORD"},
}
KEYS = ["hit_id", "alert_id", "decision", "reason_code", "customer_record_id", "reason", "evidence"]
SHORT = {"DIFFERENT_ENTITY": "DIFF", "SAME_ENTITY": "SAME", "REVIEW": "REV"}


def as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v).strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            return as_list(json.loads(s))
        except ValueError:
            pass
    return [p.strip() for p in re.split(r"[;,]", s) if p.strip()]


def read_jsonl(path: str) -> list:
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    print("  bad JSON on line %d of %s" % (n, path))
    return rows


def sentences(text: str) -> int:
    return len(re.findall(r"[.!?](?=\s|$)", (text or "").strip()))


def check_format(rows: list) -> list:
    problems = []
    seen = set()
    for r in rows:
        hid = r.get("hit_id", "?")
        if list(r.keys()) != KEYS:
            problems.append("%s: keys %s" % (hid, list(r.keys())))
        if hid in seen:
            problems.append("%s: duplicate hit_id" % hid)
        seen.add(hid)
        d, c = r.get("decision"), r.get("reason_code")
        if d not in CODES:
            problems.append("%s: bad decision %r" % (hid, d))
        elif c not in CODES[d]:
            problems.append("%s: reason_code %r does not belong to %s" % (hid, c, d))
        n = sentences(r.get("reason", ""))
        if not 2 <= n <= 4:
            problems.append("%s: reason has %d sentences (need 2 to 4)" % (hid, n))
        if not isinstance(r.get("evidence"), list):
            problems.append("%s: evidence is not a list" % hid)
        cid = r.get("customer_record_id")
        if cid is not None and not isinstance(cid, str):
            problems.append("%s: customer_record_id is not a string or null" % hid)
    return problems


def main(argv: list) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    show_all = "--all" in argv
    if len(args) != 2:
        print(__doc__)
        return 2
    out = read_jsonl(args[0])
    labels = read_jsonl(args[1])
    ours = {r.get("hit_id"): r for r in out}

    problems = check_format(out)
    print("== format: %d lines, %d problems" % (len(out), len(problems)))
    for p in problems[:20]:
        print("  " + p)
    if len(problems) > 20:
        print("  ... %d more" % (len(problems) - 20))

    cost = base = 0
    unsafe = []
    missing = []
    n = reviews = right = code_ok = cid_ok = 0
    ev_prec = ev_rec = 0.0
    confusion = {t: {o: 0 for o in COST} for t in COST}
    rows = []
    for lab in sorted(labels, key=lambda x: (str(x.get("alert_id")), str(x.get("hit_id")))):
        hid = lab.get("hit_id")
        truth = lab.get("decision")
        if truth not in COST:
            continue
        n += 1
        base += COST[truth]["REVIEW"]
        r = ours.get(hid)
        if r is None:
            missing.append(hid)
            cost += COST[truth]["REVIEW"]
            continue
        d = r.get("decision")
        if d not in COST:
            d = "REVIEW"
        c = COST[truth][d]
        cost += c
        confusion[truth][d] += 1
        reviews += d == "REVIEW"
        if d == "DIFFERENT_ENTITY" and truth != "DIFFERENT_ENTITY":
            unsafe.append(hid)
        lab_codes = set(as_list(lab.get("reason_codes")))
        lab_cids = set(as_list(lab.get("customer_record_ids")))
        lab_ev = set(as_list(lab.get("evidence")))
        our_ev = set(r.get("evidence") or [])
        cid = r.get("customer_record_id")
        this_code = this_cid = None
        if d == truth:
            right += 1
            this_code = r.get("reason_code") in lab_codes
            code_ok += this_code
            this_cid = (cid in lab_cids) if lab_cids else (cid is None)
            cid_ok += this_cid
            if our_ev:
                ev_prec += len(our_ev & lab_ev) / len(our_ev)
            elif not lab_ev:
                ev_prec += 1
            if lab_ev:
                ev_rec += len(our_ev & lab_ev) / len(lab_ev)
            elif not our_ev:
                ev_rec += 1
        miss = d != truth or this_code is False or this_cid is False
        if miss or show_all:
            rows.append((c, hid, truth, sorted(lab_codes), d, r.get("reason_code"),
                         sorted(lab_cids), cid, sorted(lab_ev - our_ev), sorted(our_ev - lab_ev),
                         lab.get("path") or ""))

    score = max(0.0, (base - cost) / base) if base else 0.0
    print("\n== decisions on %d practice hits" % n)
    print("  cost %d vs all-REVIEW %d  ->  decision score %.1f%%" % (cost, base, 100 * score))
    print("  unsafe clearances (DIFF when truth is not DIFF): %d %s" % (len(unsafe), " ".join(unsafe)))
    print("  review rate %.0f%%, correct %d/%d" % (100.0 * reviews / max(1, n), right, n))
    if missing:
        print("  MISSING from output (counted as REVIEW): %s" % " ".join(missing))
    print("  confusion, rows = truth, cols = ours")
    print("    truth   DIFF  SAME   REV")
    for t in COST:
        print("    %-5s %6d %5d %5d" % (SHORT[t], confusion[t]["DIFFERENT_ENTITY"],
                                     confusion[t]["SAME_ENTITY"], confusion[t]["REVIEW"]))
    if right:
        print("\n== on the %d correct decisions" % right)
        print("  reason code accepted     %d/%d" % (code_ok, right))
        print("  customer_record_id right %d/%d" % (cid_ok, right))
        print("  evidence precision %.0f%%, recall %.0f%%" % (100 * ev_prec / right, 100 * ev_rec / right))

    if rows:
        print("\n== %s (most expensive first)" % ("all hits" if show_all else "misses"))
        for (c, hid, truth, lcodes, d, code, lcids, cid, ev_missing, ev_extra, path) in sorted(
                rows, key=lambda x: (-x[0], x[1])):
            print("- %s cost %d: truth %s %s | ours %s %s" % (
                hid, c, SHORT[truth], "/".join(lcodes), SHORT[d], code))
            print("    customer: truth %s | ours %s" % (" or ".join(lcids) or "null", cid))
            if ev_missing or ev_extra:
                print("    evidence: missing %s | extra %s" % (" ".join(ev_missing) or "-", " ".join(ev_extra) or "-"))
            if path:
                print("    path: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
