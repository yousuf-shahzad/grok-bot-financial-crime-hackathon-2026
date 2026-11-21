"""Unit tests for system/engine/dates.py (SPEC.md sections 2-4, PLAN.md 5C). Made-up values only.

Run: py -3 -X utf8 -m unittest discover -s tests
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "system"))

from engine import dates  # noqa: E402
from engine.model import BirthClaim, PartialDate as PD  # noqa: E402


def claim(years, month=None, day=None):
    return BirthClaim(years=tuple(years), month=month, day=day, source="H-TEST")


class ParseTest(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(dates.parse("1987-03-09"), PD(1987, 3, 9))
        self.assertEqual(dates.parse(" 1987-3-9 "), PD(1987, 3, 9))
        self.assertEqual(dates.parse("1987-03-09T00:00:00"), PD(1987, 3, 9))

    def test_day_first_slash(self):
        # PLAN.md 5C: numeric d/m/y is always day first
        self.assertEqual(dates.parse("19/05/2004"), PD(2004, 5, 19))
        self.assertEqual(dates.parse("03/04/2004"), PD(2004, 4, 3))
        self.assertEqual(dates.parse("7/1/1990"), PD(1990, 1, 7))

    def test_impossible_slash_date_unknown(self):
        self.assertIsNone(dates.parse("05/19/2004"))   # no month 19, never swapped
        self.assertIsNone(dates.parse("31/02/2004"))

    def test_month_d_yyyy(self):
        self.assertEqual(dates.parse("March 9, 1987"), PD(1987, 3, 9))
        self.assertEqual(dates.parse("Sept 30 1975"), PD(1975, 9, 30))
        self.assertEqual(dates.parse("Dec. 1, 2001"), PD(2001, 12, 1))

    def test_d_month_yyyy(self):
        self.assertEqual(dates.parse("9 March 1987"), PD(1987, 3, 9))
        self.assertEqual(dates.parse("1st January 2000"), PD(2000, 1, 1))
        self.assertEqual(dates.parse("21 nov 1966"), PD(1966, 11, 21))

    def test_partial(self):
        self.assertEqual(dates.parse("1987"), PD(1987, None, None))
        self.assertEqual(dates.parse("1987-03"), PD(1987, 3, None))
        self.assertEqual(dates.parse("March 1987"), PD(1987, 3, None))
        self.assertEqual(dates.parse("Mar, 1987"), PD(1987, 3, None))

    def test_unknown_parts_never_filled(self):
        d = dates.parse("1987")
        self.assertIsNone(d.month)
        self.assertIsNone(d.day)

    def test_garbage_and_invalid(self):
        for s in [None, "", "   ", "unknown", "N/A", "87", "1987-13-01", "1987-02-30",
                  "Smarch 3, 1987", "0999", "12345"]:
            self.assertIsNone(dates.parse(s), s)

    def test_partialdate_passthrough(self):
        d = PD(1990, 1, None)
        self.assertIs(dates.parse(d), d)

    def test_leap_day(self):
        self.assertEqual(dates.parse("29/02/2000"), PD(2000, 2, 29))
        self.assertIsNone(dates.parse("29/02/1900"))


class SameInSharedPartsTest(unittest.TestCase):
    def test_equal_and_partial(self):
        self.assertTrue(dates.same_in_shared_parts(PD(1980, 1, 2), PD(1980, 1, 2)))
        self.assertTrue(dates.same_in_shared_parts(PD(1980), PD(1980, 1, 2)))
        self.assertTrue(dates.same_in_shared_parts(PD(1980, 1), PD(1980, 1, 2)))

    def test_differs(self):
        self.assertFalse(dates.same_in_shared_parts(PD(1980, 1, 2), PD(1980, 1, 3)))
        self.assertFalse(dates.same_in_shared_parts(PD(1980, 1), PD(1980, 2, 2)))
        self.assertFalse(dates.same_in_shared_parts(PD(1981), PD(1980, 1, 2)))

    def test_missing_fails_nothing(self):
        self.assertTrue(dates.same_in_shared_parts(None, PD(1980, 1, 2)))
        self.assertTrue(dates.same_in_shared_parts(PD(1980), None))


class BirthAgreesTest(unittest.TestCase):
    def test_year_in_claim_years(self):
        self.assertTrue(dates.birth_agrees(PD(1974, 6, 1), claim([1973, 1974])))
        self.assertTrue(dates.birth_agrees(PD(1973), claim([1973, 1974])))

    def test_year_alone_agrees_with_full_date(self):
        self.assertTrue(dates.birth_agrees(PD(1980), claim([1980], 1, 2)))
        self.assertTrue(dates.birth_agrees(PD(1980, 1, 2), claim([1980])))

    def test_every_shared_part_equal(self):
        self.assertTrue(dates.birth_agrees(PD(1980, 1, 2), claim([1980], 1, 2)))
        self.assertTrue(dates.birth_agrees(PD(1980, 1), claim([1980], 1, 2)))
        self.assertFalse(dates.birth_agrees(PD(1980, 1, 2), claim([1980], 1, 3)))
        self.assertFalse(dates.birth_agrees(PD(1980, 2, 2), claim([1980], 1, 2)))

    def test_one_year_off_is_not_agreement(self):
        self.assertFalse(dates.birth_agrees(PD(1981), claim([1980])))

    def test_unknown_never_agrees(self):
        self.assertFalse(dates.birth_agrees(None, claim([1980])))
        self.assertFalse(dates.birth_agrees(PD(None), claim([1980])))
        self.assertFalse(dates.birth_agrees(PD(1980), claim([])))


class BirthContradictedTest(unittest.TestCase):
    def test_more_than_one_year_outside(self):
        self.assertTrue(dates.birth_contradicted(PD(1982), claim([1980])))
        self.assertTrue(dates.birth_contradicted(PD(1971), claim([1973, 1974])))
        self.assertTrue(dates.birth_contradicted(PD(1976, 5, 5), claim([1973, 1974])))

    def test_within_one_year_not_contradicted(self):
        self.assertFalse(dates.birth_contradicted(PD(1981), claim([1980])))
        self.assertFalse(dates.birth_contradicted(PD(1979, 12, 31), claim([1980], 1, 1)))
        self.assertFalse(dates.birth_contradicted(PD(1975), claim([1973, 1974])))
        self.assertFalse(dates.birth_contradicted(PD(1972), claim([1973, 1974])))

    def test_same_year_month_or_day_differs(self):
        self.assertTrue(dates.birth_contradicted(PD(1980, 2), claim([1980], 3)))
        self.assertTrue(dates.birth_contradicted(PD(1980, 3, 4), claim([1980], 3, 5)))

    def test_same_year_month_missing_not_contradicted(self):
        self.assertFalse(dates.birth_contradicted(PD(1980), claim([1980], 3, 5)))
        self.assertFalse(dates.birth_contradicted(PD(1980, 3, 4), claim([1980])))
        self.assertFalse(dates.birth_contradicted(PD(1980, 3), claim([1980], 3, 5)))

    def test_agreeing_date_never_contradicted(self):
        for c in [claim([1980], 3, 5), claim([1979, 1980]), claim([1980], 3)]:
            self.assertFalse(dates.birth_contradicted(PD(1980, 3, 5), c))

    def test_unknown_never_contradicts(self):
        self.assertFalse(dates.birth_contradicted(None, claim([1980])))
        self.assertFalse(dates.birth_contradicted(PD(None), claim([1980])))
        self.assertFalse(dates.birth_contradicted(PD(1950), claim([])))


class YoungerThanTest(unittest.TestCase):
    def test_full_dates_boundary(self):
        self.assertTrue(dates.younger_than(PD(2000, 6, 15), PD(2016, 6, 14), 16))
        self.assertFalse(dates.younger_than(PD(2000, 6, 15), PD(2016, 6, 15), 16))

    def test_default_is_16(self):
        self.assertTrue(dates.younger_than(PD(2000, 6, 15), PD(2016, 6, 14)))

    def test_partial_uses_oldest_possible_age(self):
        # born some time in 2000, report some time in 2015: at most 15 -> certainly younger
        self.assertTrue(dates.younger_than(PD(2000), PD(2015), 16))
        # report in 2016: could already be 16 -> not certain
        self.assertFalse(dates.younger_than(PD(2000), PD(2016), 16))
        self.assertFalse(dates.younger_than(PD(2000, 12), PD(2016, 12), 16))
        self.assertTrue(dates.younger_than(PD(2000, 12), PD(2016, 11), 16))
        self.assertFalse(dates.younger_than(PD(2000, 12, 31), PD(2016), 16))

    def test_adult(self):
        self.assertFalse(dates.younger_than(PD(1960, 1, 1), PD(2010, 1, 1), 16))

    def test_unknown_is_never_younger(self):
        self.assertFalse(dates.younger_than(None, PD(2010), 16))
        self.assertFalse(dates.younger_than(PD(2000), None, 16))
        self.assertFalse(dates.younger_than(PD(None), PD(2010), 16))


class BeforeTest(unittest.TestCase):
    def test_certain(self):
        self.assertIs(dates.before(PD(2001, 1, 1), PD(2001, 1, 2)), True)
        self.assertIs(dates.before(PD(1999), PD(2000, 1, 1)), True)
        self.assertIs(dates.before(PD(2001, 1, 2), PD(2001, 1, 1)), False)
        self.assertIs(dates.before(PD(2002), PD(2001, 12, 31)), False)

    def test_same_day_is_not_before(self):
        self.assertIs(dates.before(PD(2001, 5, 5), PD(2001, 5, 5)), False)

    def test_overlap_is_unknown(self):
        self.assertIsNone(dates.before(PD(2001), PD(2001, 6, 1)))
        self.assertIsNone(dates.before(PD(2001, 6), PD(2001, 6, 10)))
        self.assertIsNone(dates.before(PD(2001), PD(2001)))

    def test_missing_is_unknown(self):
        self.assertIsNone(dates.before(None, PD(2001)))
        self.assertIsNone(dates.before(PD(2001), None))


if __name__ == "__main__":
    unittest.main()