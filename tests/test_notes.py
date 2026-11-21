"""Stub contract for engine.notes. Made-up notes only."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "system"))

from engine.notes import NoteFacts, parse  # noqa: E402


class ParseStubTest(unittest.TestCase):
    def test_verification_wording_stays_unknown(self):
        note = {
            "note_id": "NOTE-TEST-1",
            "created_at": "2020-01-02",
            "text": (
                "Acme Check validated identity verification of Ada Example, "
                "born 2 January 1990, document issued in Portugal."
            ),
        }
        facts = parse(note)
        self.assertIsInstance(facts, NoteFacts)
        self.assertFalse(facts.verified)
        self.assertFalse(facts.rejected)
        self.assertIsNone(facts.name)
        self.assertIsNone(facts.dob)
        self.assertIsNone(facts.doc_country)
        self.assertEqual(facts.lived_in, [])
        self.assertIsNone(facts.date)

    def test_failure_wording_is_not_marked_rejected_yet(self):
        # The stub must not guess. Unknown stays unknown.
        facts = parse({"text": "Provider rejected the check; it expired."})
        self.assertFalse(facts.verified)
        self.assertFalse(facts.rejected)

    def test_string_note_and_repeat_calls(self):
        text = "She used to live in Lisbon."
        self.assertEqual(parse(text), parse(text))


if __name__ == "__main__":
    unittest.main()
