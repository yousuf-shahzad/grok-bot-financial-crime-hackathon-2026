"""Stub contract for engine.hitfacts. Made-up rows only."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "system"))

from engine.hitfacts import extract  # noqa: E402
from engine.model import HitProfile  # noqa: E402


class ExtractStubTest(unittest.TestCase):
    def test_returns_hit_profile_with_no_facts(self):
        hit = {
            "hit_id": "H-TEST-1",
            "alert_id": "A-TEST-1",
            "entity_type": "Individual",
            "name": "Ada Example",
            "aliases": ["A. Example"],
            "dobs": ["1970"],
            "countries": ["Portugal"],
            "profile_notes": "Aged 40 in March 2010.",
        }
        profile = extract(hit, data=object())
        self.assertIsInstance(profile, HitProfile)
        self.assertEqual(profile.hit_id, "H-TEST-1")
        self.assertEqual(profile.alert_id, "A-TEST-1")
        self.assertEqual(profile.entity_type, "Individual")
        self.assertEqual(profile.names, [])
        self.assertEqual(profile.births, [])
        self.assertEqual(profile.countries, [])
        self.assertIsNone(profile.earliest_report)
        self.assertIsNone(profile.deceased)
        self.assertIsNone(profile.incorporated)
        self.assertEqual(profile.listing_kind, "")
        self.assertIn("no date of birth in dobs, notes or search results", profile.missing)

    def test_missing_fields_stay_blank(self):
        profile = extract({}, data=None)
        self.assertEqual(profile.hit_id, "")
        self.assertEqual(profile.alert_id, "")
        self.assertEqual(profile.entity_type, "")

    def test_two_calls_match(self):
        hit = {"hit_id": "H-TEST-2", "alert_id": "A-TEST-2", "entity_type": "Company"}
        self.assertEqual(extract(hit, None), extract(hit, None))


if __name__ == "__main__":
    unittest.main()
