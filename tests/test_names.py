"""Unit tests for system/engine/names.py (SOP principle 8). Made-up names only.

Run: py -3 -X utf8 -m unittest discover -s tests
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "system"))

from engine import names  # noqa: E402


class PartsTest(unittest.TestCase):
    def setUp(self):
        names.use_variants(None)

    def test_case_accents_punctuation(self):
        self.assertEqual(names.parts("Zoë-Renée  DÜRRWALD"), ["zoe", "renee", "durrwald"])

    def test_special_letters_folded(self):
        self.assertEqual(names.parts("Østby Strauß Łukowicz"), ["ostby", "strauss", "lukowicz"])

    def test_brackets_dropped(self):
        self.assertEqual(names.parts("Corvin Talbridge (also Cory) [old]"), ["corvin", "talbridge"])
        self.assertEqual(names.parts("Corvin Talbridge (nickname"), ["corvin", "talbridge"])

    def test_initials_dropped(self):
        self.assertEqual(names.parts("Q. R. Pemberly"), ["pemberly"])
        self.assertEqual(names.parts("Ansel J Morrow"), ["ansel", "morrow"])

    def test_apostrophe_joins(self):
        self.assertEqual(names.parts("Fenna O'Dallow"), ["fenna", "odallow"])

    def test_placeholders(self):
        for raw in ["N/A", "NA", "TEST", "Unknown", "XXX", "none", "12345", "xxxx"]:
            self.assertEqual(names.parts(raw), [], raw)
        self.assertEqual(names.parts("Test Unknown Brindle 007"), ["brindle"])

    def test_distinct_once_order_kept(self):
        self.assertEqual(names.parts("Lio Kasterman Lio"), ["lio", "kasterman"])

    def test_honorifics_individual_only(self):
        self.assertEqual(names.parts("Dr. Mrs Velma Quist"), ["velma", "quist"])
        self.assertEqual(names.real_part_count("Mr Quist"), 1)

    def test_company_legal_forms(self):
        self.assertEqual(names.parts("Brightvane Holdings Ltd.", company=True), ["brightvane", "holdings"])
        self.assertEqual(names.parts("Orrin & Tamm GmbH & Co. KG", company=True), ["orrin", "tamm"])
        # not dropped for individuals
        self.assertIn("ltd", names.parts("Brightvane Ltd"))

    def test_none_and_non_string(self):
        self.assertEqual(names.parts(None), [])
        self.assertEqual(names.parts(""), [])
        self.assertEqual(names.real_part_count(None), 0)

    def test_real_part_count(self):
        self.assertEqual(names.real_part_count("Wren Hollister-Vane"), 3)
        self.assertEqual(names.real_part_count("Wren"), 1)
        self.assertEqual(names.real_part_count("W. UNKNOWN"), 0)


class PartsMatchTest(unittest.TestCase):
    def setUp(self):
        names.use_variants(None)

    def test_identical_and_case(self):
        self.assertTrue(names.parts_match("Brindle", "brindle"))
        self.assertTrue(names.parts_match("ödo", "Odo"))

    def test_short_parts_identical_only(self):
        self.assertFalse(names.parts_match("ado", "abo"))
        self.assertFalse(names.parts_match("kim", "kima"))  # shorter is 3 letters

    def test_four_to_six_one_edit(self):
        self.assertTrue(names.parts_match("marlo", "marla"))     # change
        self.assertTrue(names.parts_match("brin", "brinn"))      # add, shorter = 4
        self.assertFalse(names.parts_match("marlo", "morla"))    # 2 edits
        self.assertTrue(names.parts_match("quentz", "quents"))   # 6 letters, 1 edit

    def test_swap_is_two_edits(self):
        self.assertFalse(names.parts_match("talmer", "tlamer"))  # 6 letters, swap = 2
        self.assertTrue(names.parts_match("talmerson", "tlamerson"))  # 9 letters, 2 allowed

    def test_seven_plus_two_edits(self):
        self.assertTrue(names.parts_match("pemberly", "pembrely"))
        self.assertTrue(names.parts_match("castellow", "castelo"))   # shorter 7, 2 edits
        self.assertFalse(names.parts_match("castellow", "kastelo"))  # 3 edits

    def test_shorter_decides_allowance(self):
        # shorter is 6 letters -> 1 edit, even though the other has 8
        self.assertFalse(names.parts_match("hollin", "hollings"))
        self.assertTrue(names.parts_match("hollin", "hollins"))

    def test_builtin_variants(self):
        self.assertTrue(names.parts_match("Muhammad", "Mohamed"))
        self.assertTrue(names.parts_match("Tom", "Thomas"))
        self.assertTrue(names.parts_match("Bill", "William"))
        self.assertFalse(names.parts_match("Tom", "Bill"))

    def test_empty(self):
        self.assertFalse(names.parts_match("", "abcd"))
        self.assertFalse(names.parts_match(None, None))


class NamesAgreeTest(unittest.TestCase):
    def setUp(self):
        names.use_variants(None)

    def test_two_parts_match(self):
        self.assertTrue(names.names_agree("Corvin Ashby Talbridge", "Talbridge Corvin Mott"))

    def test_token_order_ignored(self):
        self.assertTrue(names.names_agree("TALBRIDGE, Corvin", "Corvin Talbridge"))

    def test_every_part_of_shorter(self):
        self.assertTrue(names.names_agree("Talbridge", "Corvin Ashby Talbridge"))
        self.assertTrue(names.names_agree("Corvin A. Talbridge", "Corvin Talbridge Ashby"))

    def test_one_of_two_is_not_enough(self):
        self.assertFalse(names.names_agree("Corvin Talbridge", "Corvin Pellworth"))
        self.assertFalse(names.names_agree("Corvin Talbridge", "Ashby Pellworth Talbridge"))

    def test_typos_and_nicknames(self):
        self.assertTrue(names.names_agree("Tom Pemberly", "Thomas Pembrely"))
        self.assertTrue(names.names_agree("Wren Hollister", "Wren Holister"))

    def test_joined_or_split(self):
        self.assertTrue(names.names_agree("Abdulsalam", "Abdul Salam"))
        self.assertTrue(names.names_agree("Abdul Salam", "Abdulsalam"))
        self.assertTrue(names.names_agree("Vanderhoek Ilse", "Ilse van der Hoek"))
        # the joined part counts as ONE part: one joined match alone is not "two parts"
        self.assertFalse(names.names_agree("Abdulsalam Pellworth", "Abdul Salam Corvane"))

    def test_hyphenated(self):
        self.assertTrue(names.names_agree("Jean-Luc Varenne", "Jeanluc Varenne"))

    def test_accents_brackets_initials(self):
        self.assertTrue(names.names_agree("Zoë R. Dürrwald (Zee)", "ZOE DURRWALD"))

    def test_placeholders_never_agree(self):
        self.assertFalse(names.names_agree("UNKNOWN", "Corvin Talbridge"))
        self.assertFalse(names.names_agree("N/A", "N/A"))
        self.assertFalse(names.names_agree(None, "Corvin Talbridge"))
        self.assertFalse(names.names_agree("", ""))

    def test_single_part_alias_agrees(self):
        self.assertTrue(names.names_agree("Corvin Talbridge", "Corvin"))

    def test_symmetric(self):
        pairs = [("Corvin Talbridge", "Talbridge"), ("Abdulsalam Mott", "Abdul Salam Mott"),
                 ("Wren Hollister", "Ansel Hollister")]
        for a, b in pairs:
            self.assertEqual(names.names_agree(a, b), names.names_agree(b, a), (a, b))

    def test_company(self):
        self.assertTrue(names.names_agree("Brightvane Ltd", "Brightvane Limited", company=True))
        self.assertTrue(names.names_agree("Orrin Tamm Holdings PLC", "Orrin-Tamm Holdings", company=True))
        self.assertFalse(names.names_agree("Brightvane Ltd", "Duskwater Ltd", company=True))
        # as individuals "ltd" would be a matching part on its own
        self.assertTrue(names.names_agree("Brightvane Ltd", "Brightvane Ltd Duskwater"))

    def test_deterministic(self):
        r1 = [names.names_agree("Corvin Ashby", x) for x in ["Ashby", "Corvine Ashbey", "Pell"]]
        names.use_variants(None)
        r2 = [names.names_agree("Corvin Ashby", x) for x in ["Ashby", "Corvine Ashbey", "Pell"]]
        self.assertEqual(r1, r2)


class NamesContradictTest(unittest.TestCase):
    def setUp(self):
        names.use_variants(None)

    def test_clear_mismatch(self):
        self.assertTrue(names.names_contradict("Corvin Talbridge", ["Duskan Pellworth", "D. Pell"]))

    def test_any_agreeing_name_blocks(self):
        self.assertFalse(names.names_contradict("Corvin Talbridge", ["Duskan Pellworth", "Corvin Talbrige"]))

    def test_verified_needs_two_parts(self):
        self.assertFalse(names.names_contradict("Talbridge", ["Duskan Pellworth"]))
        self.assertFalse(names.names_contradict("Mr Talbridge", ["Duskan Pellworth"]))

    def test_placeholder_hit_names_are_unknown(self):
        self.assertFalse(names.names_contradict("Corvin Talbridge", ["UNKNOWN", "N/A"]))
        self.assertFalse(names.names_contradict("Corvin Talbridge", []))
        self.assertFalse(names.names_contradict(None, ["Duskan Pellworth"]))


class UseVariantsTest(unittest.TestCase):
    def tearDown(self):
        names.use_variants(None)

    def test_list_of_lists(self):
        names.use_variants([["quillon", "quill", "quin"]])
        self.assertTrue(names.parts_match("Quin", "Quillon"))
        self.assertFalse(names.parts_match("Tom", "Thomas"))  # file replaces built-ins

    def test_dict_with_variants_and_legal_forms(self):
        names.use_variants({"variants": ["quillon, quill", "brannoc, bran"],
                            "legal_forms": ["ltd", "zorg"]})
        self.assertTrue(names.parts_match("bran", "Brannoc"))
        self.assertEqual(names.parts("Brightvane Zorg GmbH", company=True), ["brightvane", "gmbh"])

    def test_dict_name_to_list(self):
        names.use_variants({"quillon": ["quill", "quin"]})
        self.assertTrue(names.parts_match("quill", "quin"))

    def test_variant_forms(self):
        names.use_variants([["Quillon", "quin"], ["quin", "quinto"]])
        self.assertEqual(names.variant_forms("Quin"), ["quillon", "quin", "quinto"])
        self.assertEqual(names.variant_forms("brannoc"), ["brannoc"])
        self.assertEqual(names.variant_forms(""), [])

    def test_none_restores_builtins(self):
        names.use_variants([["quillon", "quin"]])
        names.use_variants(None)
        self.assertTrue(names.parts_match("Tom", "Thomas"))
        self.assertFalse(names.parts_match("Quin", "Quillon"))


if __name__ == "__main__":
    unittest.main()