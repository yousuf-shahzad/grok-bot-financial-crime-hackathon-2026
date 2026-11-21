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


CITED = [{"fact": "a supplied record shows it", "evidence_ids": ["CUS-T1"]}]


def screen(error_in, missed=("CUS-T1",)):
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


class UncitedScreener(unittest.TestCase):
    """Lead's rule: siding against the rules (or calling it unsettled) needs a cited supplied record."""
    def test_uncited_blame_keeps_rules(self):
        d = det()
        for e in ("deterministic", "neither", "both"):
            final, path = arbiter.resolve_one(d, view(SAME, "NAME_DOB_MATCH"), screen(e, missed=()))
            self.assertEqual((final.decision, final.reason_code), (d.decision, d.reason_code), e)
            self.assertEqual(path, "uncited_keep_rules")
            self.assertTrue(2 <= sentences(final.reason) <= 4, final.reason)

    def test_uncited_never_creates_a_clearance(self):
        for rules in (det(SAME, "NAME_DOB_MATCH"), det(REVIEW, "INSUFFICIENT_DATA")):
            for e in ("deterministic", "neither", "both"):
                final, _ = arbiter.resolve_one(rules, view(DIFF, "DOB_MISMATCH"), screen(e, missed=()))
                self.assertEqual(final.decision, rules.decision)

    def test_hit_or_account_ids_do_not_count_as_cited(self):
        d = det()
        final, path = arbiter.resolve_one(d, view(SAME, "NAME_DOB_MATCH"), screen("deterministic", missed=("H-T1", "ACC-T1")))
        self.assertEqual(path, "uncited_keep_rules")


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
        self.assertEqual(out["H-T1"].decision, DIFF)
        self.assertEqual(st.calls, ["llm_judge", "screening_agent"])
        t = arbiter.trace("H-T1")
        # The only cited id is already in the rules' evidence, so the rules line stands.
        self.assertEqual(t["path"], "error_in_llm_keep_rules")
        self.assertEqual(t["guard"], "no_new_cited_record")
        self.assertEqual(t["llm"]["evidence_ids"], ["CUS-T1"])  # invented ID dropped
        self.assertEqual(t["final"]["decision"], DIFF)

    def test_review_all_drops_ids_the_case_did_not_supply(self):
        d = det()
        d.evidence = ["CUS-T1", "H-T1", "GHOST-1"]
        self.stub(view(SAME, "NAME_DOB_MATCH"), screen("deterministic"))
        out = arbiter.review_all([item(d)], None)
        self.assertEqual(out["H-T1"].evidence, ["CUS-T1"])

    def test_invalid_llm_answer_is_ignored(self):
        self.stub({"decision": SAME, "reason_code": "DOB_MISMATCH", "compared": [], "evidence_ids": []}, None)
        self.assertEqual(arbiter.review_all([item(det())], None), {})
        self.assertEqual(arbiter.trace("H-T1")["path"], "llm_unavailable")


class ResolveContract(unittest.TestCase):
    """arbiter.resolve(det, llm, case) -> (Decision, trace), the lead's single-hit contract."""
    def setUp(self):
        self._a = arbiter.llm

    def tearDown(self):
        arbiter.llm = self._a

    def test_agree_no_screen_call(self):
        arbiter.llm = StubLLM(None, None)
        d = det()
        final, tr = arbiter.resolve(d, view(DIFF, "DOB_MISMATCH"), {"allowed_ids": []})
        self.assertIs(final, d)
        self.assertEqual(arbiter.llm.calls, [])
        self.assertEqual(set(tr), {"deterministic", "llm", "screener", "final", "path"})

    def test_screener_exception_goes_to_review(self):
        class Boom(StubLLM):
            def ask_json(self, *a, **k):
                raise RuntimeError("down")
        arbiter.llm = Boom(None, None)
        final, tr = arbiter.resolve(det(), view(SAME, "NAME_DOB_MATCH"), {"allowed_ids": []})
        self.assertEqual((final.decision, final.reason_code), (REVIEW, "INSUFFICIENT_DATA"))
        self.assertIsNone(tr["screener"])


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


