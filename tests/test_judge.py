"""Unit tests for judge.py + explain.py. Made-up values only.

Matchers are replaced by tiny stand-ins so these run before module C lands:
 names: case-insensitive word overlap; dates: year/month/day rules from SPEC section 3 and 4.
Run: py -3 -X utf8 -m unittest discover -s tests
"""
from __future__ import annotations

import os
import re
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "system"))

from engine import judge  # noqa: E402
from engine.model import BirthClaim, Fact, HitProfile, PartialDate, Person, Resolution  # noqa: E402

# ---- stand-in matchers -------------------------------------------------------------------------
fake_names = types.SimpleNamespace()
fake_names.parts = lambda n, company=False: sorted({p for p in re.findall(r"[a-z]+", n.lower()) if len(p) > 1})
fake_names.real_part_count = lambda n: len(fake_names.parts(n))


def _agree(a, b, company=False):
    pa, pb = set(fake_names.parts(a)), set(fake_names.parts(b))
    m = len(pa & pb)
    return m >= 2 or (m > 0 and m == min(len(pa), len(pb)))


fake_names.names_agree = _agree

fake_dates = types.SimpleNamespace()


def _parse(s):
    m = re.match(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$", s or "")
    if not m:
        return None
    return PartialDate(int(m.group(1)), int(m.group(2)) if m.group(2) else None, int(m.group(3)) if m.group(3) else None)


def _agrees(c, b):
    if c.year not in b.years:
        return False
    if c.month and b.month and c.month != b.month:
        return False
    if c.day and b.day and c.day != b.day:
        return False
    return True


def _contra(c, b):
    if all(abs(c.year - y) > 1 for y in b.years):
        return True
    if len(b.years) == 1 and c.year == b.years[0] and c.month and b.month and c.month != b.month:
        return True
    return False


def _before(a, b):
    ta, tb = (a.year, a.month or 0, a.day or 0), (b.year, b.month or 0, b.day or 0)
    if a.year != b.year:
        return a.year < b.year
    if a.month is None or b.month is None:
        return None
    return ta < tb if ta != tb else False


def _younger(dob, at, years=16):
    return at.year - dob.year < years  # good enough for whole-year fixtures


fake_dates.parse = _parse
fake_dates.birth_agrees = _agrees
fake_dates.birth_contradicted = _contra
fake_dates.before = _before
fake_dates.younger_than = _younger

judge.names, judge.dates = fake_names, fake_dates

ALERT = {"alert_id": "A-T1", "screened_at": "2026-01-15", "entity_type": "Individual"}


def person(**kw):
    base = dict(person_id="CUS-100", record_ids=["CUS-100"], entity_type="Individual",
                names=[Fact("Pat Quill Testman", "CUS-100", "full_name")],
                dobs=[Fact(PartialDate(1980, 5, 2), "CUS-100", "dob")],
                countries=[Fact("Freedonia", "CUS-100", "residence")])
    base.update(kw)
    return Person(**base)


def hit(**kw):
    base = dict(hit_id="H-T1", alert_id="A-T1", entity_type="Individual",
                names=[Fact("Pat Testman", "H-T1")],
                births=[BirthClaim((1980,), None, None, "H-T1")],
                countries=[Fact("Freedonia", "H-T1")])
    base.update(kw)
    return HitProfile(**base)


def sentences(t):
    return len(re.findall(r"[.!?](?=\s|$)", t))


class JudgeTests(unittest.TestCase):
    def check(self, d, decision, code):
        self.assertEqual((d.decision, d.reason_code), (decision, code), d.reason)
        self.assertTrue(2 <= sentences(d.reason) <= 4, d.reason)
        self.assertFalse([e for e in d.evidence if e.startswith(("H-", "ACC-"))], d.evidence)
        self.assertEqual(d.evidence, sorted(set(d.evidence)))

    def one(self, h, p):
        return judge.decide(h, Resolution(people=[p]), ALERT)

    def test_same_name_dob_location(self):
        d = self.one(hit(), person())
        self.check(d, "SAME_ENTITY", "NAME_DOB_LOCATION_MATCH")
        self.assertEqual(d.customer_record_id, "CUS-100")

    def test_same_name_dob_no_country(self):
        self.check(self.one(hit(countries=[]), person()), "SAME_ENTITY", "NAME_DOB_MATCH")

    def test_entity_type(self):
        self.check(self.one(hit(entity_type="Company"), person()), "DIFFERENT_ENTITY", "ENTITY_TYPE_MISMATCH")

    def test_deceased(self):
        d = self.one(hit(deceased=Fact(PartialDate(2020, 3, 1), "H-T1")), person())
        self.check(d, "DIFFERENT_ENTITY", "DECEASED")

    def test_too_young(self):
        d = self.one(hit(earliest_report=Fact(PartialDate(1990), "H-T1")), person())
        self.check(d, "DIFFERENT_ENTITY", "TEMPORAL_IMPOSSIBILITY")

    def test_dob_mismatch(self):
        d = self.one(hit(births=[BirthClaim((1960, 1961), None, None, "SR-9")]), person())
        self.check(d, "DIFFERENT_ENTITY", "DOB_MISMATCH")
        self.assertIn("SR-9", d.evidence)

    def test_one_agreeing_claim_blocks_dob_mismatch(self):
        h = hit(births=[BirthClaim((1960,), None, None, "H-T1"), BirthClaim((1980,), None, None, "H-T1")])
        self.check(self.one(h, person()), "SAME_ENTITY", "NAME_DOB_LOCATION_MATCH")

    def test_year_off_by_one_is_not_contradiction(self):
        d = self.one(hit(births=[BirthClaim((1981,), None, None, "H-T1")]), person())
        self.check(d, "REVIEW", "INSUFFICIENT_DATA")

    def test_verified_name_mismatch(self):
        p = person(verified_name=Fact("Robin Otherly", "KYC-7", "verified_name"))
        d = self.one(hit(), p)
        self.check(d, "DIFFERENT_ENTITY", "NAME_MISMATCH_VERIFIED")
        self.assertIn("KYC-7", d.evidence)

    def test_verified_dob_beats_declared(self):
        p = person(verified_dob=Fact(PartialDate(1950, 1, 1), "KYC-8", "verified_dob"))
        d = self.one(hit(), p)
        self.check(d, "DIFFERENT_ENTITY", "DOB_MISMATCH")
        self.assertIn("KYC-8", d.evidence)

    def test_location_mismatch(self):
        d = self.one(hit(births=[], countries=[Fact("Sylvania", "H-T1")]), person())
        self.check(d, "DIFFERENT_ENTITY", "LOCATION_MISMATCH")

    def test_location_exception_name_dob_agree(self):
        d = self.one(hit(countries=[Fact("Sylvania", "H-T1")]), person())
        self.check(d, "REVIEW", "INSUFFICIENT_DATA")

    def test_missing_dob_is_not_mismatch(self):
        self.check(self.one(hit(), person(dobs=[])), "REVIEW", "INSUFFICIENT_DATA")
        self.check(self.one(hit(births=[]), person()), "REVIEW", "INSUFFICIENT_DATA")

    def test_single_part_name_cannot_confirm(self):
        p = person(names=[Fact("Testman", "CUS-100")])
        self.check(self.one(hit(), p), "REVIEW", "INSUFFICIENT_DATA")

    def test_company_name_location(self):
        h = hit(entity_type="Company", names=[Fact("Acme Widgets Ltd", "H-T1")], births=[])
        p = person(entity_type="Company", names=[Fact("Acme Widgets Limited", "CUS-100")], dobs=[])
        self.check(self.one(h, p), "SAME_ENTITY", "NAME_LOCATION_MATCH")

    def test_no_people(self):
        d = judge.decide(hit(), Resolution(people=[]), ALERT)
        self.check(d, "REVIEW", "INSUFFICIENT_DATA")
        self.assertIsNone(d.customer_record_id)
        d = judge.decide(hit(entity_type="Company"), Resolution(people=[]), ALERT)
        self.check(d, "DIFFERENT_ENTITY", "ENTITY_TYPE_MISMATCH")

    def test_ambiguous_same_decision(self):
        a, b = person(), person(person_id="CUS-200", record_ids=["CUS-200"])
        d = judge.decide(hit(), Resolution(people=[b, a]), ALERT)
        self.check(d, "SAME_ENTITY", "NAME_DOB_LOCATION_MATCH")
        self.assertEqual(d.customer_record_id, "AMBIGUOUS")
        self.assertEqual(d.evidence, ["CUS-100", "CUS-200"])

    def test_ambiguous_different_decisions(self):
        a = person()
        b = person(person_id="CUS-200", record_ids=["CUS-200"], dobs=[Fact(PartialDate(1950), "CUS-200")])
        d = judge.decide(hit(), Resolution(people=[a, b]), ALERT)
        self.check(d, "REVIEW", "AMBIGUOUS_CUSTOMER_RECORD")
        self.assertEqual(d.customer_record_id, "AMBIGUOUS")

    def test_names_with_dots_keep_sentence_count(self):
        p = person(names=[Fact("Pat Q. Testman Jr.", "CUS-100")])
        d = self.one(hit(), p)
        self.check(d, "SAME_ENTITY", "NAME_DOB_LOCATION_MATCH")


if __name__ == "__main__":
    unittest.main()
