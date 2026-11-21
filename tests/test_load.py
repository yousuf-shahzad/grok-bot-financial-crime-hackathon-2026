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


def _write_text(folder, name, text):
    with open(os.path.join(folder, name), "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


class OfficialFormatTests(unittest.TestCase):
    """Shapes the official / unseen files might use. Invented rows only."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_json_array_file(self):
        rows = [{"hit_id": "H-2", "name": "Zed"}, {"hit_id": "H-1", "name": "Yan"}]
        _write_text(self.dir, "hits.jsonl", json.dumps(rows, indent=2))
        d = load.load(self.dir)
        self.assertEqual(list(d.hits), ["H-1", "H-2"])

    def test_json_extension_fallback(self):
        _write_text(self.dir, "alerts.json", json.dumps([{"alert_id": "AL-9"}]))
        self.assertEqual(list(load.load(self.dir).alerts), ["AL-9"])

    def test_jsonl_preferred_over_json(self):
        _write_text(self.dir, "alerts.jsonl", json.dumps({"alert_id": "AL-L"}) + "\n")
        _write_text(self.dir, "alerts.json", json.dumps([{"alert_id": "AL-J"}]))
        self.assertEqual(list(load.load(self.dir).alerts), ["AL-L"])

    def test_wrapped_array(self):
        _write_text(self.dir, "notes.json", json.dumps({"notes": [
            {"note_id": "NOTE-1", "requester_email": "Pat@Mail.test", "text": "x"}]}))
        d = load.load(self.dir)
        self.assertEqual([n["note_id"] for n in d.notes_by_email["pat@mail.test"]], ["NOTE-1"])

    def test_bom_blank_and_malformed_lines(self):
        text = ("\ufeff" + json.dumps({"record_id": "CUS-1", "email": "a@b.test"}) + "\r\n"
                "\n   \n"
                "{not json\n"
                "[1, 2]\n"
                "42\n"
                + json.dumps({"record_id": "CUS-2"}) + "\n"
                + json.dumps({"record_id": "CUS-3"}))  # no trailing newline
        _write_text(self.dir, "customers.jsonl", text)
        d = load.load(self.dir)
        self.assertEqual(list(d.customers), ["CUS-1", "CUS-2", "CUS-3"])
        self.assertEqual(d.customers_by_email["a@b.test"], ["CUS-1"])

    def test_bom_on_json_array(self):
        _write_text(self.dir, "hits.json", "\ufeff" + json.dumps([{"hit_id": "H-7"}]))
        self.assertEqual(list(load.load(self.dir).hits), ["H-7"])

    def test_broken_array_falls_back_without_crash(self):
        _write_text(self.dir, "hits.jsonl", "[\n" + json.dumps({"hit_id": "H-1"}) + ",\n{broken\n")
        self.assertEqual(list(load.load(self.dir).hits), ["H-1"])

    def test_empty_and_garbage_files(self):
        _write_text(self.dir, "customers.jsonl", "")
        _write_text(self.dir, "hits.jsonl", "\ufeff\n\n")
        _write_text(self.dir, "alerts.jsonl", "garbage\x00\n")
        with open(os.path.join(self.dir, "notes.jsonl"), "wb") as fh:
            fh.write(b"\xff\xfe\x00bad bytes\n")
        d = load.load(self.dir)
        self.assertEqual((d.customers, d.hits, d.alerts, d.notes_by_email), ({}, {}, {}, {}))

    def test_numeric_ids_phones_and_keys(self):
        _write_text(self.dir, "customers.jsonl", "\n".join(json.dumps(r) for r in [
            {"record_id": 20, "phone": 447700900123, "email": None},
            {"record_id": 3.0, "phone": 447700900123.0},
            {"record_id": True},
            {"record_id": None},
        ]))
        _write_text(self.dir, "accounts.jsonl", "\n".join(json.dumps(r) for r in [
            {"account_id": 7, "customer_id": 20, "login_handle": 99},
            {"account_id": 7, "customer_id": 3},
        ]))
        _write_text(self.dir, "kyc_checks.jsonl", json.dumps(
            {"check_id": 1, "applicant_id": 5, "document_number": 123456, "result": "APPROVED"}))
        d = load.load(self.dir)
        self.assertEqual(sorted(d.customers), ["20", "3"])
        self.assertEqual(d.customers_by_phone["447700900123"], ["20", "3"])
        self.assertEqual([r["customer_id"] for r in d.accounts_by_id["7"]], [20, 3])  # "20" < "3"
        self.assertEqual(len(d.accounts_by_login["99"]), 1)
        self.assertEqual(sorted(d.accounts_by_customer), ["20", "3"])
        self.assertEqual(len(d.kyc_by_applicant["5"]), 1)
        self.assertEqual(len(d.kyc_by_docnum["123456"]), 1)
        self.assertIsInstance(d.customers["20"]["phone"], int)  # raw row kept

    def test_duplicate_id_first_row_wins_and_ties_stable(self):
        _write_text(self.dir, "hits.jsonl", "\n".join(json.dumps(r) for r in [
            {"hit_id": "H-1", "name": "first"}, {"hit_id": "H-1", "name": "second"}]))
        _write_text(self.dir, "search_results.jsonl", "\n".join(json.dumps(r) for r in [
            {"query": "Q", "result_id": "SR-1", "title": "a"},
            {"query": "q ", "result_id": "SR-1", "title": "b"}]))
        d = load.load(self.dir)
        self.assertEqual(d.hits["H-1"]["name"], "first")
        self.assertEqual([r["title"] for r in d.search_by_query["q"]], ["a", "b"])

    def test_helpers_on_numbers_and_nesting(self):
        self.assertEqual(load.as_list(1990), ["1990"])
        self.assertEqual(load.as_list(1990.0), ["1990"])
        self.assertEqual(load.as_list(["1990-01", 1991, ["x; y", None], " "]), ["1990-01", "1991", "x; y"])
        self.assertEqual(load.as_list(True), [])
        self.assertEqual(load.digits(7700900123), "7700900123")
        self.assertEqual(load.digits(7700900123.0), "7700900123")
        self.assertEqual(load.digits(["1"]), "")


class NameVariantsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def _nv(self, text):
        _write_text(self.dir, "name_variants.json", text)
        return load.load(self.dir).name_variants

    def test_shapes_pass_through(self):
        shapes = [
            [["bob", "rob", "robert"], ["bill", "will"]],
            {"robert": ["bob", "rob"], "william": ["bill"]},
            {"groups": [["ann", "anna"]], "legal_forms": ["ltd", "llc"]},
        ]
        for shape in shapes:
            self.assertEqual(self._nv(json.dumps(shape)), shape)

    def test_bom(self):
        self.assertEqual(self._nv("\ufeff" + json.dumps([["al", "alan"]])), [["al", "alan"]])

    def test_broken_or_empty_is_none(self):
        for text in ["{broken", "", "   ", "[]", "{}", "42", '"text"', "null"]:
            self.assertIsNone(self._nv(text), text)

    def test_shapes_accepted_by_names(self):
        from engine import names
        if not hasattr(names, "use_variants"):
            self.skipTest("names.use_variants not present")
        try:
            for text in [json.dumps([["bob", "robert"]]), json.dumps({"groups": [["al", "alan"]]}), "{broken"]:
                names.use_variants(self._nv(text))
        finally:
            names.use_variants(None)  # restore built-in tables for other tests


if __name__ == "__main__":
    unittest.main()
