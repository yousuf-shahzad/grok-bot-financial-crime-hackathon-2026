"""Safety tests for the dual decision path (rules engine vs LLM judge + screening agent).

Lead's board item 2, written against the contract
    arbiter.resolve(det: Decision, llm: dict, case: dict) -> (Decision, trace)
and the batch path main.arbitrate_all -> arbiter.review_all -> main._arbiter_ok (PR #56):
  (a) the LLM can never create a clearance (DIFFERENT_ENTITY), whatever the judge and screener say;
  (b) the full disagreement table: det decision x llm decision x screener error_in -> final;
  (c) no key / LLM_DISABLE=1 -> output byte-identical to rules only (tests/fixtures/rare);
  (d) judge or screener exceptions, or malformed JSON -> REVIEW (or the rules line kept), never a crash.

Invented IDs and values only. The LLM is stubbed: no network, no key. Every real network call is
blocked (urllib.request.urlopen raises). Classes that need engine.arbiter / engine.llm_judge skip
cleanly when they are not on this branch (PR #56 not merged); the no-key checks (c) run everywhere.

Two LLM-failure behaviours are pinned, as in PR #56: a JUDGE failure means "no second view" (the
rules line is kept), a SCREENER failure means REVIEW / INSUFFICIENT_DATA. The clearance safety
assertions hold either way.
"""
from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import urllib.request
from dataclasses import replace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SYSTEM = os.path.join(ROOT, "system")
FIXTURE = os.path.join(HERE, "fixtures", "rare")
MAIN = os.path.join(SYSTEM, "main.py")
RUN = os.path.join(SYSTEM, "run")
sys.path.insert(0, SYSTEM)

import main  # noqa: E402
from engine import llm  # noqa: E402
from engine.model import Decision, Fact, HitProfile, PartialDate, Person, Resolution  # noqa: E402

try:
    from engine import arbiter, llm_judge  # noqa: E402
    HAVE_DUAL = all(hasattr(arbiter, n) for n in ("resolve", "resolve_one", "review_all")) and \
        hasattr(llm_judge, "judge") and hasattr(main, "arbitrate_all")
except Exception:  # noqa: BLE001
    arbiter = llm_judge = None
    HAVE_DUAL = False
SKIP = "engine.arbiter / engine.llm_judge not on this branch (PR #56, D-dual-path, not merged yet)"

DIFF, SAME, REVIEW = "DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW"
DECISIONS = (DIFF, SAME, REVIEW)
CODES = {
    DIFF: ("TEMPORAL_IMPOSSIBILITY", "DOB_MISMATCH", "LOCATION_MISMATCH", "NAME_MISMATCH_VERIFIED",
           "ENTITY_TYPE_MISMATCH", "DECEASED"),
    SAME: ("NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH", "NAME_LOCATION_MATCH"),
    REVIEW: ("INSUFFICIENT_DATA", "AMBIGUOUS_CUSTOMER_RECORD"),
}
PAIRS = [(d, c) for d in DECISIONS for c in CODES[d]]
DEFAULT_CODE = {DIFF: "LOCATION_MISMATCH", SAME: "NAME_DOB_MATCH", REVIEW: "INSUFFICIENT_DATA"}
ERROR_IN = ("deterministic", "llm", "neither", "both")
NO_CITE = ("H-", "ACC-")

# ---------------------------------------------------------------- invented fixtures
HID, AID, CID = "H-ZZ901", "A-ZZ901", "CUS-ZZ901"
NOTE, KYC, ACC = "NOTE-ZZ901", "KYC-ZZ901", "ACC-ZZ901"
FAKE = "KYC-ZZ999"  # never supplied: must never be cited


def _f(value, source, kind="declared"):
    return {"value": value, "source": source, "kind": kind}


CASE = {
    "alert_id": AID,
    "screened": {"customer_name": "Quill Examplar", "entity_type": "Individual", "dob": "1977-03-04",
                 "country": "Ruritania", "city": "Strelsau", "screened_at": "2026-01-02"},
    "hit": {"hit_id": HID, "entity_type": "Individual", "listing_kind": "sanctions",
            "names": [_f("Quill Examplar", HID, "listed")],
            "births": [{"years": [1977], "month": 3, "day": None, "source": HID}],
            "countries": [_f("Freedonia", HID, "listed")], "earliest_report": None, "deceased": None,
            "incorporated": None, "missing": [],
            "texts": [{"id": HID, "kind": "hit profile (first paragraph) and listed dates of birth",
                       "text": "Invented profile: a trader from Freedonia, born March 1977."}]},
    "customers": [{"person_id": CID, "record_ids": [CID], "entity_type": "Individual",
                   "names": [_f("Quill Examplar", CID)], "verified_name": _f("Quill Examplar", KYC, "verified"),
                   "dobs": [_f("1977-03-04", CID)], "verified_dob": _f("1977-03-04", KYC, "verified"),
                   "countries": [_f("Ruritania", CID)],
                   "texts": [{"id": KYC, "kind": "KYC check", "text": "{\"result\": \"approved\"}"},
                             {"id": NOTE, "kind": "customer note (email)",
                              "text": "Invented note: I lived in Freedonia until 2010."}]}],
    "note": "",
    # H- and ACC- IDs are supplied but must still never be cited
    "allowed_ids": sorted([AID, ACC, CID, HID, KYC, NOTE]),
}


