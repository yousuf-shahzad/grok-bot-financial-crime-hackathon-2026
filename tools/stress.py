#!/usr/bin/env python3
"""Stress harness: rewrite the dev data in ways the SOP says must NOT change any answer, rerun
system/run on each rewrite and report every decision that moves.

    python tools/stress.py data/dev [--only NAME,NAME] [--keep]

Each transform keeps the meaning of every record (SOP: names compare ignoring case, accents and
punctuation; dates are the same date in another format; codes and nationalities are countries;
list fields may arrive as real lists; file order means nothing). A good system gives the same
decision and reason code on every hit for every transform. A move to DIFFERENT_ENTITY is flagged
as UNSAFE because it is the 60-cost direction.

Rewritten copies go to a temporary folder outside the repo and are deleted afterwards (the data
is participants-only: never commit them). Standard library only. Not part of system/.
"""
from __future__ import annotations

import collections
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RUN = os.path.join(REPO, "system", "run")

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
LIST_FIELDS = {
    "alerts": ["hit_ids"],
    "hits": ["aliases", "dobs", "nationality", "citizenship", "countries", "addresses",
             "identifiers", "categories", "sources", "source_urls"],
}
CODE = {"United Kingdom": "GB", "United States": "US", "Nigeria": "NG", "Germany": "DE", "Spain": "ES",
        "France": "FR", "Italy": "IT", "Bangladesh": "BD", "Ireland": "IE", "Canada": "CA",
        "Australia": "AU", "Netherlands": "NL", "Austria": "AT", "Kenya": "KE", "Poland": "PL", "India": "IN"}
DEMONYM = {"United Kingdom": "British", "United States": "American", "Nigeria": "Nigerian",
           "Germany": "German", "Spain": "Spanish", "France": "French", "Italy": "Italian",
           "Bangladesh": "Bangladeshi", "Ireland": "Irish", "Canada": "Canadian", "Poland": "Polish",
           "India": "Indian"}


