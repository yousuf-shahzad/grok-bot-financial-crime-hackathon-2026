"""main.cross_examine_all guard: the LLM cross-examiner may only turn DIFFERENT_ENTITY into REVIEW.
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


def dec(hid="H-X1", decision="DIFFERENT_ENTITY", code="LOCATION_MISMATCH"):
    return Decision(hit_id=hid, alert_id="A-X1", decision=decision, reason_code=code,
                    customer_record_id="CUS-X1", reason="One. Two.", evidence=["CUS-X1"])


def to_review(d):
    return replace(d, decision="REVIEW", reason_code="INSUFFICIENT_DATA",
                   reason="Text says otherwise. Sent to review.")


def items(*ds):
    return [(d, None, None, {}) for d in ds]


class CrossExamGuard(unittest.TestCase):
    def setUp(self):
        self._orig = main.crossexam

    def tearDown(self):
        main.crossexam = self._orig

    def batch(self, fn, *ds):
        main.crossexam = types.SimpleNamespace(review_all=fn)
        return main.cross_examine_all(items(*ds), None)

    def test_no_module_is_rules_only(self):
        main.crossexam = None
        self.assertEqual(main.cross_examine_all(items(dec()), None), {})

    def test_empty_result_changes_nothing(self):
        self.assertEqual(self.batch(lambda it, data, log=None: {}, dec()), {})

    def test_clear_to_review_accepted(self):
        d = dec()
        out = self.batch(lambda it, data, log=None: {"H-X1": to_review(d)}, d)
        self.assertEqual(out["H-X1"].decision, "REVIEW")

    def test_cannot_create_confirmation_or_touch_non_clears(self):
        clear, rev, same = dec("H-1"), dec("H-2", "REVIEW", "INSUFFICIENT_DATA"), dec("H-3", "SAME_ENTITY", "NAME_DOB_MATCH")
        got = {"H-1": replace(clear, decision="SAME_ENTITY", reason_code="NAME_DOB_MATCH"),
               "H-2": replace(rev, decision="DIFFERENT_ENTITY", reason_code="LOCATION_MISMATCH"),
               "H-3": to_review(same)}
        self.assertEqual(self.batch(lambda it, data, log=None: got, clear, rev, same), {})

    def test_cannot_swap_hits(self):
        a, b = dec("H-1"), dec("H-2")
        out = self.batch(lambda it, data, log=None: {"H-1": to_review(b), "H-9": to_review(a)}, a, b)
        self.assertEqual(out, {})

    def test_error_or_bad_type_keeps_rules(self):
        def boom(it, data, log=None):
            raise RuntimeError("network down")
        self.assertEqual(self.batch(boom, dec()), {})
        self.assertEqual(self.batch(lambda it, data, log=None: ["not", "a", "dict"], dec()), {})

    def test_per_hit_api_fallback(self):
        calls = []

        def review(d, profile, res, alert, data):
            calls.append(d.hit_id)
            return to_review(d)
        main.crossexam = types.SimpleNamespace(review=review)
        out = main.cross_examine_all(items(dec("H-1"), dec("H-2", "SAME_ENTITY", "NAME_DOB_MATCH")), None)
        self.assertEqual(sorted(out), ["H-1"])
        self.assertEqual(calls, ["H-1"])  # only clearances are sent


if __name__ == "__main__":
    unittest.main()
