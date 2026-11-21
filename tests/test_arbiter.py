"""arbiter.py + llm_judge.py + main's guard, with a stubbed engine.llm. Made-up IDs only; no network."""
from __future__ import annotations

import json
import os
import re
import sys
import unittest
from dataclasses import replace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "system"))

import main  # noqa: E402
from engine import arbiter, llm_judge  # noqa: E402
from engine.model import Decision, Fact, HitProfile, PartialDate, Person, Resolution  # noqa: E402

DIFF, SAME, REVIEW = "DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW"


def det(decision=DIFF, code="LOCATION_MISMATCH", hid="H-T1"):
    return Decision(hit_id=hid, alert_id="A-T1", decision=decision, reason_code=code, customer_record_id="CUS-T1",
                    reason="The customer is tied to Freedonia (CUS-T1). The hit is tied only to Sylvania.",
                    evidence=["CUS-T1"])


def view(decision, code, ev=()):
    return {"decision": decision, "reason_code": code, "compared": [], "evidence_ids": list(ev)}


def screen(error_in, missed=()):
    return {"error_in": error_in, "explanation": "The note shows a shared country. Really.",
            "significant_missed_facts": [{"fact": "lived in Sylvania", "evidence_ids": list(missed)}]}


def sentences(t):
    return len(re.findall(r"[.!?](?=\s|$)", t))


class ResolveOne(unittest.TestCase):
    def check(self, final, decision, code):
        self.assertEqual((final.decision, final.reason_code), (decision, code), final.reason)
        self.assertIn(final.reason_code, llm_judge.CODES[final.decision])
        self.assertTrue(2 <= sentences(final.reason) <= 4, final.reason)

    def test_agree_keeps_line_unchanged(self):
        d = det()
        final, path = arbiter.resolve_one(d, view(DIFF, "DOB_MISMATCH"), None)
        self.assertIs(final, d)
        self.assertEqual(path, "agree")

    def test_no_llm_view_keeps_rules(self):
        d = det(SAME, "NAME_DOB_MATCH")
        self.assertIs(arbiter.resolve_one(d, None, None)[0], d)

    def test_error_in_llm_keeps_rules(self):
        final, path = arbiter.resolve_one(det(), view(SAME, "NAME_DOB_MATCH"), screen("llm"))
        self.check(final, DIFF, "LOCATION_MISMATCH")
        self.assertIn("Grok", final.reason)

    def test_error_in_rules_takes_llm_same_or_review(self):
        final, _ = arbiter.resolve_one(det(), view(SAME, "NAME_DOB_MATCH", ["NOTE-T1"]), screen("deterministic", ["NOTE-T1", "H-T1"]))
        self.check(final, SAME, "NAME_DOB_MATCH")
        self.assertEqual(final.evidence, ["CUS-T1", "NOTE-T1"])  # H- never cited
        final, _ = arbiter.resolve_one(det(), view(REVIEW, "INSUFFICIENT_DATA"), screen("deterministic"))
        self.check(final, REVIEW, "INSUFFICIENT_DATA")

    def test_llm_can_never_create_a_clearance(self):
        for rules in (det(SAME, "NAME_DOB_MATCH"), det(REVIEW, "INSUFFICIENT_DATA")):
            for s in (screen("deterministic"), screen("neither"), screen("both"), screen("llm"), None):
                final, _ = arbiter.resolve_one(rules, view(DIFF, "DOB_MISMATCH"), s)
                self.assertNotEqual(final.decision, DIFF, (rules.decision, s))

    def test_neither_both_or_failure_go_to_review(self):
        for s in (screen("neither"), screen("both"), None):
            final, _ = arbiter.resolve_one(det(), view(SAME, "NAME_DOB_MATCH"), s)
            self.check(final, REVIEW, "INSUFFICIENT_DATA")


class StubLLM:
    """Answers the judge with `judge_answer` and the screener with `screen_answer`."""
    STATS = {}

    def __init__(self, judge_answer, screen_answer):
        self.j, self.s, self.calls = judge_answer, screen_answer, []

    def available(self):
        return True

    def ask_json(self, system, user, schema, name="answer", timeout=45.0):
        self.calls.append(name)
        return self.j if name == "llm_judge" else self.s