class ContractGaps(unittest.TestCase):
    """Lead's single-hit rules, with ask_json stubbed. Invented IDs only."""

    def setUp(self):
        self._llm = arbiter.llm
        self.calls = []

    def tearDown(self):
        arbiter.llm = self._llm

    def _stub(self, answer):
        calls = self.calls

        class Stub:
            STATS = {}

            def available(self):
                return True

            def ask_json(self, system, user, schema, name="answer", timeout=45.0):
                calls.append({"name": name, "timeout": timeout})
                if isinstance(answer, Exception):
                    raise answer
                return answer

        arbiter.llm = Stub()

    def case(self, *ids):
        return {"allowed_ids": list(ids), "alert_id": "A-T1",
                "screened": {}, "hit": {}, "customers": [], "note": ""}

    def test_agreement_makes_no_call(self):
        self._stub({"error_in": "llm", "significant_missed_facts": [], "explanation": "no"})
        d = det()
        final, tr = arbiter.resolve(d, view(DIFF, "LOCATION_MISMATCH"), self.case("CUS-T1"))
        self.assertIs(final, d)
        self.assertEqual(self.calls, [])
        self.assertIn("path", tr)

    def test_each_error_in_with_decision_pairs(self):
        pairs = [
            ("llm", DIFF, "LOCATION_MISMATCH", SAME, "NAME_DOB_MATCH", DIFF, "LOCATION_MISMATCH"),
            ("llm", REVIEW, "INSUFFICIENT_DATA", DIFF, "DOB_MISMATCH", REVIEW, "INSUFFICIENT_DATA"),
            # CUS-T1 is already in the rules' evidence, so blaming the rules does not overrule them.
            ("deterministic", DIFF, "DOB_MISMATCH", SAME, "NAME_DOB_MATCH", DIFF, "DOB_MISMATCH"),
            ("deterministic", SAME, "NAME_DOB_MATCH", REVIEW, "AMBIGUOUS_CUSTOMER_RECORD", SAME, "NAME_DOB_MATCH"),
            ("deterministic", SAME, "NAME_LOCATION_MATCH", DIFF, "DECEASED", SAME, "NAME_LOCATION_MATCH"),
            ("neither", DIFF, "DECEASED", SAME, "NAME_DOB_MATCH", REVIEW, "INSUFFICIENT_DATA"),
            ("both", REVIEW, "INSUFFICIENT_DATA", SAME, "NAME_DOB_LOCATION_MATCH", REVIEW, "INSUFFICIENT_DATA"),
        ]
        for error_in, det_d, det_c, llm_d, llm_c, want_d, want_c in pairs:
            self.calls.clear()
            self._stub({"error_in": error_in, "significant_missed_facts": CITED, "explanation": "Checked both."})
            final, _ = arbiter.resolve(det(det_d, det_c), view(llm_d, llm_c), self.case("CUS-T1"))
            self.assertEqual((final.decision, final.reason_code), (want_d, want_c), error_in)
            self.assertEqual(len(self.calls), 1)
            self.assertIn(final.reason_code, llm_judge.CODES[final.decision])
            if final.decision == DIFF:
                self.assertEqual(det_d, DIFF)

    def test_llm_diff_becomes_review(self):
        self._stub({"error_in": "deterministic", "significant_missed_facts": CITED, "explanation": "Rules missed it."})
        final, tr = arbiter.resolve(det(SAME, "NAME_DOB_MATCH"), view(DIFF, "DOB_MISMATCH"), self.case("CUS-T1"))
        self.assertEqual((final.decision, final.reason_code), (SAME, "NAME_DOB_MATCH"))
        self.assertEqual(tr["guard"], "no_new_cited_record")
        self._stub({"error_in": "deterministic", "significant_missed_facts": [
            {"fact": "a note", "evidence_ids": ["NOTE-T9"]}], "explanation": "A new note."})
        final, _ = arbiter.resolve(det(SAME, "NAME_DOB_MATCH"), view(DIFF, "DOB_MISMATCH"),
                                   self.case("CUS-T1", "NOTE-T9"))
        self.assertEqual((final.decision, final.reason_code), (REVIEW, "INSUFFICIENT_DATA"))
        # with no supplied record cited, the rules' SAME stands (still never a clearance)
        final, _ = arbiter.resolve(det(SAME, "NAME_DOB_MATCH"), view(DIFF, "DOB_MISMATCH"), self.case())
        self.assertEqual(final.decision, SAME)

    def test_bad_screener_answers_review(self):
        for answer in (RuntimeError("timeout"), {"error_in": "unsure"}, "not-json", None, []):
            self._stub(answer)
            final, tr = arbiter.resolve(det(), view(SAME, "NAME_DOB_MATCH"), self.case("CUS-T1"))
            self.assertEqual((final.decision, final.reason_code), (REVIEW, "INSUFFICIENT_DATA"), answer)
            self.assertIsNone(tr["screener"])

    def test_fake_and_hit_ids_are_filtered(self):
        self._stub({"error_in": "deterministic", "significant_missed_facts": [
            {"fact": "a note", "evidence_ids": ["NOTE-T9", "H-NO", "ACC-NO", "KYC-MADE-UP"]}],
                    "explanation": "A note was missed."})
        rules = det()
        rules.evidence = ["CUS-T1", "H-T1", "ACC-T1", "GHOST-1"]
        final, _ = arbiter.resolve(rules, view(SAME, "NAME_DOB_MATCH", ["KYC-MADE-UP"]),
                                   self.case("CUS-T1", "NOTE-T9", "H-T1"))
        self.assertEqual(final.evidence, ["CUS-T1", "NOTE-T9"])
        self.assertNotIn("H-T1", final.evidence)
        self.assertNotIn("KYC-MADE-UP", final.evidence)

    def test_bad_llm_code_is_no_second_view(self):
        # same rule as llm_judge.judge(): a reason code that does not belong to the decision (or is
        # missing) makes the LLM answer invalid, so the rules' line stands and no screener is called
        self._stub({"error_in": "deterministic", "significant_missed_facts": [], "explanation": "Take the review."})
        d = det()
        for bad in (view(SAME, "DOB_MISMATCH"), {"decision": SAME, "compared": [], "evidence_ids": []}):
            self.calls.clear()
            final, tr = arbiter.resolve(d, bad, self.case("CUS-T1", "NOTE-T9"))
            self.assertIs(final, d)
            self.assertEqual(tr["path"], "llm_unavailable")
            self.assertEqual(self.calls, [])
            self.assertEqual(final.evidence, ["CUS-T1"])

    def test_screen_failed_flag_reviews(self):
        final, path = arbiter.resolve_one(det(), view(SAME, "NAME_DOB_MATCH"), screen("llm"), screen_failed=True)
        self.assertEqual((final.decision, final.reason_code, path), (REVIEW, "INSUFFICIENT_DATA", "screen_failed"))

    def test_unknown_error_in_is_a_screener_failure(self):
        final, path = arbiter.resolve_one(
            det(), view(SAME, "NAME_DOB_MATCH"),
            {"error_in": "unsure", "significant_missed_facts": [], "explanation": "no"})
        self.assertEqual((final.decision, final.reason_code, path), (REVIEW, "INSUFFICIENT_DATA", "screen_failed"))

    def test_screener_explanation_ids_are_scrubbed(self):
        self._stub({"error_in": "deterministic", "significant_missed_facts": CITED,
                    "explanation": "Note NOTE-T9 agrees, but H-NO and ACC-NO and KYC-BAD do not."})
        final, _ = arbiter.resolve(det(), view(SAME, "NAME_DOB_MATCH"), self.case("NOTE-T9", "CUS-T1"))
        self.assertIn("NOTE-T9", final.reason)
        self.assertIn("a record", final.reason)
        self.assertNotIn("H-NO", final.reason)
        self.assertNotIn("ACC-NO", final.reason)
        self.assertNotIn("KYC-BAD", final.reason)
        self.assertTrue(2 <= sentences(final.reason) <= 4, final.reason)

    def test_screener_explanation_stays_within_four_sentences(self):
        expl = " ".join("Sentence %d mentions KYC-BAD." % i for i in range(1, 9))
        self._stub({"error_in": "deterministic", "significant_missed_facts": CITED, "explanation": expl})
        final, _ = arbiter.resolve(det(), view(SAME, "NAME_DOB_MATCH"), self.case("CUS-T1"))
        self.assertTrue(2 <= sentences(final.reason) <= 4, final.reason)
        self.assertNotIn("KYC-BAD", final.reason)
        self.assertNotIn("Sentence 8", final.reason)
        self.assertIn("Sentence 1", final.reason)

    def test_disable_keeps_rules_output(self):
        os.environ["LLM_DISABLE"] = "1"
        try:
            self.assertFalse(arbiter.llm.available())
            d = det()
            self.assertEqual(arbiter.review_all([item(d)], None), {})
            self.assertEqual(main.arbitrate_all([d], [item(d)], None), {})
        finally:
            os.environ.pop("LLM_DISABLE", None)


