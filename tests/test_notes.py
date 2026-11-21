"""engine.notes on made-up notes. No dev records."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "system"))

from engine.model import PartialDate  # noqa: E402
from engine.notes import NoteFacts, parse  # noqa: E402


class NotesTest(unittest.TestCase):
    def test_full_verification_sentence(self):
        facts = parse({
            "note_id": "NOTE-TEST-1",
            "created_at": "2020-01-02",
            "text": (
                "Acme Check validated identity verification of Ada Example, "
                "born 2 January 1990, document issued in Portugal. "
                "She used to live in Nigeria."
            ),
        })
        self.assertIsInstance(facts, NoteFacts)
        self.assertTrue(facts.verified)
        self.assertFalse(facts.rejected)
        self.assertEqual(facts.name, "Ada Example")
        self.assertEqual(facts.dob, PartialDate(1990, 1, 2))
        self.assertEqual(facts.doc_country, "Portugal")
        self.assertEqual(facts.lived_in, ["Nigeria"])
        self.assertEqual(facts.date, "2020-01-02")

    def test_dob_and_document_from_wording(self):
        facts = parse(
            "Provider completed identity verification of Musa Okonkwo "
            "DOB 19/05/2004 document from Nigeria."
        )
        self.assertTrue(facts.verified)
        self.assertEqual(facts.name, "Musa Okonkwo")
        self.assertEqual(facts.dob, PartialDate(2004, 5, 19))
        self.assertEqual(facts.doc_country, "Nigeria")
        self.assertIsNone(facts.date)

    def test_partial_sentence_stays_unknown(self):
        facts = parse("We validated identity verification of Ada Example yesterday.")
        self.assertFalse(facts.verified)
        self.assertFalse(facts.rejected)
        self.assertIsNone(facts.name)
        self.assertIsNone(facts.dob)

    def test_failure_is_not_evidence(self):
        facts = parse({
            "created_at": "2019-04-01",
            "text": "The provider could not verify Ada Example, born 1 January 1990.",
        })
        self.assertTrue(facts.rejected)
        self.assertFalse(facts.verified)
        self.assertIsNone(facts.name)
        self.assertIsNone(facts.dob)
        self.assertEqual(facts.date, "2019-04-01")

    def test_expired_and_rejected(self):
        self.assertTrue(parse("The check expired before review.").rejected)
        self.assertTrue(parse("Identity check was rejected.").rejected)

    def test_not_expired_is_not_a_failure(self):
        facts = parse("The document has not expired and has not been rejected.")
        self.assertFalse(facts.rejected)
        self.assertFalse(facts.verified)

    def test_success_and_failure_together_stay_unknown(self):
        facts = parse(
            "First the check was rejected. Later Acme completed identity verification "
            "of Ada Example, born 2 January 1990, document issued in Portugal. "
            "She previously lived in France."
        )
        self.assertFalse(facts.verified)
        self.assertFalse(facts.rejected)
        self.assertIsNone(facts.name)
        self.assertEqual(facts.lived_in, ["France"])

    def test_moved_from_includes_both_places(self):
        facts = parse("He moved from Portugal to France in 2011 and used to live in Kenya.")
        self.assertEqual(facts.lived_in, ["Portugal", "France", "Kenya"])
        self.assertFalse(facts.verified)

    def test_international_is_not_a_place(self):
        facts = parse("She formerly lived in International.")
        self.assertEqual(facts.lived_in, [])

    def test_unrelated_note_is_unknown(self):
        facts = parse({"text": "Customer asked about a card fee.", "created_at": "2021-06-01"})
        self.assertFalse(facts.verified)
        self.assertFalse(facts.rejected)
        self.assertEqual(facts.lived_in, [])
        self.assertEqual(facts.date, "2021-06-01")

    def test_repeat_calls_match(self):
        text = "Used to live in Spain."
        self.assertEqual(parse(text), parse(text))


if __name__ == "__main__":
    unittest.main()
