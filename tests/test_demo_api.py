"""JSON API checks for the Case Review demo server (demo/app.py + demo/review_api.py).

Starts demo/app.py on the invented fixture folder tests/fixtures/rare, offline and with no LLM
(every *_API_KEY blanked and LLM_DISABLE=1, as in test_rare_cases.py), on a free local port,
with the review audit log in a temp SQLite file (CASE_REVIEW_DB), then checks the JSON API:
status, summary, the case queue, one case, the maker-checker review workflow, the append-only
audit log, MI, case reports, the reviewed-decisions export and the LLM court without a key.

Tests share one server, so each workflow test uses its own hit.
Run: py -3 -X utf8 -m unittest discover -s tests
"""
from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURE = os.path.join(HERE, "fixtures", "rare")
APP = os.path.join(ROOT, "demo", "app.py")
DECISIONS = {"DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW"}
BUCKETS = {"needs_decision", "returned", "pending_approval", "proposed_match", "proposed_clear", "escalated", "done"}
MAKER, CHECKER = "Test Maker", "Test Checker"
WHY = "Invented rationale for the API test."


def _count_lines(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


HITS = _count_lines(os.path.join(FIXTURE, "hits.jsonl"))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class DemoApiTest(unittest.TestCase):
    proc = None
    base = ""

    @classmethod
    def setUpClass(cls):
        env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
        env.update({"OPENROUTER_API_KEY": "", "XAI_API_KEY": "", "LLM_DISABLE": "1", "PYTHONIOENCODING": "utf-8"})
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = env["CASE_REVIEW_DB"] = os.path.join(cls.tmp.name, "reviews.sqlite")
        port = _free_port()
        cls.base = "http://127.0.0.1:%d" % port
        cls.proc = subprocess.Popen([sys.executable, "-X", "utf8", APP, FIXTURE, "--port", str(port)],
                                    cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.time() + 60
        while True:
            if cls.proc.poll() is not None:
                raise RuntimeError("demo/app.py exited early: " + cls.proc.stderr.read().decode("utf-8", "replace"))
            try:
                if cls.get("/api/status")[1].get("ready"):
                    break
            except (urllib.error.URLError, ConnectionError, ValueError):
                pass
            if time.time() > deadline:
                raise RuntimeError("demo/app.py did not become ready within 60 s")
            time.sleep(0.2)
        cls.codes = cls.get("/api/codes")[1]
        cls.hit_ids = sorted(r["hit_id"] for r in cls.get("/api/cases")[1]["rows"])

    @classmethod
    def tearDownClass(cls):
        if cls.proc is not None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
            cls.proc.stderr.close()
        cls.tmp.cleanup()

    # ---------------------------------------------------------------- HTTP helpers

    @classmethod
    def _open(cls, req):
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read().decode("utf-8")

    @classmethod
    def get(cls, path: str):
        code, text = cls._open(cls.base + path)
        return code, json.loads(text or "{}")

    @classmethod
    def text(cls, path: str):
        return cls._open(cls.base + path)

    @classmethod
    def post(cls, path: str, body: dict):
        req = urllib.request.Request(cls.base + path, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        code, text = cls._open(req)
        return code, json.loads(text or "{}")

    def case(self, hid):
        code, x = self.get("/api/case/" + hid)
        self.assertEqual(code, 200)
        return x

    def decide(self, hid, decision, who=MAKER, **extra):
        x = self.case(hid)
        body = {"hit_id": hid, "action": "DECIDE", "decision": decision, "reviewer": who, "role": "analyst",
                "rationale": WHY, "reason_code": self.codes[decision][0],
                "record_ids": [r["id"] for r in x["records"]][:1]}
        body.update(extra)
        return self.post("/api/review", body)

    def act(self, hid, action, who):
        return self.post("/api/review", {"hit_id": hid, "action": action, "reviewer": who, "role": "checker", "rationale": WHY})

    def bucket(self, hid):
        return self.case(hid)["workflow"]

    # ---------------------------------------------------------------- status, summary

    def test_status_ready(self):
        code, body = self.get("/api/status")
        self.assertEqual(code, 200)
        self.assertIs(body["ready"], True)
        self.assertIsInstance(body.get("status"), str)

    def test_summary_counts(self):
        code, s = self.get("/api/summary")
        self.assertEqual(code, 200)
        self.assertEqual(s["hits"], HITS)
        self.assertEqual(s["alerts"], _count_lines(os.path.join(FIXTURE, "alerts.jsonl")))
        self.assertTrue(set(s["by_decision"]) <= DECISIONS, s["by_decision"])
        self.assertEqual(sum(n for codes in s["by_decision"].values() for n in codes.values()), HITS)

    def test_summary_rules_only_without_key(self):
        _, s = self.get("/api/summary")
        self.assertIn("rules only", str(s.get("llm", "rules only")))
        self.assertEqual(s.get("crossexam_downgrades", 0), 0)
        self.assertIs(bool(s.get("blindfold", False)), False)

    def test_summary_practice_without_labels(self):
        _, s = self.get("/api/summary")
        self.assertEqual(s["practice"]["n"], 0)   # the fixture ships no practice labels

    def test_unknown_path_is_json_404(self):
        code, body = self.get("/api/no-such-endpoint")
        self.assertEqual(code, 404)
        self.assertIn("error", body)

    def test_codes(self):
        self.assertEqual(set(self.codes), {"CLEAR", "CONFIRM", "ESCALATE"})
        self.assertTrue(all(self.codes[k] for k in self.codes))

    # ---------------------------------------------------------------- queue

    def test_cases_shape_and_counts(self):
        code, c = self.get("/api/cases")
        self.assertEqual(code, 200)
        self.assertEqual(set(c["counts"]) - {"qa_sample"}, BUCKETS)
        self.assertEqual(sum(v for k, v in c["counts"].items() if k != "qa_sample"), HITS)
        self.assertEqual(c["total"], HITS)
        for r in c["rows"]:
            self.assertIn(r["bucket"], BUCKETS)
            self.assertIn(r["system"]["decision"], DECISIONS)
            self.assertIsInstance(r["qa_sample"], bool)
            for k in ("hit_id", "alert_id", "hit_name", "screened_name", "entity_type", "crossexamined", "human"):
                self.assertIn(k, r)

    def test_cases_bucket_filter(self):
        _, all_ = self.get("/api/cases")
        for b in sorted(BUCKETS):
            code, c = self.get("/api/cases?bucket=" + b)
            self.assertEqual(code, 200)
            self.assertTrue(all(r["bucket"] == b for r in c["rows"]), b)
            self.assertEqual(c["total"], all_["counts"][b], b)

    def test_cases_qa_filter_only_engine_clearances(self):
        _, c = self.get("/api/cases?qa=1")
        for r in c["rows"]:
            self.assertIs(r["qa_sample"], True)
            self.assertEqual(r["system"]["decision"], "DIFFERENT_ENTITY")

    def test_cases_search(self):
        hid = self.hit_ids[0]
        _, c = self.get("/api/cases?q=" + hid)
        self.assertIn(hid, [r["hit_id"] for r in c["rows"]])

    # ---------------------------------------------------------------- one case

    def test_case_detail(self):
        hid = self.hit_ids[0]
        x = self.case(hid)
        self.assertEqual(x["decision"]["hit_id"], hid)
        self.assertTrue(x["comparison"])
        for row in x["comparison"]:
            self.assertIn(row["status"], {"agree", "contradict", "unknown"})
            self.assertIn("field", row)
        for rec in x["records"]:
            self.assertTrue(rec["id"])
            for k in ("kind", "group", "default", "text"):
                self.assertIn(k, rec)
        self.assertIsInstance(x["history"], list)
        self.assertIn(x["workflow"], BUCKETS)
        self.assertIsInstance(x["qa_sample"], bool)
        self.assertIs(x["court_available"], False)   # no LLM key in this test

    def test_case_unknown_is_404(self):
        self.assertEqual(self.get("/api/case/H-NO-SUCH-HIT")[0], 404)

    def test_report_markdown(self):
        hid = self.hit_ids[0]
        code, md = self.text("/api/report/%s.md" % hid)
        self.assertEqual(code, 200)
        self.assertIn(hid, md)

    # ---------------------------------------------------------------- review validation

    def test_review_rejects_bad_input(self):
        hid = self.hit_ids[1]
        self.assertEqual(self.decide(hid, "CONFIRM", who="")[0], 400)                   # no reviewer
        self.assertEqual(self.decide(hid, "CONFIRM", rationale="too short")[0], 400)    # < 10 chars
        self.assertEqual(self.post("/api/review", {"hit_id": hid, "decision": "MAYBE", "reviewer": MAKER, "rationale": WHY})[0], 400)
        self.assertEqual(self.decide(hid, "CONFIRM", reason_code="NOT_A_CODE")[0], 400)
        self.assertEqual(self.decide(hid, "CLEAR", reason_code=self.codes["CONFIRM"][0])[0], 400)  # code of another decision
        self.assertEqual(self.decide(hid, "CLEAR", record_ids=[])[0], 400)              # CLEAR must cite a record
        self.assertEqual(self.decide(hid, "CONFIRM", record_ids=["NOT-A-RECORD"])[0], 400)  # only the case's records count
        self.assertEqual(self.post("/api/review", {"hit_id": hid, "action": "SHRUG", "reviewer": MAKER, "rationale": WHY})[0], 400)
        self.assertEqual(self.post("/api/review", {"hit_id": "H-NO-SUCH-HIT", "decision": "CONFIRM", "reviewer": MAKER, "rationale": WHY})[0], 404)
        self.assertEqual(self.act(hid, "APPROVE", CHECKER)[0], 409)                     # nothing pending
        self.assertEqual(self.get("/api/reviews/" + hid)[1]["history"], [])            # nothing was written

    # ---------------------------------------------------------------- maker-checker workflow

    def test_four_eyes_approve_flow_and_export(self):
        hid = self.hit_ids[2]
        rec = [r["id"] for r in self.case(hid)["records"]][:1]
        code, r = self.decide(hid, "CONFIRM", record_ids=rec)
        self.assertEqual(code, 200, r)
        self.assertIs(r["ok"], True)
        self.assertEqual(r["workflow"], "pending_approval")
        self.assertEqual(self.decide(hid, "CLEAR")[0], 409)                             # already decided
        self.assertEqual(self.act(hid, "APPROVE", MAKER.upper())[0], 403)               # same person, any case
        code, r = self.act(hid, "APPROVE", CHECKER)
        self.assertEqual(code, 200, r)
        self.assertEqual(r["workflow"], "done")

        hist = self.get("/api/reviews/" + hid)[1]["history"]
        self.assertEqual([h["action"] for h in hist], ["DECIDE", "APPROVE"])
        self.assertEqual(hist[0]["decision"], "CONFIRM")
        self.assertEqual(hist[0]["reviewer"], MAKER)
        self.assertEqual(hist[1]["reviewer"], CHECKER)

        row = next(x for x in self.get("/api/cases?bucket=done")[1]["rows"] if x["hit_id"] == hid)
        self.assertEqual(row["human"]["decision"], "CONFIRM")
        self.assertEqual(row["human"]["maker"], MAKER)
        self.assertEqual(row["human"]["checker"], CHECKER)

        code, text = self.text("/api/reviewed_decisions.jsonl")
        self.assertEqual(code, 200)
        lines = [json.loads(l) for l in text.splitlines() if l.strip()]
        self.assertEqual(len(lines), HITS)
        self.assertEqual(len({l["hit_id"] for l in lines}), HITS)
        mine = next(l for l in lines if l["hit_id"] == hid)
        self.assertEqual(mine["decision"], "SAME_ENTITY")   # the approved human call wins
        self.assertEqual(mine["status"], "done")
        self.assertEqual((mine["maker"], mine["checker"]), (MAKER, CHECKER))
        self.assertEqual(mine["reason"], WHY)
        self.assertEqual(mine["evidence"], rec)

    def test_return_sends_case_back(self):
        hid = self.hit_ids[3]
        self.assertEqual(self.decide(hid, "CLEAR")[0], 200)
        code, r = self.act(hid, "RETURN", CHECKER)
        self.assertEqual(code, 200, r)
        self.assertEqual(r["workflow"], "returned")
        self.assertEqual(self.decide(hid, "ESCALATE", record_ids=[])[0], 200)           # a returned case can be decided again

    def test_escalate_needs_no_record_or_checker(self):
        hid = self.hit_ids[4]
        code, r = self.decide(hid, "ESCALATE", record_ids=[])
        self.assertEqual(code, 200, r)
        self.assertEqual(r["workflow"], "escalated")
        self.assertEqual(self.bucket(hid), "escalated")

    def test_pending_case_is_not_exported_as_human_call(self):
        hid = self.hit_ids[5]
        self.assertEqual(self.decide(hid, "CONFIRM")[0], 200)
        mine = next(json.loads(l) for l in self.text("/api/reviewed_decisions.jsonl")[1].splitlines() if json.loads(l)["hit_id"] == hid)
        system = self.case(hid)["decision"]
        self.assertEqual(mine["status"], "pending_approval")
        self.assertEqual(mine["decision"], system["decision"])   # unapproved: the engine's answer stands

    # ---------------------------------------------------------------- audit log, MI

    def test_audit_log_is_append_only(self):
        hid = self.hit_ids[6]
        self.assertEqual(self.decide(hid, "ESCALATE", record_ids=[])[0], 200)
        con = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                con.execute("UPDATE reviews SET decision='CLEAR' WHERE hit_id=?", (hid,))
            with self.assertRaises(sqlite3.DatabaseError):
                con.execute("DELETE FROM reviews WHERE hit_id=?", (hid,))
            con.rollback()
            n, = con.execute("SELECT COUNT(*) FROM reviews WHERE hit_id=?", (hid,)).fetchone()
            self.assertEqual(n, 1)
        finally:
            con.close()

    def test_mi(self):
        code, m = self.get("/api/mi")
        self.assertEqual(code, 200)
        for k in ("decisions", "approvals", "returns", "overrides", "by_reviewer", "buckets", "audit_rows"):
            self.assertIn(k, m)
        self.assertEqual(set(m["buckets"]), BUCKETS)
        self.assertEqual(sum(m["buckets"].values()), HITS)

    # ---------------------------------------------------------------- LLM court

    def test_court_unavailable_without_key(self):
        code, body = self.post("/api/court", {"hit_id": self.hit_ids[0], "role": "prosecution", "record_ids": [], "prior": None})
        self.assertIn(code, (501, 503))
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main()