def read(folder, name):
    p = os.path.join(folder, name + ".jsonl")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def write(folder, name, rows):
    with open(os.path.join(folder, name + ".jsonl"), "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def iso_to(fmt, s, k):
    m = ISO.match(str(s or ""))
    if not m:
        return s
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if fmt == "slash":
        return "%02d/%02d/%04d" % (d, mo, y)
    if fmt == "long":
        return "%d %s %d" % (d, MONTHS[mo - 1], y)
    if fmt == "us_long":
        return "%s %d, %d" % (MONTHS[mo - 1], d, y)
    return ["%02d/%02d/%04d" % (d, mo, y), "%d %s %d" % (d, MONTHS[mo - 1], y),
            "%s %d, %d" % (MONTHS[mo - 1], d, y)][k % 3]


def fold(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


# --------------------------------------------------------------------------------------------
# Transforms: (name, description, function(folder_in -> folder_out))
# --------------------------------------------------------------------------------------------

def t_shuffle(src, dst):
    rnd = random.Random(7)
    for fn in os.listdir(src):
        if fn.endswith(".jsonl"):
            rows = read(src, fn[:-6])
            rnd.shuffle(rows)
            write(dst, fn[:-6], rows)


def t_dates(src, dst):
    for name, fields in (("customers", ["dob"]), ("kyc_checks", ["verified_dob"])):
        rows = read(src, name)
        for i, r in enumerate(rows):
            for f in fields:
                r[f] = iso_to("mix", r.get(f), i)
        write(dst, name, rows)


def t_case_accents(src, dst):
    rows = read(src, "customers")
    for i, r in enumerate(rows):
        for f in ("full_name", "preferred_name"):
            if r.get(f):
                v = fold(r[f])
                r[f] = v.upper() if i % 2 else v.lower()
    write(dst, "customers", rows)
    rows = read(src, "hits")
    for r in rows:
        if r.get("name"):
            r["name"] = r["name"].upper()
    write(dst, "hits", rows)


def t_lists(src, dst):
    for name, fields in LIST_FIELDS.items():
        rows = read(src, name)
        for r in rows:
            for f in fields:
                v = r.get(f)
                if isinstance(v, str):
                    r[f] = [x.strip() for x in v.split(";") if x.strip()]
                elif v is None:
                    r[f] = []
        write(dst, name, rows)
    rows = read(src, "alerts")
    for r in rows:
        if isinstance(r.get("hit_count"), str):
            try:
                r["hit_count"] = int(float(r["hit_count"]))
            except ValueError:
                pass
        if isinstance(r.get("hit_ids"), str):
            r["hit_ids"] = [x.strip() for x in r["hit_ids"].split(";") if x.strip()]
    write(dst, "alerts", rows)


def t_countries(src, dst):
    rows = read(src, "customers")
    for i, r in enumerate(rows):
        rc = r.get("residence_country")
        if rc in CODE and i % 2 == 0:
            r["residence_country"] = CODE[rc]
        nat = r.get("nationality")
        if nat in DEMONYM and i % 3 == 0:
            r["nationality"] = DEMONYM[nat]
    write(dst, "customers", rows)


TRANSFORMS = [
    ("shuffle", "every file in a different record order", t_shuffle),
    ("dates", "customer and KYC dates of birth in other formats (DD/MM/YYYY, D Month YYYY, Month D, YYYY)", t_dates),
    ("case_accents", "customer names lower/upper case without accents, hit names upper case", t_case_accents),
    ("lists", "list fields as real JSON lists, hit_count as a number (likely official format)", t_lists),
    ("countries", "customer residence as ISO codes and nationality as demonyms", t_countries),
]


def run_system(folder, out):
    t = time.time()
    p = subprocess.run(["bash", RUN, folder, out], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if p.returncode != 0:
        sys.stderr.write(p.stderr[-2000:])
        raise SystemExit("system/run failed on " + folder)
    errors = [l for l in p.stderr.splitlines() if "error on" in l]
    with open(out, encoding="utf-8") as f:
        res = {}
        for l in f:
            o = json.loads(l)
            res[o["hit_id"]] = o
    return res, time.time() - t, errors


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    data = os.path.abspath(argv[1])
    only = None
    if "--only" in argv:
        only = set(argv[argv.index("--only") + 1].split(","))
    keep = "--keep" in argv
    labels = {}
    lp = os.path.join(data, "practice_labels.jsonl")
    if os.path.exists(lp):
        for r in read(data, "practice_labels"):
            labels[r["hit_id"]] = r["decision"]

    tmp = tempfile.mkdtemp(prefix="stress-")
    try:
        base, secs, errs = run_system(data, os.path.join(tmp, "base.jsonl"))
        print("baseline: %d hits in %.0fs, %d per-hit errors" % (len(base), secs, len(errs)))
        total_moves = 0
        for name, desc, fn in TRANSFORMS:
            if only and name not in only:
                continue
            dst = os.path.join(tmp, name)
            shutil.copytree(data, dst)
            fn(data, dst)
            res, secs, errs = run_system(dst, os.path.join(tmp, name + ".jsonl"))
            moves = collections.Counter()
            unsafe, examples = [], []
            for hid, b in sorted(base.items()):
                r = res.get(hid)
                if r is None:
                    moves["missing"] += 1
                    continue
                if (b["decision"], b["reason_code"]) != (r["decision"], r["reason_code"]):
                    moves[(b["decision"], r["decision"])] += 1
                    examples.append("%s %s/%s -> %s/%s%s" % (hid, b["decision"][:4], b["reason_code"],
                                                             r["decision"][:4], r["reason_code"],
                                                             " [practice]" if hid in labels else ""))
                    if r["decision"] == "DIFFERENT_ENTITY" and b["decision"] != "DIFFERENT_ENTITY":
                        unsafe.append(hid)
            n = sum(moves.values())
            total_moves += n
            print("\n== %s: %s" % (name, desc))
            print("   %d hits in %.0fs, %d per-hit errors, %d decisions or reason codes moved%s"
                  % (len(res), secs, len(errs), n, "" if n else "  OK"))
            for k, v in moves.most_common():
                print("   %4d  %s" % (v, k if isinstance(k, str) else "%s -> %s" % k))
            if unsafe:
                print("   UNSAFE (new clearances): " + " ".join(unsafe[:20]))
            for e in examples[:8]:
                print("     " + e)
            if not keep:
                shutil.rmtree(dst, ignore_errors=True)
        print("\nTOTAL moved across transforms: %d" % total_moves)
        return 0 if total_moves == 0 else 1
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print("kept rewritten copies in " + tmp + " (delete them when done)")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