def _fact(value, source, kind=""):
    return {"value": value, "source": source, "kind": kind}


def person_case(entity="Individual", verified="ADA EXAMPLE", hit_name="Ada Example", dob=True, country=True):
    """Invented customer and hit. dob/country can be turned off to test the SAME guard."""
    person = {
        "person_id": "CUS-T1", "record_ids": ["CUS-T1"], "entity_type": entity,
        "names": [_fact(hit_name, "CUS-T1", "full_name")],
        "verified_name": _fact(verified, "KYC-T1", "verified_name") if verified else None,
        "dobs": [],
        "verified_dob": _fact("1970-03-12", "KYC-T1", "verified_dob") if dob else None,
        "countries": [_fact("Freedonia", "CUS-T1", "residence")] if country else [],
    }
    hit = {
        "hit_id": "H-T1", "entity_type": entity,
        "names": [_fact(hit_name, "H-T1", "listed")],
        "births": [{"years": [1970], "month": 3, "day": 12, "source": "H-T1"}] if dob else [],
        "countries": [_fact("Freedonia", "H-T1", "country")] if country else [],
    }
    return {"allowed_ids": ["CUS-T1", "NOTE-T9", "KYC-T1", "H-T1", "A-T1"],
            "alert_id": "A-T1", "screened": {}, "hit": hit, "customers": [person], "note": ""}


