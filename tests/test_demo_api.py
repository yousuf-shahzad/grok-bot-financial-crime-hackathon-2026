"""JSON API checks for the Case Review demo server (demo/app.py).

Starts demo/app.py on the invented fixture folder tests/fixtures/rare, offline and with no LLM
(every *_API_KEY blanked and LLM_DISABLE=1, as in test_rare_cases.py), on a free local port,
then checks the JSON API. Run: py -3 -X utf8 -m unittest discover -s tests
"""
from __future__ import annotations

import json
import os
import socket
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


def _count_lines(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


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
        env["CASE_REVIEW_DB"] = os.path.join(cls.tmp.name, "reviews.sqlite")  # used once the review API lands
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

    @classmethod
    def get(cls, path: str):
        try:
            with urllib.request.urlopen(cls.base + path, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read().decode("utf-8") or "{}")

    def test_status_ready(self):
        code, body = self.get("/api/status")
        self.assertEqual(code, 200)
        self.assertIs(body["ready"], True)
        self.assertIsInstance(body.get("status"), str)

    def test_summary_counts(self):
        code, s = self.get("/api/summary")
        self.assertEqual(code, 200)
        hits = _count_lines(os.path.join(FIXTURE, "hits.jsonl"))
        self.assertEqual(s["hits"], hits)
        self.assertEqual(s["alerts"], _count_lines(os.path.join(FIXTURE, "alerts.jsonl")))
        self.assertTrue(set(s["by_decision"]) <= DECISIONS, s["by_decision"])
        self.assertEqual(sum(n for codes in s["by_decision"].values() for n in codes.values()), hits)

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


if __name__ == "__main__":
    unittest.main()
