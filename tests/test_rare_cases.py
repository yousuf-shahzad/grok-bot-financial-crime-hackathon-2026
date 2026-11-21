"""End-to-end SOP checks on rare cases, using the invented data folder tests/fixtures/rare.

Every customer, hit, check and ID in the fixture is made up. Expected answers come
from SPEC.md (the SOP), not from the engine's current output.
Runs the real entry point system/run with bash when one is found (Git Bash on
Windows), otherwise system/main.py with this Python.

Rules only, offline: the run's environment drops every LLM key (OPENROUTER_API_KEY,
XAI_API_KEY and any other *_API_KEY) so the optional cross-examiner hook in main.py
has no provider, and sets LLM_DISABLE=1 (llm.py's off switch, which wins over any key). The
keys are set to "" so a local .env cannot fill them in. No network, no key needed.

Run: py -3 -X utf8 -m unittest discover -s tests
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURE = os.path.join(HERE, "fixtures", "rare")
RUN = os.path.join(ROOT, "system", "run")
MAIN = os.path.join(ROOT, "system", "main.py")

DIFF, SAME, REVIEW = "DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW"


def _find_bash():
    env = os.environ.get("RARE_BASH")
    if env and os.path.isfile(env):
        return env
    if os.name == "nt":
        for p in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
            if os.path.isfile(p):
                return p
        found = shutil.which("bash")
        # the WSL launcher in System32 is not a usable bash for this repo
        if found and "system32" not in found.lower():
            return found
        return None
    return shutil.which("bash")


def _posix(p):
    return p.replace("\\", "/")


def run_fixture():
    out_dir = tempfile.mkdtemp(prefix="rare-")
    out = os.path.join(out_dir, "out.jsonl")
    bash = _find_bash()
    if bash:
        cmd = [bash, _posix(RUN), _posix(FIXTURE), _posix(out)]
    else:
        cmd = [sys.executable, "-X", "utf8", MAIN, FIXTURE, out]
    env = {k: v for k, v in os.environ.items() if not k.upper().endswith("_API_KEY")}
    env.update(PYTHONHASHSEED="0", PYTHONIOENCODING="utf-8", OPENROUTER_API_KEY="", XAI_API_KEY="",
               LLM_DISABLE="1")
    proc = subprocess.run(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=300)
    lines = []
    if os.path.isfile(out):
        with open(out, encoding="utf-8") as f:
            lines = [json.loads(x) for x in f if x.strip()]
    shutil.rmtree(out_dir, ignore_errors=True)
    return proc, cmd, {d["hit_id"]: d for d in lines}


class RareCasesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proc, cls.cmd, cls.out = run_fixture()

    def expect(self, hit_id, decision, code, cid=None, cids=None):
        self.assertIn(hit_id, self.out, "no output line for %s (stderr: %s)"
                      % (hit_id, self.proc.stderr.decode("utf-8", "replace")[-500:]))
        d = self.out[hit_id]
        self.assertEqual((d["decision"], d["reason_code"]), (decision, code), hit_id)
        if cid is not None:
            self.assertEqual(d["customer_record_id"], cid, hit_id)
        if cids is not None:
            self.assertIn(d["customer_record_id"], cids, hit_id)
        return d

    # ---- the run itself ----------------------------------------------------------------------
    def test_entry_point_succeeds_and_covers_every_hit(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr.decode("utf-8", "replace"))
        with open(os.path.join(FIXTURE, "hits.jsonl"), encoding="utf-8") as f:
            ids = sorted(json.loads(x)["hit_id"] for x in f if x.strip())
        self.assertEqual(sorted(self.out), ids)

    def test_output_shape_and_reason_code_belongs_to_decision(self):
        allowed = {
            DIFF: {"TEMPORAL_IMPOSSIBILITY", "DOB_MISMATCH", "LOCATION_MISMATCH", "NAME_MISMATCH_VERIFIED",
                   "ENTITY_TYPE_MISMATCH", "DECEASED"},
            SAME: {"NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH", "NAME_LOCATION_MATCH"},
            REVIEW: {"INSUFFICIENT_DATA", "AMBIGUOUS_CUSTOMER_RECORD"},
        }
        for hid, d in sorted(self.out.items()):
            self.assertEqual(sorted(d), sorted(["hit_id", "alert_id", "decision", "reason_code",
                                                "customer_record_id", "reason", "evidence"]), hid)
            self.assertIn(d["reason_code"], allowed[d["decision"]], hid)
            self.assertEqual(d["evidence"], sorted(set(d["evidence"])), hid)
            self.assertTrue(str(d["reason"]).strip(), hid)

    # ---- SOP section 3: contradictions -------------------------------------------------------
    def test_01_deceased_before_screening(self):
        self.expect("H-RC01", DIFF, "DECEASED", cid="CUS-RC0101")

    def test_02_person_vs_company(self):
        self.expect("H-RC02", DIFF, "ENTITY_TYPE_MISMATCH", cid="CUS-RC0201")

    def test_03_company_incorporated_after_earliest_report(self):
        self.expect("H-RC03", DIFF, "TEMPORAL_IMPOSSIBILITY", cid="CUS-RC0301")

    # ---- SOP section 4: agreement ------------------------------------------------------------
    def test_04_company_name_location_match(self):
        self.expect("H-RC04", SAME, "NAME_LOCATION_MATCH", cid="CUS-RC0401")

    # ---- SOP section 1C: ambiguity -----------------------------------------------------------
    def test_05_two_people_decisions_differ(self):
        d = self.expect("H-RC05", REVIEW, "AMBIGUOUS_CUSTOMER_RECORD", cid="AMBIGUOUS")
        self.assertTrue({"CUS-RC0501", "CUS-RC0502"} <= set(d["evidence"]))

    def test_06_two_people_same_decision(self):
        self.expect("H-RC06", DIFF, "DOB_MISMATCH", cid="AMBIGUOUS")

    # ---- SOP section 3 exception -------------------------------------------------------------
    def test_07_name_dob_agree_countries_differ_is_review(self):
        self.expect("H-RC07", REVIEW, "INSUFFICIENT_DATA", cid="CUS-RC0701")

    # ---- SOP section 1D: rejected / expired checks are not evidence --------------------------
    def test_08_rejected_and_expired_kyc_ignored(self):
        d = self.expect("H-RC08", SAME, "NAME_DOB_LOCATION_MATCH", cid="CUS-RC0801")
        self.assertNotIn("KYC-RC0801", d["evidence"])
        self.assertNotIn("KYC-RC0802", d["evidence"])

    # ---- SOP section 1B: merging -------------------------------------------------------------
    def test_09_document_number_merge(self):
        # the dob is only on the record merged through the shared approved document number
        d = self.expect("H-RC09", SAME, "NAME_DOB_LOCATION_MATCH", cids=["CUS-RC0901", "CUS-RC0902"])
        self.assertIn("CUS-RC0902", d["evidence"])

    def test_13_rejected_check_does_not_merge(self):
        self.expect("H-RC13", REVIEW, "INSUFFICIENT_DATA", cid="CUS-RC1301")

    def test_14_shared_phone_alone_does_not_merge(self):
        self.expect("H-RC14", REVIEW, "INSUFFICIENT_DATA", cid="CUS-RC1401")

    # ---- SOP section 5: placeholder and single-part names ------------------------------------
    def test_10_single_part_customer_name_is_review(self):
        self.expect("H-RC10", REVIEW, "INSUFFICIENT_DATA", cid="CUS-RC1001")

    def test_11_placeholder_verified_name_cannot_clear(self):
        self.expect("H-RC11", REVIEW, "INSUFFICIENT_DATA", cid="CUS-RC1101")

    def test_12_placeholder_hit_name_cannot_clear(self):
        self.expect("H-RC12", REVIEW, "INSUFFICIENT_DATA", cid="CUS-RC1201")


    # ---- reworded notes (wording invented, not in dev): KYC verifications -------------------
    def test_21_kyc_note_provider_first_active_vetted(self):
        d = self.expect("H-RC21", SAME, "NAME_DOB_LOCATION_MATCH", cid="CUS-RC2101")
        self.assertIn("NOTE-RC0001", d["evidence"])

    def test_22_kyc_note_country_first_passive_cleared(self):
        d = self.expect("H-RC22", SAME, "NAME_DOB_LOCATION_MATCH", cid="CUS-RC2201")
        self.assertIn("NOTE-RC0002", d["evidence"])

    def test_23_kyc_note_successfully_confirming(self):
        d = self.expect("H-RC23", SAME, "NAME_DOB_LOCATION_MATCH", cid="CUS-RC2301")
        self.assertIn("NOTE-RC0003", d["evidence"])

    def test_24_kyc_note_verifies_other_legal_name(self):
        d = self.expect("H-RC24", DIFF, "NAME_MISMATCH_VERIFIED", cid="CUS-RC2401")
        self.assertIn("NOTE-RC0004", d["evidence"])

    # ---- failure words: never a verification (a wrong one would clear on name) ---------------
    def _not_verified(self, n):
        hid, note_id = "H-RC%02d" % n, "NOTE-RC%04d" % (n - 20)
        d = self.expect(hid, SAME, "NAME_DOB_LOCATION_MATCH", cid="CUS-RC%02d01" % n)
        self.assertNotIn(note_id, d["evidence"])

    def test_25_failure_word_rejected(self):
        self._not_verified(25)

    def test_26_failure_word_failed(self):
        self._not_verified(26)

    def test_27_failure_word_unable(self):
        self._not_verified(27)

    def test_28_failure_word_expired(self):
        self._not_verified(28)

    def test_29_failure_word_declined(self):
        self._not_verified(29)

    def test_30_failure_word_mismatch(self):
        self._not_verified(30)

    # ---- names: bracketed aliases, placeholder tokens ----------------------------------------
    def test_31_bracketed_aliases(self):
        self.expect("H-RC31", SAME, "NAME_DOB_LOCATION_MATCH", cid="CUS-RC3101")

    def test_32_placeholder_tokens_inside_names(self):
        self.expect("H-RC32", SAME, "NAME_DOB_LOCATION_MATCH", cid="CUS-RC3201")

    # ---- date formats ------------------------------------------------------------------------
    def test_33_month_d_yyyy_vs_d_mon_yyyy(self):
        self.expect("H-RC33", SAME, "NAME_DOB_LOCATION_MATCH", cid="CUS-RC3301")

    def test_34_day_first_slash_vs_year_month(self):
        self.expect("H-RC34", SAME, "NAME_DOB_LOCATION_MATCH", cid="CUS-RC3401")

    def test_35_one_year_off_is_review_not_clear(self):
        self.expect("H-RC35", REVIEW, "INSUFFICIENT_DATA", cid="CUS-RC3501")

    def test_36_d_month_yyyy_vs_year_mismatch(self):
        self.expect("H-RC36", DIFF, "DOB_MISMATCH", cid="CUS-RC3601")

    # ---- reworded ages in the profile ----------------------------------------------------------
    def test_37_aged_n_at_the_time_of_report(self):
        self.expect("H-RC37", SAME, "NAME_DOB_LOCATION_MATCH", cid="CUS-RC3701")

    def test_38_then_n(self):
        self.expect("H-RC38", SAME, "NAME_DOB_LOCATION_MATCH", cid="CUS-RC3801")

    def test_39_reworded_age_contradicts(self):
        self.expect("H-RC39", DIFF, "DOB_MISMATCH", cid="CUS-RC3901")

    # ---- death wording -------------------------------------------------------------------------
    def test_40_died_in(self):
        self.expect("H-RC40", DIFF, "DECEASED", cid="CUS-RC4001")

    def test_41_passed_away_on(self):
        self.expect("H-RC41", DIFF, "DECEASED", cid="CUS-RC4101")

    def test_42_deceased_since(self):
        self.expect("H-RC42", DIFF, "DECEASED", cid="CUS-RC4201")

    # ---- company vs person profiles ----------------------------------------------------------
    def test_43_organisation_hit_vs_person(self):
        self.expect("H-RC43", DIFF, "ENTITY_TYPE_MISMATCH", cid="CUS-RC4301")

    def test_44_person_hit_vs_company(self):
        self.expect("H-RC44", DIFF, "ENTITY_TYPE_MISMATCH", cid="CUS-RC4401")

    # ---- lived-in note, country named first ------------------------------------------------
    def test_45_lived_in_country_first(self):
        d = self.expect("H-RC45", SAME, "NAME_DOB_LOCATION_MATCH", cid="CUS-RC4501")
        self.assertIn("NOTE-RC0011", d["evidence"])

    def test_46_dob_differs_passport_check_pending(self):
        d = self.expect("H-RC46", DIFF, "DOB_MISMATCH", cid="CUS-RC4601")
        self.assertIn("KYC-RC4601", d["evidence"])

    # ---- determinism -------------------------------------------------------------------------
    def test_second_run_identical(self):
        _, _, again = run_fixture()
        self.assertEqual(again, self.out)

if __name__ == "__main__":
    unittest.main()