def det(decision=DIFF, code=None, hid=HID):
    return Decision(hit_id=hid, alert_id=AID, decision=decision, reason_code=code or DEFAULT_CODE[decision],
                    customer_record_id=CID,
                    reason="The customer is tied to Ruritania (%s). The hit is tied only to Freedonia." % CID,
                    evidence=[CID])


def view(decision, code=None, ev=()):
    return {"decision": decision, "reason_code": code or DEFAULT_CODE[decision],
            "compared": [{"field": "country", "customer": "Ruritania", "hit": "Freedonia", "verdict": "contradict"}],
            "evidence_ids": list(ev)}


def screen_answer(error_in, missed=(NOTE, HID, ACC, FAKE)):
    """A raw screening-agent answer, as ask_json would return it."""
    return {"error_in": error_in, "explanation": "The invented note was missed. It changes the picture.",
            "significant_missed_facts": [{"fact": "Invented: lived in Freedonia", "evidence_ids": list(missed)}]}


def expected(det_decision, llm_decision, error_in, cited=True):
    """The lead's HARD rules, as a table. cited: the screener cites a supplied record. Without one it
    may not side against the rules or call it unsettled: the rules' line stands (lead, 7064805375)."""
    if llm_decision == det_decision or error_in == "llm":
        return det_decision
    if not cited and error_in in ("deterministic", "neither", "both"):
        return det_decision
    if error_in == "deterministic" and llm_decision in (SAME, REVIEW):
        return llm_decision
    return REVIEW


def sentences(text):
    return len(re.findall(r"[.!?](?=\s|$)", text or ""))


class StubLLM:
    """Stands in for engine.llm. `judge` / `screen`: an answer, an Exception to raise, or a callable."""
    STATS: dict = {}

    def __init__(self, judge=None, screen=None, available=True):
        self.j, self.s, self.on, self.calls = judge, screen, available, []

    def available(self):
        return self.on

    def describe(self):
        return "stub"

    def ask_json(self, system, user, schema, name="answer", timeout=45.0):
        self.calls.append(name)
        ans = self.j if name == "llm_judge" else self.s
        if isinstance(ans, BaseException):
            raise ans
        return ans(user) if callable(ans) else json.loads(json.dumps(ans))


def _no_network(*a, **k):
    raise AssertionError("network call attempted in an offline test")


class Offline(unittest.TestCase):
    """Blocks the network and restores every patched module attribute."""

    def setUp(self):
        self._urlopen = urllib.request.urlopen
        urllib.request.urlopen = _no_network
        self._saved = []
        self.patch(main, "log", lambda msg: None)  # keep the test output quiet
        self._dual_mode = os.environ.get("DUAL_MODE")
        os.environ["DUAL_MODE"] = "enforce"  # these tests check the path that can change a line

    def patch(self, obj, name, value):
        self._saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def tearDown(self):
        for obj, name, value in reversed(self._saved):
            setattr(obj, name, value)
        urllib.request.urlopen = self._urlopen
        if self._dual_mode is None:
            os.environ.pop("DUAL_MODE", None)
        else:
            os.environ["DUAL_MODE"] = self._dual_mode

    def stub(self, judge=None, screen=None, available=True):
        st = StubLLM(judge, screen, available)
        self.patch(arbiter, "llm", st)
        self.patch(llm_judge, "llm", st)
        return st

    # shared line checks
    def check_line(self, final, d, case=CASE, llm_view=None):
        self.assertIsInstance(final, Decision)
        self.assertEqual((final.hit_id, final.alert_id), (d.hit_id, d.alert_id))
        self.assertIn(final.decision, CODES)
        self.assertIn(final.reason_code, CODES[final.decision], final)
        # (a) a final DIFFERENT_ENTITY may only come from det, with det's own code
        if final.decision == DIFF:
            self.assertEqual((d.decision, d.reason_code), (DIFF, final.reason_code), final.reason)
        allowed = set(d.evidence) | set((case or {}).get("allowed_ids") or [])
        for i in final.evidence:
            self.assertFalse(i.startswith(NO_CITE), (i, final.evidence))
            self.assertIn(i, allowed, final.evidence)
        self.assertTrue(set(d.evidence) <= set(final.evidence), final.evidence)
        if final is not d:
            self.assertTrue(2 <= sentences(final.reason) <= 4, final.reason)
            if llm_view is not None:  # names both views
                low = final.reason.lower().replace("_", " ")
                self.assertIn("rules", low)
                for dec in (d.decision, llm_view["decision"]):
                    self.assertIn(dec.lower().replace("_", " "), low, final.reason)


