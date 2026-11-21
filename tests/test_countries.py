"""Unit tests for system/engine/countries.py (SPEC.md sections 2-3, PLAN.md 5C). Made-up values only.

Run: py -3 -X utf8 -m unittest discover -s tests
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "system"))

from engine import countries  # noqa: E402

N = countries.normalise


class NormaliseNamesTest(unittest.TestCase):
    def test_canonical_names(self):
        self.assertEqual(N("France"), "France")
        self.assertEqual(N("  germany "), "Germany")
        self.assertEqual(N("UNITED KINGDOM"), "United Kingdom")

    def test_accents_punctuation_and_article(self):
        self.assertEqual(N("Côte d’Ivoire"), N("Ivory Coast"))
        self.assertEqual(N("The Netherlands"), "Netherlands")
        self.assertEqual(N("Trinidad & Tobago"), N("Trinidad and Tobago"))
        self.assertEqual(N("St. Lucia"), N("Saint Lucia"))

    def test_alternative_names(self):
        self.assertEqual(N("Holland"), "Netherlands")
        self.assertEqual(N("Czechia"), N("Czech Republic"))
        self.assertEqual(N("Russian Federation"), "Russia")
        self.assertEqual(N("Burma"), "Myanmar")
        self.assertEqual(N("Türkiye"), "Turkey")

    def test_uk_constituent_countries(self):
        for s in ["England", "Scotland", "Wales", "Northern Ireland", "Great Britain", "UK", "U.K."]:
            self.assertEqual(N(s), "United Kingdom", s)


class NormaliseCodesTest(unittest.TestCase):
    def test_iso2(self):
        self.assertEqual(N("FR"), "France")
        self.assertEqual(N("DE"), "Germany")
        self.assertEqual(N("GB"), "United Kingdom")
        self.assertEqual(N("NG"), "Nigeria")

    def test_iso3(self):
        self.assertEqual(N("FRA"), "France")
        self.assertEqual(N("DEU"), "Germany")
        self.assertEqual(N("GBR"), "United Kingdom")
        self.assertEqual(N("USA"), "United States")
        self.assertEqual(N("U.S.A."), "United States")

    def test_names_and_codes_agree(self):
        for name, a2, a3 in [("Portugal", "PT", "PRT"), ("Kenya", "KE", "KEN"),
                             ("Japan", "JP", "JPN"), ("Brazil", "BR", "BRA")]:
            self.assertEqual(N(a2), N(name))
            self.assertEqual(N(a3), N(name))


class NormaliseNationalitiesTest(unittest.TestCase):
    def test_nationalities(self):
        self.assertEqual(N("British"), "United Kingdom")
        self.assertEqual(N("Nigerian"), "Nigeria")
        self.assertEqual(N("French"), "France")
        self.assertEqual(N("Dutch"), "Netherlands")
        self.assertEqual(N("Swiss"), "Switzerland")
        self.assertEqual(N("Filipino"), "Philippines")
        self.assertEqual(N("Emirati"), "United Arab Emirates")
        self.assertEqual(N("american"), "United States")


class CodesNeedCapitalsTest(unittest.TestCase):
    def test_lowercase_short_words_are_not_codes(self):
        for s in ["in", "and", "is", "to", "at", "it", "be", "no", "id", "gb", "us", "ind", "fra"]:
            self.assertIsNone(N(s), s)

    def test_mixed_case_short_words_are_not_codes(self):
        for s in ["In", "And", "Is", "To", "Gb", "Usa"]:
            self.assertIsNone(N(s), s)

    def test_capitalised_codes_still_map(self):
        self.assertEqual(N("GB"), "United Kingdom")
        self.assertEqual(N("US"), "United States")
        self.assertEqual(N("IND"), "India")
        self.assertEqual(N("IN"), "India")
        self.assertEqual(N("AND"), "Andorra")
        self.assertEqual(N(" U.K. "), "United Kingdom")
        self.assertEqual(N("U.S.A."), "United States")

    def test_capital_id_is_ambiguous(self):
        self.assertIsNone(N("ID"))
        self.assertEqual(N("IDN"), "Indonesia")
        self.assertEqual(N("Indonesia"), "Indonesia")
        self.assertEqual(N("indonesian"), "Indonesia")

    def test_names_unaffected_by_case(self):
        self.assertEqual(N("india"), "India")
        self.assertEqual(N("andorra"), "Andorra")
        self.assertEqual(N("PERU"), "Peru")
        self.assertEqual(N("united states"), "United States")

    def test_from_address_lowercase_word(self):
        self.assertIsNone(countries.from_address("Flat 2, Kestrel House, in"))
        self.assertEqual(countries.from_address("Flat 2, Kestrel House, GB"), "United Kingdom")


class TerritoriesTest(unittest.TestCase):
    def test_territories_are_their_own_country(self):
        self.assertEqual(N("Hong Kong"), "Hong Kong")
        self.assertNotEqual(N("Hong Kong"), N("China"))
        self.assertEqual(N("Puerto Rico"), "Puerto Rico")
        self.assertNotEqual(N("Puerto Rico"), N("United States"))
        self.assertEqual(N("Jersey"), "Jersey")
        self.assertNotEqual(N("Jersey"), N("United Kingdom"))
        self.assertEqual(N("Cayman Islands"), "Cayman Islands")
        self.assertEqual(N("HK"), "Hong Kong")


class NormaliseUnknownTest(unittest.TestCase):
    def test_not_countries(self):
        for s in ["International", "Europe", "EUROPE", "Global", "Worldwide"]:
            self.assertIsNone(N(s), s)

    def test_unknown_input_returns_none(self):
        for s in [None, "", "   ", "Unknown", "N/A", "none", "Atlantis", "Zembla",
                  "QQ", "XYZ", "12345", "London"]:
            self.assertIsNone(N(s), s)


class FromAddressTest(unittest.TestCase):
    def test_last_part(self):
        self.assertEqual(countries.from_address("12 Fernhollow Lane, Brackwater, United Kingdom"),
                         "United Kingdom")
        self.assertEqual(countries.from_address("4 Rue des Ormes, Lyon, FR"), "France")
        self.assertEqual(countries.from_address("Kestrel Tower, Dubai, UAE"), "United Arab Emirates")

    def test_postcode_in_last_part(self):
        self.assertEqual(countries.from_address("Ahornweg 3, 10999 Germany"), "Germany")
        self.assertEqual(countries.from_address("Ahornweg 3, Germany 10999"), "Germany")

    def test_single_part(self):
        self.assertEqual(countries.from_address("Portugal"), "Portugal")

    def test_only_last_part_counts(self):
        # a country earlier in the address is not the address's country
        self.assertIsNone(countries.from_address("France Street 9, Springvale"))

    def test_unknown(self):
        self.assertIsNone(countries.from_address(None))
        self.assertIsNone(countries.from_address(""))
        self.assertIsNone(countries.from_address("8 Mill Road, Brackwater"))
        self.assertIsNone(countries.from_address("PO Box 1, International"))


if __name__ == "__main__":
    unittest.main()