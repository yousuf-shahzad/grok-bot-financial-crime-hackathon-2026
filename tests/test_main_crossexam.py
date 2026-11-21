"""main.cross_examine guard: the LLM cross-examiner may only turn DIFFERENT_ENTITY into REVIEW.
Stand-in crossexam modules, made-up IDs only."""
from __future__ import annotations

import os
import sys
import types
import unittest
from dataclasses import replace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "system"))

import main  # noqa: E402
from engine.model import Decision  # noqa: E402


def dec(decision="DIFFERENT_ENTITY", code="LOCATION_MISMATCH"):
    return Decision(hit_id="H-X1", alert_id="A-X1", decision=decision, reason_code=code,
                    customer_record_id="CUS-X1", reason="One. Two.", evidence=["CUS-X1"])


def fake(fn):
    return types.SimpleNamespace(review=fn)


class CrossExamGuard(unittest.TestCase):
    def setUp(self):
        self._orig = main.crossexam

    def tearDown(self):
        main.crossexam = self._orig

    def run_with(self, fn, d):
        main.crossexam = fake(fn)
        return main.cross_examine(d, None, None, {}, None)

    def test_no_module_is_rules_only(self):
        main.crossexam = None
        d = dec()
        self.assertIs(main.cross_examine(d, None, None, {}, None), d)

    def test_clear_to_review_accepted(self):
        out = self.run_with(lambda d, *a: replace(d, decision="REVIEW", reason_code="INSUFFICIENT_DATA",
                                                  reason="Text says otherwise. Sent to review."), dec())
        self.assertEqual((out.decision, out.reason_code), ("REVIEW", "INSUFFICIENT_DATA"))

    def test_cannot_create_confirmation(self):
        d = dec()
        out = self.run_with(lambda d, *a: replace(d, decision="SAME_ENTITY", reason_code="NAME_DOB_MATCH"), d)
        self.assertIs(out, d)

    def test_cannot_change_other_hit(self):
        d = dec()
        out = self.run_with(lambda d, *a: replace(d, hit_id="H-OTHER", decision="REVIEW",
                                                  reason_code="INSUFFICIENT_DATA"), d)
        self.assertIs(out, d)

    def test_never_called_on_review_or_same(self):
        called = []
        for d in (dec("REVIEW", "INSUFFICIENT_DATA"), dec("SAME_ENTITY", "NAME_DOB_MATCH")):
            out = self.run_with(lambda d, *a: called.append(1) or replace(d, decision="DIFFERENT_ENTITY"), d)
            self.assertIs(out, d)
        self.assertEqual(called, [])

    def test_error_keeps_rules(self):
        def boom(*a):
            raise RuntimeError("network down")
        d = dec()
        self.assertIs(self.run_with(boom, d), d)

    def test_none_keeps_rules(self):
        d = dec()
        self.assertIs(self.run_with(lambda *a: None, d), d)


if __name__ == "__main__":
    unittest.main()