def item(d):
    person = Person(person_id=CID, record_ids=[CID], entity_type="Individual",
                    names=[Fact("Quill Examplar", CID)], dobs=[Fact(PartialDate(1977, 3, 4), CID)],
                    countries=[Fact("Ruritania", CID)])
    prof = HitProfile(hit_id=d.hit_id, alert_id=AID, entity_type="Individual",
                      names=[Fact("Quill Examplar", d.hit_id)], countries=[Fact("Freedonia", d.hit_id)])
    return (d, prof, Resolution(people=[person]), {"alert_id": AID, "customer_name": "Quill Examplar"})



def _has_dual_mode():
    """True once DUAL_MODE is implemented in main.py or engine/arbiter.py."""
    for rel in ("main.py", os.path.join("engine", "arbiter.py")):
        try:
            with open(os.path.join(SYSTEM, rel), encoding="utf-8") as f:
                if "DUAL_MODE" in f.read():
                    return True
        except OSError:
            pass
    return False


def _lines(path):
    with open(path, encoding="utf-8") as f:
        return {d["hit_id"]: d for d in (json.loads(x) for x in f if x.strip())}


# ======================================================================= (b) the table
@unittest.skipUnless(HAVE_DUAL, SKIP)
class DisagreementTable(Offline):
    def test_codes_match_the_engine(self):
        self.assertEqual({k: tuple(v) for k, v in llm_judge.CODES.items()}, CODES)

    def test_full_table_via_resolve(self):
        n = 0
        for det_dec, llm_dec, err in itertools.product(DECISIONS, DECISIONS, ERROR_IN):
            with self.subTest(det=det_dec, llm=llm_dec, error_in=err):
                st = self.stub(screen=screen_answer(err))
                d, v = det(det_dec), view(llm_dec, ev=[NOTE])
                final, tr = arbiter.resolve(d, v, CASE)
                want = expected(det_dec, llm_dec, err)
                self.assertEqual(final.decision, want)
                self.check_line(final, d, llm_view=v)
                self.assertTrue({"deterministic", "llm", "screener", "final"} <= set(tr))
                self.assertEqual(tr["deterministic"]["decision"], det_dec)
                self.assertEqual(tr["final"], {"decision": final.decision, "reason_code": final.reason_code})
                if llm_dec == det_dec:
                    self.assertIs(final, d)  # agreement: unchanged, and no screening call
                    self.assertEqual(st.calls, [])
                    continue
                self.assertEqual(st.calls, ["screening_agent"])  # exactly ONE screening call
                self.assertEqual(tr["screener"]["error_in"], err)
                self.assertIn(NOTE, final.evidence)  # the screener's missed ID is cited
                self.assertNotIn(FAKE, final.evidence)
                if want == det_dec:
                    self.assertEqual(final.reason_code, d.reason_code)
                elif want == llm_dec:
                    self.assertEqual(final.reason_code, v["reason_code"])
                else:
                    self.assertEqual(final.reason_code, "INSUFFICIENT_DATA")
                n += 1
        self.assertEqual(n, 3 * 2 * 4)

    def test_error_in_deterministic_takes_every_same_or_review_code(self):
        for det_dec in DECISIONS:
            for llm_dec, code in PAIRS:
                if llm_dec == det_dec:
                    continue
                with self.subTest(det=det_dec, llm=code):
                    self.stub(screen=screen_answer("deterministic"))
                    d, v = det(det_dec), view(llm_dec, code)
                    final, _ = arbiter.resolve(d, v, CASE)
                    self.check_line(final, d, llm_view=v)
                    if llm_dec == DIFF:
                        self.assertEqual((final.decision, final.reason_code), (REVIEW, "INSUFFICIENT_DATA"))
                    else:
                        self.assertEqual((final.decision, final.reason_code), (llm_dec, code))

    def test_full_table_via_main_batch_path(self):
        """main.arbitrate_all -> arbiter.review_all (judge + screener) -> main._arbiter_ok."""
        for det_dec, llm_dec, err in itertools.product(DECISIONS, DECISIONS, ERROR_IN):
            with self.subTest(det=det_dec, llm=llm_dec, error_in=err):
                st = self.stub(judge=view(llm_dec, ev=[CID]), screen=screen_answer(err, missed=(CID, HID, FAKE)))
                d = det(det_dec)
                out = main.arbitrate_all([d], [item(d)], None)
                final = out.get(d.hit_id, d)
                self.assertEqual(final.decision, expected(det_dec, llm_dec, err))
                self.check_line(final, d, case=None, llm_view=view(llm_dec))
                self.assertEqual(st.calls, ["llm_judge"] if llm_dec == det_dec else ["llm_judge", "screening_agent"])
                if llm_dec == det_dec:
                    self.assertNotIn(d.hit_id, out)
                tr = arbiter.trace(d.hit_id)
                self.assertEqual(tr["final"], {"decision": final.decision, "reason_code": final.reason_code})

    def test_deterministic(self):
        self.stub(screen=screen_answer("neither"))
        a = arbiter.resolve(det(SAME), view(REVIEW), CASE)
        b = arbiter.resolve(det(SAME), view(REVIEW), CASE)
        self.assertEqual(a, b)