class GuardRules(unittest.TestCase):
    """Stubbed screener. A deterministic blame needs a new supplied id; SAME needs the matchers."""

    def setUp(self):
        self._llm = arbiter.llm
        self.calls = []

    def tearDown(self):
        arbiter.llm = self._llm

    def stub(self, missed):
        calls = self.calls

        class Stub:
            STATS = {}

            def available(self):
                return True

            def ask_json(self, system, user, schema, name="answer", timeout=45.0):
                calls.append(name)
                return {"error_in": "deterministic", "explanation": "A supplied note was missed.",
                        "significant_missed_facts": [{"fact": "a note", "evidence_ids": list(missed)}]}

        arbiter.llm = Stub()

    def test_prompt_states_the_four_rules(self):
        text = arbiter.SCREEN_PROMPT
        self.assertIn("case['rules']", text)
        self.assertIn("location_exception_applies", text)
        self.assertIn("name AND the date of birth BOTH agree", text)
        self.assertIn("unknown on either side", text)
        self.assertIn("For a company: name AND country", text)
        self.assertIn("UNKNOWN IS NEVER AGREEMENT", text)
        self.assertIn("table stands unless a cited supplied record", text)

    def test_uncited_already_cited_and_newly_cited(self):
        rules = det()
        agreed = person_case()
        self.stub(())
        final, tr = arbiter.resolve(rules, view(REVIEW, "INSUFFICIENT_DATA"), agreed)
        self.assertEqual(final.decision, DIFF)
        self.assertEqual(tr["guard"], "no_new_cited_record")
        self.calls.clear()
        self.stub(("CUS-T1",))
        final, tr = arbiter.resolve(rules, view(REVIEW, "INSUFFICIENT_DATA"), agreed)
        self.assertEqual(final.decision, DIFF)
        self.assertEqual(tr["guard"], "no_new_cited_record")
        self.calls.clear()
        self.stub(("H-T1", "ACC-T1", "KYC-MADE-UP"))
        final, tr = arbiter.resolve(rules, view(REVIEW, "INSUFFICIENT_DATA"), agreed)
        self.assertEqual(final.decision, DIFF)
        self.assertEqual(tr["guard"], "no_new_cited_record")
        self.calls.clear()
        self.stub(("NOTE-T9",))
        final, tr = arbiter.resolve(rules, view(REVIEW, "INSUFFICIENT_DATA"), agreed)
        self.assertEqual((final.decision, final.reason_code), (REVIEW, "INSUFFICIENT_DATA"))
        self.assertNotIn("guard", tr)

    def test_same_needs_name_and_dob_for_a_person(self):
        self.stub(("NOTE-T9",))
        final, tr = arbiter.resolve(det(), view(SAME, "NAME_DOB_MATCH"), person_case(dob=False))
        self.assertEqual(final.decision, DIFF)
        self.assertEqual(tr["guard"], "same_without_name_and_dob")
        final, tr = arbiter.resolve(det(), view(SAME, "NAME_DOB_MATCH"), person_case())
        self.assertEqual((final.decision, final.reason_code), (SAME, "NAME_DOB_MATCH"))
        self.assertNotIn("guard", tr)
        one = person_case(verified="ADA", hit_name="Ada")
        final, tr = arbiter.resolve(det(), view(SAME, "NAME_DOB_MATCH"), one)
        self.assertEqual(final.decision, DIFF)
        self.assertEqual(tr["guard"], "same_without_name_and_dob")

    def test_company_same_needs_name_and_country(self):
        self.stub(("NOTE-T9",))
        final, tr = arbiter.resolve(det(), view(SAME, "NAME_LOCATION_MATCH"),
                                    person_case(entity="Company", verified=None, hit_name="Acme Widgets",
                                                dob=False, country=False))
        self.assertEqual(final.decision, DIFF)
        self.assertEqual(tr["guard"], "same_without_name_and_dob")
        final, tr = arbiter.resolve(det(), view(SAME, "NAME_LOCATION_MATCH"),
                                    person_case(entity="Company", verified=None, hit_name="Acme Widgets", dob=False))
        self.assertEqual((final.decision, final.reason_code), (SAME, "NAME_LOCATION_MATCH"))
        self.assertNotIn("guard", tr)


if __name__ == "__main__":
    unittest.main()
