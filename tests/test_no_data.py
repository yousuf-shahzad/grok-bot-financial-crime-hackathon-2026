"""Fails if a dataset file, a key file or a data folder is in the repo (team repo or public copy).

Checks the files git tracks (or, outside git, every file under the repo root). Allowed data-shaped
files: invented fixtures under tests/fixtures/ and our own output/dev.jsonl.
"""
from __future__ import annotations

import os
import re
import subprocess
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

DATASET_NAMES = {"alerts", "hits", "customers", "accounts", "onboarding", "kyc_checks", "notes",
                 "search_results", "practice_labels", "name_variants"}


def repo_files() -> list:
    try:
        out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"], capture_output=True, check=True)
        files = [f for f in out.stdout.decode("utf-8").split("\0") if f]
        if files:
            return sorted(files)
    except (OSError, subprocess.CalledProcessError):
        pass
    found = []
    for d, dirs, names in os.walk(ROOT):
        dirs[:] = sorted(x for x in dirs if x not in (".git", "__pycache__"))
        for n in names:
            found.append(os.path.relpath(os.path.join(d, n), ROOT).replace(os.sep, "/"))
    return sorted(found)


def problems(files: list) -> list:
    bad = []
    for f in files:
        low = f.lower()
        base = os.path.basename(low)
        stem = re.sub(r"\.(jsonl?|csv|xlsx)$", "", base)
        fixture = low.startswith("tests/fixtures/")
        if low.endswith((".xlsx", ".xls", ".csv")):
            bad.append((f, "spreadsheet/csv"))
        elif re.match(r"^\.env($|\.)", base) and base != ".env.example":
            bad.append((f, "env file"))
        elif low.split("/")[0] in ("data", "dev") or "/data/dev/" in low:
            bad.append((f, "data folder"))
        elif base in ("policy_sheet.txt", "start_here.txt"):
            bad.append((f, "dataset text"))
        elif low.endswith(".jsonl") and not fixture and low != "output/dev.jsonl":
            bad.append((f, "jsonl outside fixtures/output"))
        elif low.endswith((".json", ".jsonl")) and stem in DATASET_NAMES and not fixture:
            bad.append((f, "dataset table name"))
    return bad


class NoDataInRepo(unittest.TestCase):
    def test_no_dataset_or_key_files(self):
        bad = problems(repo_files())
        self.assertEqual(bad, [], "data-like files must never be committed or published: %s" % bad)

    def test_detector_catches_the_usual_suspects(self):
        caught = {f for f, _ in problems([
            "data/ScreeningDevSet-browse.xlsx", "data/dev/customers.jsonl", "dev/hits.jsonl",
            ".env", "system/.env.local", "notes.jsonl", "tools/practice_labels.jsonl",
            "x/policy_sheet.txt", "demo/customers.json"])}
        self.assertEqual(len(caught), 9, caught)
        self.assertEqual(problems(["tests/fixtures/rare/customers.jsonl", "output/dev.jsonl",
                                   ".env.example", "system/engine/model.py"]), [])


if __name__ == "__main__":
    unittest.main()
