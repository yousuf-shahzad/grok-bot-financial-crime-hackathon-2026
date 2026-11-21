"""demo/court_llm.py with a stubbed engine.llm. Made-up case and IDs only; no network."""
from __future__ import annotations

import json
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "demo"))

import court_llm  # noqa: E402

CASE = {
    "hit": {"name": "Pat Testman", "aliases": [], "births": [{"years": [1980], "source": "H-T1"}],
            "countries": ["Freedonia"], "listing_kind": "a politically exposed person",
            "earliest_report": None, "deceased": None, "missing": []},
    "customer": {"person_id": "CUS-T1", "record_ids": ["CUS-T1"], "verified_name": "Pat Testman",
                 "names": ["Pat Testman"], "verified_dob": "1980-05-02", "dobs": [], "countries": ["Freedonia"]},
    "rules": {"recommendation": "SAME_ENTITY", "reason_code": "NAME_DOB_MATCH", "reason": "x. y.",
              "evidence": ["CUS-T1", "KYC-T1"], "prosecution": [], "defence": []},
    "sop": "ignored, court_llm uses its own SOP text",
}
RECORDS = [{"id": "NOTE-T1", "kind": "note", "text": "Invented note text."},
           {"id": "NOTE-T1", "kind": "note", "text": "duplicate dropped"},
           {"id": "", "kind": "note", "text": "no id dropped"}]


class Stub:
    def __init__(self, answer, available=True):
        self.answer, self._available, self.calls = answer, available, []

    def available(self):
        return self._available

    def describe(self):
        return "stub / test-model"

    def ask_json(self, system, user, schema, name="answer", timeout=45.0):
        self.calls.append({"system": system, "user": json.loads(user), "schema": schema, "name": name})
        return self.answer


def advocate(points, position="p."):
    return {"position": position, "points": points, "gaps": ["g"]}


class CourtTests(unittest.TestCase):
    def setUp(self):
        self._orig = court_llm.llm

    def tearDown(self):
        court_llm.llm = self._orig

    def use(self, answer, available=True):
        court_llm.llm = Stub(answer, available)
        return court_llm.llm

    def test_no_key(self):
        self.use(None, available=False)
        self.assertEqual(court_llm.argue("defence", CASE, RECORDS), {"error": "no LLM key configured"})

    def test_bad_role_and_missing_prior(self):
        self.use({})
        self.assertIn("error", court_llm.argue("judge", CASE, RECORDS))
        self.assertIn("error", court_llm.argue("adjudicator", CASE, RECORDS, prior=None))

    def test_model_failure(self):
        self.use(None)
        self.assertEqual(court_llm.argue("prosecution", CASE, RECORDS), {"error": "model call failed"})

    def test_drops_uncited_ids_and_sends_only_ticked_records(self):
        stub = self.use(advocate([{"claim": "Names agree.", "evidence_ids": ["NOTE-T1", "CUS-T1", "KYC-FAKE"]},
                                  {"claim": "", "evidence_ids": ["NOTE-T1"]}]))
        out = court_llm.argue("prosecution", CASE, RECORDS)
        self.assertEqual(out["role"], "prosecution")
        self.assertEqual(out["points"], [{"claim": "Names agree.", "evidence_ids": ["CUS-T1", "NOTE-T1"]}])
        sent = stub.calls[0]["user"]
        self.assertEqual([r["id"] for r in sent["records"]], ["NOTE-T1"])
        self.assertNotIn("sop", sent["case"])
        self.assertEqual(stub.calls[0]["system"], court_llm.PROMPTS["prosecution"])
        self.assertIs(stub.calls[0]["schema"], court_llm.ADVOCATE_SCHEMA)

    def test_adjudicator_shape(self):
        prior = {"prosecution": advocate([{"claim": "a", "evidence_ids": ["CUS-T1"]}]),
                 "defence": advocate([{"claim": "b", "evidence_ids": ["NOTE-T1"]}])}
        self.use({"position": "Clear.", "points": [], "gaps": [], "summary": "s1. s2. s3.",
                  "suggested_disposition": "CLEAR", "confidence": "high",
                  "what_would_settle": ["x"], "sop_rule": "every date of birth contradicted"})
        out = court_llm.argue("adjudicator", CASE, RECORDS, prior=prior)
        self.assertEqual((out["suggested_disposition"], out["confidence"]), ("CLEAR", "high"))
        for k in ("summary", "what_would_settle", "sop_rule", "position", "points", "gaps"):
            self.assertIn(k, out)

    def test_adjudicator_cannot_clear_without_cited_defence(self):
        prior = {"prosecution": advocate([{"claim": "a", "evidence_ids": ["CUS-T1"]}]),
                 "defence": advocate([{"claim": "made up", "evidence_ids": ["KYC-INVENTED"]}])}
        self.use({"position": "Clear.", "points": [], "gaps": [], "summary": "s.",
                  "suggested_disposition": "CLEAR", "confidence": "high",
                  "what_would_settle": [], "sop_rule": "r"})
        out = court_llm.argue("adjudicator", CASE, RECORDS, prior=prior)
        self.assertEqual((out["suggested_disposition"], out["confidence"]), ("ESCALATE", "low"))

    def test_adjudicator_cannot_confirm_without_cited_prosecution(self):
        prior = {"prosecution": advocate([{"claim": "trust me", "evidence_ids": []}]),
                 "defence": advocate([{"claim": "b", "evidence_ids": ["NOTE-T1"]}])}
        self.use({"position": "Confirm.", "points": [], "gaps": [], "summary": "s.",
                  "suggested_disposition": "CONFIRM", "confidence": "medium",
                  "what_would_settle": [], "sop_rule": "r"})
        out = court_llm.argue("adjudicator", CASE, RECORDS, prior=prior)
        self.assertEqual(out["suggested_disposition"], "ESCALATE")

    def test_unknown_enum_becomes_escalate_low(self):
        prior = {"prosecution": advocate([]), "defence": advocate([])}
        self.use({"position": "", "points": [], "gaps": [], "summary": "", "suggested_disposition": "MAYBE",
                  "confidence": "certain", "what_would_settle": [], "sop_rule": ""})
        out = court_llm.argue("adjudicator", CASE, RECORDS, prior=prior)
        self.assertEqual((out["suggested_disposition"], out["confidence"]), ("ESCALATE", "low"))

    def test_schemas_are_strict(self):
        for schema in (court_llm.ADVOCATE_SCHEMA, court_llm.ADJUDICATOR_SCHEMA):
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(sorted(schema["required"]), sorted(schema["properties"]))


if __name__ == "__main__":
    unittest.main()