# ================================================================ (a) never a new clearance
SCREENS = [screen_answer(e) for e in ERROR_IN] + [None, RuntimeError("screener down"), "not json {",
                                                  {"error_in": "rules"}, {}]


@unittest.skipUnless(HAVE_DUAL, SKIP)
class NeverAnLLMClearance(Offline):
    def test_resolve_exhaustive(self):
        """Every det (decision, code) x every LLM (decision, code) x every screener outcome."""
        for (dd, dc), (ld, lc), s in itertools.product(PAIRS, PAIRS, SCREENS):
            with self.subTest(det=dc, llm=lc, screen=repr(s)[:40]):
                self.stub(screen=s)
                d, v = det(dd, dc), view(ld, lc, ev=[NOTE, KYC])
                final, tr = arbiter.resolve(d, v, CASE)
                self.check_line(final, d, llm_view=v)
                if dd != DIFF:
                    self.assertNotEqual(final.decision, DIFF)
                    self.assertNotEqual(tr["final"]["decision"], DIFF)

    def test_resolve_one_exhaustive(self):
        """The pure rules, including screens that bypass _screen's validation."""
        raw = [{"error_in": e, "explanation": "x.", "significant_missed_facts": []} for e in ERROR_IN] + [None]
        for (dd, dc), (ld, lc), s in itertools.product(PAIRS, PAIRS, raw):
            d = det(dd, dc)
            final, _ = arbiter.resolve_one(d, view(ld, lc), s)
            self.check_line(final, d)

    def test_hostile_llm_through_main(self):
        """Judge always clears (every clearance code); screener blames the rules, or anything else."""
        for code in CODES[DIFF]:
            for s in SCREENS:
                for dd, dc in PAIRS:
                    with self.subTest(llm=code, screen=repr(s)[:40], det=dc):
                        self.stub(judge=view(DIFF, code, ev=[CID]), screen=s)
                        d = det(dd, dc)
                        final = main.arbitrate_all([d], [item(d)], None).get(d.hit_id, d)
                        self.check_line(final, d, case=None)

    def test_main_guard_drops_clearances_from_a_broken_arbiter(self):
        """Even if review_all itself misbehaved, main._arbiter_ok refuses any new clearance."""
        decisions = [det(dd, dc, hid="H-ZZ9%02d" % i) for i, (dd, dc) in enumerate(PAIRS)]
        items = [item(d) for d in decisions]

        def evil_review_all(its, data, log=None):
            return {d.hit_id: replace(d, decision=DIFF, reason_code="DECEASED", reason="Cleared. Really.")
                    for d, *_ in its}
        self.patch(main, "arbiter", types.SimpleNamespace(review_all=evil_review_all))
        out = main.arbitrate_all(decisions, items, None)
        for d in decisions:
            final = out.get(d.hit_id, d)
            self.check_line(final, d, case=None)
            if d.decision != DIFF or d.reason_code != "DECEASED":
                self.assertNotIn(d.hit_id, out)

    def test_end_to_end_rare_fixture_with_hostile_llm(self):
        """main.main on the invented rare fixture: no line is a clearance the rules did not make."""
        if not os.path.isdir(FIXTURE):
            self.skipTest("tests/fixtures/rare missing")
        tmp = tempfile.mkdtemp(prefix="dual-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.patch(main, "crossexam", None)
        self.patch(main, "arbiter", None)
        ref = os.path.join(tmp, "rules.jsonl")
        self.assertEqual(main.main(["main.py", FIXTURE, ref]), 0)
        main.arbiter = arbiter
        st = self.stub(judge=view(DIFF, "DOB_MISMATCH"), screen=screen_answer("deterministic"))
        out = os.path.join(tmp, "hostile.jsonl")
        self.assertEqual(main.main(["main.py", FIXTURE, out]), 0)
        self.assertIn("screening_agent", st.calls)
        rules, got = _lines(ref), _lines(out)
        self.assertEqual(set(rules), set(got))
        for hid, line in got.items():
            r = rules[hid]
            if line["decision"] == DIFF:
                self.assertEqual((r["decision"], r["reason_code"]), (DIFF, line["reason_code"]), hid)
            elif (line["decision"], line["reason_code"]) != (r["decision"], r["reason_code"]):
                self.assertEqual(line["decision"], REVIEW, hid)  # a change is never to SAME here

    def test_dual_mode_advisory_is_byte_identical_to_rules_only(self):
        """DUAL_MODE=advisory: a stubbed LLM that disagrees everywhere leaves the output byte-identical."""
        if not os.path.isdir(FIXTURE):
            self.skipTest("tests/fixtures/rare missing")
        if not _has_dual_mode():
            self.skipTest("DUAL_MODE not on this branch yet")
        tmp = tempfile.mkdtemp(prefix="dual-adv-")
        self.addCleanup(shutil.rmtree, tmp, True)
        saved = os.environ.get("DUAL_MODE")
        self.addCleanup(lambda: os.environ.__setitem__("DUAL_MODE", saved) if saved is not None
                        else os.environ.pop("DUAL_MODE", None))
        self.patch(main, "crossexam", None)
        self.patch(main, "arbiter", None)
        ref = os.path.join(tmp, "rules.jsonl")
        os.environ.pop("DUAL_MODE", None)
        self.assertEqual(main.main(["main.py", FIXTURE, ref]), 0)
        with open(ref, "rb") as f:
            want = f.read()
        self.assertTrue(want.strip())
        main.arbiter = arbiter
        os.environ["DUAL_MODE"] = "advisory"
        hostile = [("judge SAME, screener blames rules", view(SAME, "NAME_DOB_MATCH"), screen_answer("deterministic")),
                   ("judge DIFF, screener blames rules", view(DIFF, "DOB_MISMATCH"), screen_answer("deterministic")),
                   ("judge REVIEW, screener blames both", view(REVIEW, "INSUFFICIENT_DATA"), screen_answer("both"))]
        for label, j, sc in hostile:
            with self.subTest(label):
                self.stub(judge=j, screen=sc)
                out = os.path.join(tmp, "adv.jsonl")
                self.assertEqual(main.main(["main.py", FIXTURE, out]), 0)
                with open(out, "rb") as f:
                    self.assertEqual(f.read(), want)


# ===================================================================== (d) failures
BAD_JUDGE = [None, "not json {", [], 42, {}, {"decision": "MAYBE", "reason_code": "INSUFFICIENT_DATA"},
             {"decision": SAME, "reason_code": "DOB_MISMATCH", "compared": [], "evidence_ids": []},
             {"decision": DIFF, "compared": [], "evidence_ids": []},
             {"decision": SAME, "reason_code": "NAME_DOB_MATCH", "compared": "x", "evidence_ids": 5},
             RuntimeError("judge down"), ValueError("bad json"), TimeoutError("slow")]
BAD_SCREEN = [None, "not json {", [], 7, {}, {"error_in": "rules"}, {"error_in": None},
              {"error_in": "deterministic", "significant_missed_facts": 5},
              RuntimeError("screener down"), ValueError("bad json"), TimeoutError("slow")]
ODD_BUT_PARSEABLE = [{"error_in": e, "significant_missed_facts": "oops", "explanation": 123} for e in ERROR_IN] + \
    [{"error_in": e, "significant_missed_facts": [None, 5, {"fact": "", "evidence_ids": [NOTE]},
                                                  {"fact": "x", "evidence_ids": NOTE}]} for e in ERROR_IN]


@unittest.skipUnless(HAVE_DUAL, SKIP)
class FailuresNeverCrash(Offline):
    def test_judge_failure_keeps_the_rules_line(self):
        """Thomas's choice: a judge failure is "no second view", not a disagreement."""
        for bad in BAD_JUDGE:
            for dd, dc in PAIRS:
                with self.subTest(judge=repr(bad)[:40], det=dc):
                    st = self.stub(judge=bad, screen=screen_answer("deterministic"))
                    d = det(dd, dc)
                    out = main.arbitrate_all([d], [item(d)], None)
                    self.assertEqual(out, {})
                    self.assertNotIn("screening_agent", st.calls)
                    self.assertEqual(arbiter.trace(d.hit_id)["path"], "llm_unavailable")

    def test_judge_failure_is_safe_under_either_policy(self):
        for bad in BAD_JUDGE:
            for dd, dc in PAIRS:
                self.stub(judge=bad, screen=screen_answer("deterministic"))
                d = det(dd, dc)
                final = main.arbitrate_all([d], [item(d)], None).get(d.hit_id, d)
                self.check_line(final, d, case=None)
                self.assertTrue(final == d or (final.decision, final.reason_code) == (REVIEW, "INSUFFICIENT_DATA"))

    def test_resolve_without_llm_view_keeps_rules(self):
        st = self.stub(screen=RuntimeError("must not be called"))
        for dd, dc in PAIRS:
            d = det(dd, dc)
            final, tr = arbiter.resolve(d, None, CASE)
            self.assertIs(final, d)
        self.assertEqual(st.calls, [])

    def test_screener_failure_goes_to_review_via_resolve(self):
        for bad in BAD_SCREEN:
            for det_dec, llm_dec in itertools.permutations(DECISIONS, 2):
                with self.subTest(screen=repr(bad)[:40], det=det_dec, llm=llm_dec):
                    self.stub(screen=bad)
                    d, v = det(det_dec), view(llm_dec)
                    final, tr = arbiter.resolve(d, v, CASE)
                    self.assertEqual((final.decision, final.reason_code), (REVIEW, "INSUFFICIENT_DATA"))
                    self.check_line(final, d, llm_view=v)
                    self.assertIsNone(tr["screener"])

    def test_screener_failure_goes_to_review_via_main(self):
        for bad in BAD_SCREEN:
            for det_dec, llm_dec in itertools.permutations(DECISIONS, 2):
                with self.subTest(screen=repr(bad)[:40], det=det_dec, llm=llm_dec):
                    self.stub(judge=view(llm_dec), screen=bad)
                    d = det(det_dec)
                    final = main.arbitrate_all([d], [item(d)], None).get(d.hit_id, d)
                    self.assertEqual((final.decision, final.reason_code), (REVIEW, "INSUFFICIENT_DATA"))
                    self.check_line(final, d, case=None)

    def test_odd_but_parseable_screens_follow_the_table(self):
        for s in ODD_BUT_PARSEABLE:
            for det_dec, llm_dec in itertools.permutations(DECISIONS, 2):
                with self.subTest(screen=repr(s)[:60], det=det_dec, llm=llm_dec):
                    self.stub(screen=s)
                    d, v = det(det_dec), view(llm_dec)
                    final, _ = arbiter.resolve(d, v, CASE)
                    self.check_line(final, d, llm_view=v)
                    self.assertIn(final.decision, (expected(det_dec, llm_dec, s["error_in"]), REVIEW,
                                                   expected(det_dec, llm_dec, s["error_in"], cited=False)))

    def test_malformed_json_through_the_real_client(self):
        """engine.llm.ask_json itself, given a reply whose content is not JSON (no network, fake key)."""
        class Reply:
            def __init__(self, content):
                self.body = json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self.body
        urllib.request.urlopen = lambda *a, **k: Reply("{not json")
        self.patch(llm, "time", types.SimpleNamespace(time=__import__("time").time, sleep=lambda s: None))
        self.patch(arbiter, "llm", llm)
        self.patch(llm_judge, "llm", llm)
        saved = {k: os.environ.get(k) for k in ("LLM_DISABLE", "OPENROUTER_API_KEY", "XAI_API_KEY")}

        def restore():
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.addCleanup(restore)
        self.addCleanup(llm._MEMO.clear)
        os.environ.pop("LLM_DISABLE", None)
        os.environ["OPENROUTER_API_KEY"] = "sk-invented-not-a-real-key"
        llm._MEMO.clear()
        self.assertIsNone(llm.ask_json("s", "u", {"type": "object"}))
        for dd, dc in PAIRS:
            d = det(dd, dc)
            self.assertEqual(main.arbitrate_all([d], [item(d)], None), {})  # judge: no view, rules kept
            final, _ = arbiter.resolve(d, view(SAME if dd != SAME else REVIEW), CASE)  # screener: REVIEW
            self.assertEqual((final.decision, final.reason_code), (REVIEW, "INSUFFICIENT_DATA"))

    def test_review_all_exception_keeps_every_line(self):
        def boom(*a, **k):
            raise RuntimeError("arbiter down")
        self.patch(main, "arbiter", types.SimpleNamespace(review_all=boom))
        d = det(SAME)
        self.assertEqual(main.arbitrate_all([d], [item(d)], None), {})

    def test_case_build_failure_keeps_the_rules_line(self):
        st = self.stub(judge=view(DIFF), screen=screen_answer("deterministic"))
        d = det(SAME)
        broken = (d, None, None, None)  # build_case cannot read this
        self.assertEqual(main.arbitrate_all([d], [broken], None), {})
        self.assertEqual(st.calls, [])


@unittest.skipUnless(HAVE_DUAL, SKIP)
class UnvalidatedLLMView(Offline):
    """resolve() called directly with an LLM dict that did not go through llm_judge.judge()."""

    def test_view_without_reason_code_does_not_crash(self):
        self.stub(screen=screen_answer("deterministic"))
        d = det(DIFF)
        final, _ = arbiter.resolve(d, {"decision": SAME}, CASE)
        self.check_line(final, d)

    def test_view_code_must_belong_to_the_final_decision(self):
        self.stub(screen=screen_answer("deterministic"))
        d = det(DIFF)
        final, _ = arbiter.resolve(d, view(SAME, "DOB_MISMATCH"), CASE)
        self.check_line(final, d)

    def test_view_evidence_limited_to_allowed_ids(self):
        self.stub(screen=screen_answer("deterministic"))
        d = det(DIFF)
        final, _ = arbiter.resolve(d, view(SAME, ev=[NOTE, FAKE]), CASE)
        self.check_line(final, d)

    def test_never_a_clearance_even_unvalidated(self):
        self.stub(screen=screen_answer("deterministic"))
        for dd in (SAME, REVIEW):
            for v in ({"decision": DIFF, "reason_code": "DOB_MISMATCH"}, {"decision": DIFF, "reason_code": "NOPE"},
                      {"decision": DIFF, "reason_code": "DOB_MISMATCH", "evidence_ids": [FAKE, HID]}):
                try:
                    final, _ = arbiter.resolve(det(dd), v, CASE)
                except Exception:  # noqa: BLE001  (a crash is reported by the tests above)
                    continue
                self.assertNotEqual(final.decision, DIFF)


# ====================================== (e) enforce: right rules survive a plausible but wrong LLM
@unittest.skipUnless(HAVE_DUAL, SKIP)
class EnforceKeepsRightRules(Offline):
    """DUAL_MODE=enforce. The rules are right and the LLM is plausible but wrong, e.g. it clears a location
    mismatch although a date of birth is unknown, or calls a namesake who shares a country SAME_ENTITY.
    The arbiter must keep the rules unless the screener disproves them with a record from the case."""

    def setUp(self):
        super().setUp()
        if not _has_dual_mode():
            self.skipTest("DUAL_MODE not on this branch yet")
        saved = os.environ.get("DUAL_MODE")
        self.addCleanup(lambda: os.environ.__setitem__("DUAL_MODE", saved) if saved is not None
                        else os.environ.pop("DUAL_MODE", None))

    def _e2e(self, screen):
        if not os.path.isdir(FIXTURE):
            self.skipTest("tests/fixtures/rare missing")
        tmp = tempfile.mkdtemp(prefix="dual-enf-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.patch(main, "crossexam", None)
        self.patch(main, "arbiter", None)
        os.environ["DUAL_MODE"] = "off"
        ref = os.path.join(tmp, "rules.jsonl")
        self.assertEqual(main.main(["main.py", FIXTURE, ref]), 0)
        main.arbiter = arbiter
        os.environ["DUAL_MODE"] = "enforce"
        st = self.stub(judge=view(SAME, "NAME_DOB_MATCH"), screen=screen)
        out = os.path.join(tmp, "enforce.jsonl")
        self.assertEqual(main.main(["main.py", FIXTURE, out]), 0)
        self.assertIn("llm_judge", st.calls)
        pick = lambda path: {h: (x["decision"], x["reason_code"]) for h, x in _lines(path).items()}  # noqa: E731
        return pick(ref), pick(out)

    def test_screener_backing_the_rules_keeps_every_line(self):
        """Wrong judge everywhere, screener says the LLM erred: every decision and reason code kept."""
        want, got = self._e2e(screen_answer("llm"))
        self.assertEqual(got, want)

    def test_uncited_blame_keeps_every_line(self):
        """Screener blames the rules but cites no record at all: the rules must stand (lead, 7064805375)."""
        want, got = self._e2e(screen_answer("deterministic", missed=()))
        self.assertEqual(got, want)

    def test_blame_citing_only_unsupplied_ids_keeps_the_rules(self):
        """Location without DOB / namesake with a shared country: the LLM says SAME, the screener blames
        the rules citing only a fabricated KYC id and hit/account ids. Not a disproof: rules stand."""
        for dd, dc in PAIRS:
            if dd == SAME:
                continue
            with self.subTest(det=dc):
                self.stub(judge=None, screen=screen_answer("deterministic", missed=(FAKE, HID, ACC)))
                d = det(dd, dc)
                final, _ = arbiter.resolve(d, view(SAME, "NAME_DOB_MATCH"), CASE)
                self.assertEqual((final.decision, final.reason_code), (d.decision, d.reason_code))


# ================================================================= (c) no key = rules only
RUNNER = r"""
import sys, urllib.request
def _no_net(*a, **k):
    sys.stderr.write("NETWORK-CALL-ATTEMPTED\n")
    raise RuntimeError("network disabled in tests")
urllib.request.urlopen = _no_net
sys.path.insert(0, sys.argv[1])
import main
if sys.argv[2] == "rules":   # the rules-only reference: no LLM hook of any kind
    main.arbiter = None
    main.crossexam = None
sys.exit(main.main(["main.py", sys.argv[3], sys.argv[4]]))
"""


def _bash():
    env = os.environ.get("RARE_BASH")
    if env and os.path.isfile(env):
        return env
    if os.name == "nt":
        for p in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
            if os.path.isfile(p):
                return p
        found = shutil.which("bash")
        return found if found and "system32" not in found.lower() else None
    return shutil.which("bash")


def _env(disable, key=""):
    env = {k: v for k, v in os.environ.items() if not k.upper().endswith("_API_KEY") and k != "LLM_DISABLE"}
    env.update(PYTHONHASHSEED="0", PYTHONIOENCODING="utf-8", OPENROUTER_API_KEY=key, XAI_API_KEY=key)
    if disable:
        env["LLM_DISABLE"] = "1"
    return env


@unittest.skipUnless(os.path.isdir(FIXTURE), "tests/fixtures/rare missing")
class NoKeyIsRulesOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="dual-nokey-")
        cls.runner = os.path.join(cls.tmp, "runner.py")
        with open(cls.runner, "w", encoding="utf-8") as f:
            f.write(RUNNER)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_main(self, name, mode, env):
        out = os.path.join(self.tmp, name + ".jsonl")
        proc = subprocess.run([sys.executable, "-X", "utf8", self.runner, SYSTEM, mode, FIXTURE, out], cwd=ROOT,
                              env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        err = proc.stderr.decode("utf-8", "replace")
        self.assertEqual(proc.returncode, 0, err[-2000:])
        self.assertNotIn("NETWORK-CALL-ATTEMPTED", err)
        with open(out, "rb") as f:
            return f.read()

    def test_byte_identical_to_rules_only(self):
        ref = self.run_main("rules", "rules", _env(True))
        self.assertTrue(ref.strip())
        runs = {
            "LLM_DISABLE=1, keys blank": self.run_main("off_blank", "full", _env(True)),
            "no LLM_DISABLE, keys blank": self.run_main("nokey", "full", _env(False)),
            "LLM_DISABLE=1, invented keys set": self.run_main("off_key", "full", _env(True, "invented-not-a-key")),
        }
        for label, got in runs.items():
            with self.subTest(label):
                self.assertEqual(got, ref)

    def test_system_run_matches_rules_only(self):
        bash = _bash()
        if not bash:
            self.skipTest("no bash to start system/run")
        ref = self.run_main("rules2", "rules", _env(True))
        out = os.path.join(self.tmp, "run.jsonl")
        posix = lambda p: p.replace("\\", "/")  # noqa: E731
        for label, env in (("LLM_DISABLE=1", _env(True)), ("keys blank", _env(False))):
            with self.subTest(label):
                proc = subprocess.run([bash, posix(RUN), posix(FIXTURE), posix(out)], cwd=ROOT, env=env,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
                self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace")[-2000:])
                with open(out, "rb") as f:
                    self.assertEqual(f.read(), ref)

    @unittest.skipUnless(HAVE_DUAL, SKIP)
    def test_review_all_makes_no_call_without_a_key(self):
        saved = {k: os.environ.get(k) for k in ("LLM_DISABLE", "OPENROUTER_API_KEY", "XAI_API_KEY")}
        real_ask = llm.ask_json

        def must_not_call(*a, **k):
            raise AssertionError("ask_json called without a key")
        llm.ask_json = must_not_call
        try:
            for disable, key in ((True, "invented-not-a-key"), (True, ""), (False, "")):
                os.environ.pop("LLM_DISABLE", None)
                if disable:
                    os.environ["LLM_DISABLE"] = "1"
                os.environ["OPENROUTER_API_KEY"] = os.environ["XAI_API_KEY"] = key
                self.assertFalse(llm.available())
                for dd in DECISIONS:
                    d = det(dd)
                    self.assertEqual(arbiter.review_all([item(d)], None), {})
                    self.assertEqual(main.arbitrate_all([d], [item(d)], None), {})
        finally:
            llm.ask_json = real_ask
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
