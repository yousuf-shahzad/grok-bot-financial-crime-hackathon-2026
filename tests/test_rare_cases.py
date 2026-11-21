"""End-to-end SOP checks on rare cases, using the invented data folder tests/fixtures/rare.

Every customer, hit, check and ID in the fixture is made up. Expected answers come
from SPEC.md (the SOP), not from the engine's current output.
Runs the real entry point system/run with bash when one is found (Git Bash on
Windows), otherwise system/main.py with this Python.

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
    env = dict(os.environ, PYTHONHASHSEED="0", PYTHONIOENCODING="utf-8")
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


if __name__ == "__main__":
    unittest.main()