def item(d):
    person = Person(person_id="CUS-T1", record_ids=["CUS-T1"], entity_type="Individual",
                    names=[Fact("Pat Testman", "CUS-T1")], dobs=[Fact(PartialDate(1980, 5, 2), "CUS-T1")],
                    countries=[Fact("Freedonia", "CUS-T1")])
    prof = HitProfile(hit_id=d.hit_id, alert_id="A-T1", entity_type="Individual", names=[Fact("Pat Testman", d.hit_id)])
    return (d, prof, Resolution(people=[person]), {"alert_id": "A-T1", "customer_name": "Pat Testman"})


class ReviewAll(unittest.TestCase):
    def setUp(self):
        self._a, self._j = arbiter.llm, llm_judge.llm

    def tearDown(self):
        arbiter.llm, llm_judge.llm = self._a, self._j

    def stub(self, j, s):
        arbiter.llm = llm_judge.llm = StubLLM(j, s)
        return arbiter.llm

    def test_no_key_returns_nothing(self):
        class Off:
            STATS = {}

            def available(self):
                return False
        arbiter.llm = llm_judge.llm = Off()
        self.assertEqual(arbiter.review_all([item(det())], None), {})

    def test_agreement_changes_nothing_and_no_screener_call(self):
        st = self.stub(view(DIFF, "LOCATION_MISMATCH"), None)
        self.assertEqual(arbiter.review_all([item(det())], None), {})
        self.assertEqual(st.calls, ["llm_judge"])
        self.assertEqual(arbiter.trace("H-T1")["path"], "agree")

    def test_disagreement_screened_and_traced(self):
        st = self.stub(view(SAME, "NAME_DOB_MATCH", ["CUS-T1", "KYC-INVENTED"]), screen("deterministic"))
        out = arbiter.review_all([item(det())], None)
        self.assertEqual(out["H-T1"].decision, SAME)
        self.assertEqual(st.calls, ["llm_judge", "screening_agent"])
        t = arbiter.trace("H-T1")
        self.assertEqual(t["path"], "error_in_rules_take_llm")
        self.assertEqual(t["llm"]["evidence_ids"], ["CUS-T1"])  # invented ID dropped
        self.assertEqual(t["final"], {"decision": SAME, "reason_code": "NAME_DOB_MATCH"})

    def test_invalid_llm_answer_is_ignored(self):
        self.stub({"decision": SAME, "reason_code": "DOB_MISMATCH", "compared": [], "evidence_ids": []}, None)
        self.assertEqual(arbiter.review_all([item(det())], None), {})
        self.assertEqual(arbiter.trace("H-T1")["path"], "llm_unavailable")


class MainGuard(unittest.TestCase):
    def test_guard_blocks_new_clearances_and_bad_codes(self):
        same, rev, clr = det(SAME, "NAME_DOB_MATCH"), det(REVIEW, "INSUFFICIENT_DATA"), det()
        self.assertFalse(main._arbiter_ok(same, replace(same, decision=DIFF, reason_code="DOB_MISMATCH")))
        self.assertFalse(main._arbiter_ok(rev, replace(rev, decision=DIFF, reason_code="DOB_MISMATCH")))
        self.assertFalse(main._arbiter_ok(clr, replace(clr, reason_code="DOB_MISMATCH")))  # a different clearance
        self.assertFalse(main._arbiter_ok(clr, replace(clr, decision=SAME, reason_code="DOB_MISMATCH")))
        self.assertFalse(main._arbiter_ok(clr, replace(clr, hit_id="H-OTHER", decision=REVIEW, reason_code="INSUFFICIENT_DATA")))
        self.assertTrue(main._arbiter_ok(clr, replace(clr, decision=REVIEW, reason_code="INSUFFICIENT_DATA")))
        self.assertTrue(main._arbiter_ok(clr, replace(clr, reason="new reason. two.")))
        self.assertTrue(main._arbiter_ok(rev, replace(rev, decision=SAME, reason_code="NAME_DOB_MATCH")))

    def test_case_has_only_supplied_ids_allowed(self):
        d, prof, res, alert = item(det())
        case = llm_judge.build_case(d, prof, res, alert, None)
        self.assertEqual(case["allowed_ids"], ["A-T1", "CUS-T1", "H-T1"])
        json.dumps(case)  # serialisable


if __name__ == "__main__":
    unittest.main()
