"""Unit tests for system/engine/load.py (Data contract, PLAN.md 5A). Made-up values only.

Run: py -3 -X utf8 -m unittest discover -s tests
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "system"))

from engine import load  # noqa: E402


def _write(folder, name, rows):
    with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


class HelperTests(unittest.TestCase):
    def test_as_list(self):
        self.assertEqual(load.as_list(None), [])
        self.assertEqual(load.as_list("a; b ;; c"), ["a", "b", "c"])
        self.assertEqual(load.as_list([" x ", "", None, "y"]), ["x", "y"])
        self.assertEqual(load.as_list(""), [])

    def test_digits(self):
        self.assertEqual(load.digits("+44 7700 900123"), "447700900123")
        self.assertEqual(load.digits(None), "")


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        _write(self.dir, "customers.jsonl", [
            {"record_id": "CUS-B", "email": " Ann@Example.test ", "phone": "+1 555 0100"},
            {"record_id": "CUS-A", "email": "ann@example.test", "phone": "1-555-0100"},
        ])
        _write(self.dir, "accounts.jsonl", [
            {"account_id": "ACC-1", "customer_id": "CUS-B", "login_handle": "AnnX"},
            {"account_id": "ACC-1", "customer_id": "CUS-A", "login_handle": "annx"},
        ])
        _write(self.dir, "kyc_checks.jsonl", [
            {"check_id": "KYC-2", "applicant_id": "APP-1", "document_number": "ab12", "result": "approved"},
            {"check_id": "KYC-1", "applicant_id": "APP-1", "document_number": "AB12", "result": "rejected"},
        ])

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_indexes(self):
        d = load.load(self.dir)
        self.assertEqual(sorted(d.customers), ["CUS-A", "CUS-B"])
        self.assertEqual(d.customers_by_email["ann@example.test"], ["CUS-A", "CUS-B"])
        self.assertEqual(d.customers_by_phone["15550100"], ["CUS-A", "CUS-B"])
        self.assertEqual([r["customer_id"] for r in d.accounts_by_id["ACC-1"]], ["CUS-A", "CUS-B"])
        self.assertEqual(len(d.accounts_by_login["annx"]), 2)
        self.assertEqual([r["check_id"] for r in d.kyc_by_applicant["APP-1"]], ["KYC-1", "KYC-2"])
        self.assertEqual([r["check_id"] for r in d.kyc_by_docnum["AB12"]], ["KYC-2"])
        self.assertEqual(d.customers["CUS-B"]["email"], " Ann@Example.test ")  # raw row kept

    def test_missing_files_are_empty(self):
        d = load.load(self.dir)
        self.assertEqual(d.hits, {})
        self.assertEqual(d.alerts, {})
        self.assertEqual(d.notes_by_email, {})
        self.assertEqual(d.search_by_query, {})
        self.assertEqual(d.onboarding_by_customer, {})
        self.assertIsNone(d.name_variants)


if __name__ == "__main__":
    unittest.main()