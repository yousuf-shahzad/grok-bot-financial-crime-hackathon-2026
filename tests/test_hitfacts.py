"""engine.hitfacts on made-up rows. No dev records."""
from __future__ import annotations

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "system"))

from engine.hitfacts import extract  # noqa: E402
from engine.model import BirthClaim, PartialDate  # noqa: E402


def _hit(**kwargs):
    base = {
        "hit_id": "H-TEST-1",
        "alert_id": "A-TEST-1",
        "entity_type": "Individual",
        "name": "Ada Example",
    }
    base.update(kwargs)
    return base


class HitFactsTest(unittest.TestCase):
    def test_names_keep_hit_id_as_source(self):
        profile = extract(_hit(aliases="A. Example; Ada Example"), data=None)
        self.assertEqual([(f.value, f.kind, f.source) for f in profile.names], [
            ("Ada Example", "full_name", "H-TEST-1"),
            ("A. Example", "alias", "H-TEST-1"),
        ])
        self.assertTrue(all(f.source.startswith("H-") for f in profile.names))

    def test_list_and_semicolon_dobs(self):
        profile = extract(_hit(dobs=["1970", "1971-05", "03/04/1990"]), data=None)
        self.assertEqual(
            [(c.years, c.month, c.day, c.source) for c in profile.births],
            [
                ((1970,), None, None, "H-TEST-1"),
                ((1971,), 5, None, "H-TEST-1"),
                ((1990,), 4, 3, "H-TEST-1"),
            ])

    def test_year_range_is_one_claim(self):
        profile = extract(_hit(dobs="1973 or 1974"), data=None)
        self.assertEqual(profile.births, [
            BirthClaim(years=(1973, 1974), month=None, day=None, source="H-TEST-1")])

    def test_dobs_block_notes_and_search(self):
        data = types.SimpleNamespace(search_by_query={
            "ada example": [{
                "result_id": "SR-TEST-9",
                "title": "a sanctioned individual in Portugal",
                "snippet": "She was aged 10 in March 2000.",
            }],
        })
        profile = extract(_hit(
            dobs="1980",
            primary_category="Sanctions",
            countries="Portugal",
            profile_notes="Born 1 January 1970.\n\nAged 10 in March 2000.",
        ), data)
        self.assertEqual(profile.births[0].years, (1980,))
        self.assertEqual(profile.births[0].source, "H-TEST-1")

    def test_age_in_first_paragraph_only(self):
        profile = extract(_hit(
            profile_notes="He was aged 45 in March 2019.\n\nBorn 1 January 1900.",
            countries="Portugal",
        ), data=None)
        self.assertEqual(profile.births, [
            BirthClaim(years=(1973, 1974), month=None, day=None, source="H-TEST-1")])

    def test_explicit_birth_date(self):
        profile = extract(_hit(profile_notes="Born 2 January 1990 in Lisbon."), data=None)
        self.assertEqual(profile.births[0].years, (1990,))
        self.assertEqual(profile.births[0].month, 1)
        self.assertEqual(profile.births[0].day, 2)
        self.assertEqual(profile.births[0].source, "H-TEST-1")

    def test_search_uses_sr_id_when_relevant(self):
        data = types.SimpleNamespace(search_by_query={
            "example ada": [{
                "result_id": "SR-TEST-2",
                "title": "namesake",
                "snippet": "Not about a listing.",
            }, {
                "result_id": "SR-TEST-1",
                "title": "A sanctioned individual",
                "snippet": "Born 4 May 1962 in Portugal.",
            }],
        })
        # Query words are sorted, so the key is "ada example", not "example ada".
        data.search_by_query["ada example"] = data.search_by_query.pop("example ada")
        profile = extract(_hit(
            primary_category="Sanctions",
            countries="Portugal",
        ), data)
        self.assertEqual(len(profile.births), 1)
        self.assertEqual(profile.births[0].source, "SR-TEST-1")
        self.assertEqual(profile.births[0].years, (1962,))
        self.assertEqual(profile.births[0].month, 5)
        self.assertEqual(profile.listing_kind, "a sanctioned individual")

    def test_search_skipped_without_listing_or_country(self):
        snippet = "Aged 45 in March 2019. A sanctioned individual in Portugal."
        data = types.SimpleNamespace(search_by_query={
            "ada example": [{"result_id": "SR-TEST-3", "title": "", "snippet": snippet}],
        })
        no_phrase = extract(_hit(primary_category="Sanctions", countries="Portugal"), types.SimpleNamespace(
            search_by_query={"ada example": [{
                "result_id": "SR-TEST-3", "title": "weather", "snippet": "Aged 45 in March 2019 in Portugal.",
            }]}))
        self.assertEqual(no_phrase.births, [])
        no_country = extract(_hit(primary_category="Sanctions"), data)
        self.assertEqual(no_country.births, [])
        self.assertIn("no date of birth in dobs, notes or search results", no_country.missing)

    def test_countries_normalised_and_sourced(self):
        profile = extract(_hit(
            countries="Portugal; International",
            nationality="british",
            citizenship="Europe",
            addresses="1 Road, Lisbon, Nigeria",
            place_of_birth="Lagos, Kenya",
        ), data=None)
        self.assertEqual(
            [(f.value, f.kind, f.source) for f in profile.countries],
            [
                ("Portugal", "country", "H-TEST-1"),
                ("United Kingdom", "nationality", "H-TEST-1"),
                ("Nigeria", "address", "H-TEST-1"),
                ("Kenya", "place_of_birth", "H-TEST-1"),
            ])

    def test_dated_report_and_death_keep_hit_id(self):
        notes = "\n".join([
            "A report said he was fined in 2010.",
            "According to Herald; March 2012: a fine was issued.",
            "According to Herald; 2011: an earlier note.",
            "according to lowercase; 2001: does not count.",
        ])
        profile = extract(_hit(
            profile_notes=notes,
            deceased_date="2019-08-01",
            life_status="Deceased",
            dobs="1970",
            countries="Portugal",
        ), data=None)
        self.assertEqual(profile.earliest_report.value, PartialDate(2011, None, None))
        self.assertEqual(profile.earliest_report.source, "H-TEST-1")
        self.assertEqual(profile.deceased.value, PartialDate(2019, 8, 1))
        self.assertEqual(profile.deceased.source, "H-TEST-1")

    def test_incomparable_reports_do_not_pick_an_unproven_earlier_date(self):
        notes = "According to Herald; 2019: a note.\nAccording to Herald; March 2019: a note."
        profile = extract(_hit(profile_notes=notes, dobs="1970"), data=None)
        self.assertEqual(profile.earliest_report.value, PartialDate(2019, None, None))

    def test_company_dobs_are_incorporation_not_births(self):
        profile = extract(_hit(
            entity_type="Company",
            name="Example Holdings",
            dobs="1999-05-01; 2015",
            profile_notes="Aged 45 in March 2019.",
            countries="France",
        ), data=None)
        self.assertEqual(profile.births, [])
        self.assertEqual(profile.incorporated.value, PartialDate(1999, 5, 1))
        self.assertEqual(profile.incorporated.source, "H-TEST-1")
        self.assertIsNone(profile.deceased)

    def test_deceased_without_a_date_does_not_invent_one(self):
        profile = extract(_hit(life_status="Deceased", dobs="1970"), data=None)
        self.assertIsNone(profile.deceased)
        self.assertIn("deceased but no date of death", profile.missing)

    def test_blank_category_uses_first_category(self):
        profile = extract(_hit(primary_category="", categories="PEP; Sanctions"), data=None)
        self.assertEqual(profile.listing_kind, "a politically exposed person")

    def test_two_calls_match(self):
        hit = _hit(dobs="1970; 1971-05", aliases=["One", "Two"], countries="Spain")
        self.assertEqual(extract(hit, None), extract(hit, None))

    def test_uses_load_as_list_and_countries_normalise_when_they_pass(self):
        load = types.ModuleType("engine.load")

        def as_list(value):
            if value == "SHOULD-NOT-SPLIT":
                return ["Only Alias"]
            if value is None:
                return []
            if isinstance(value, (list, tuple)):
                return [str(item).strip() for item in value if str(item or "").strip()]
            return [part.strip() for part in str(value).split(";") if part.strip()]

        load.as_list = as_list
        countries = types.ModuleType("engine.countries")

        def normalise(value):
            text = str(value).strip()
            if text.lower() == "international":
                return None
            if text.lower() in ("gb", "british", "united kingdom"):
                return "United Kingdom"
            return text

        countries.normalise = normalise
        sys.modules["engine.load"] = load
        sys.modules["engine.countries"] = countries
        try:
            profile = extract(_hit(aliases="SHOULD-NOT-SPLIT", nationality="British"), data=None)
        finally:
            sys.modules.pop("engine.load", None)
            sys.modules.pop("engine.countries", None)
        self.assertEqual([f.value for f in profile.names if f.kind == "alias"], ["Only Alias"])
        self.assertEqual(profile.names[1].source, "H-TEST-1")
        self.assertEqual(profile.countries[0].value, "United Kingdom")
        self.assertEqual(profile.countries[0].source, "H-TEST-1")

    def test_search_key_is_accent_folded_then_raw(self):
        snippet = "Born 4 May 1962. A sanctioned individual in Portugal."
        data = types.SimpleNamespace(search_by_query={
            "jerome rakovic": [{"result_id": "SR-FOLD-1", "title": "", "snippet": snippet}],
            "jérôme raković": [{"result_id": "SR-RAW-1", "title": "", "snippet": snippet}],
        })
        profile = extract(_hit(
            name="Jérôme Raković",
            primary_category="Sanctions",
            countries="Portugal",
        ), data)
        self.assertEqual([c.source for c in profile.births], ["SR-FOLD-1"])
        self.assertEqual(profile.births[0].years, (1962,))

    def test_place_fields_use_the_last_country(self):
        profile = extract(_hit(
            nationality="Lagos, Lagos, Nigeria",
            citizenship="Lyon, Auvergne-Rhone-Alpes, France",
            place_of_birth="Madrid, Community of Madrid, Spain",
        ), data=None)
        self.assertEqual(
            [(f.kind, f.value) for f in profile.countries],
            [
                ("nationality", "Nigeria"),
                ("citizenship", "France"),
                ("place_of_birth", "Spain"),
            ])

    def test_age_shapes_in_one_sentence(self):
        samples = [
            ("In March 2019 he was 46.", (1972, 1973)),
            ("In March 2019, when he reached the age of 38.", (1980, 1981)),
            ("March 2019 saw Ada Example, a 30-year-old, take office.", (1988, 1989)),
            ("Ada Example, 33 year old, was fined in March 2019.", (1985, 1986)),
            ("Ada Example, 33, was named in March 2019.", (1985, 1986)),
            ("She was aged 45 in March 2019.", (1973, 1974)),
        ]
        for text, years in samples:
            profile = extract(_hit(profile_notes=text), data=None)
            self.assertEqual(profile.births[0].years, years, text)
            self.assertIsNone(profile.births[0].month, text)
            self.assertEqual(profile.births[0].source, "H-TEST-1")

    def test_was_born_on_full_date(self):
        profile = extract(_hit(profile_notes="She was born on 2 January 1990."), data=None)
        self.assertEqual(profile.births[0].years, (1990,))
        self.assertEqual(profile.births[0].month, 1)
        self.assertEqual(profile.births[0].day, 2)

    def test_a_fine_is_not_an_age(self):
        profile = extract(_hit(
            profile_notes="The fine was 50 in March 2019. See page 12.",
        ), data=None)
        self.assertEqual(profile.births, [])

    def test_lowercase_in_is_not_india(self):
        snippet = "Born 4 May 1962 in Portugal and later fined. id stamp."
        data = types.SimpleNamespace(search_by_query={
            "ada example": [{
                "result_id": "SR-PT-1",
                "title": "a sanctioned individual",
                "snippet": snippet,
            }],
        })
        india = extract(_hit(primary_category="Sanctions", countries="India"), data)
        self.assertEqual(india.births, [])
        andorra = extract(_hit(primary_category="Sanctions", countries="Andorra"), data)
        self.assertEqual(andorra.births, [])
        indonesia = extract(_hit(primary_category="Sanctions", countries="ID"), data)
        self.assertEqual(indonesia.births, [])
        portugal = extract(_hit(primary_category="Sanctions", countries="Portugal"), data)
        self.assertEqual(portugal.births[0].source, "SR-PT-1")
        self.assertEqual(portugal.births[0].years, (1962,))

    def test_capitalised_country_span_still_matches(self):
        data = types.SimpleNamespace(search_by_query={
            "ada example": [{
                "result_id": "SR-UK-1",
                "title": "a sanctioned individual",
                "snippet": "Born 4 May 1962. She is British and based in the United Kingdom.",
            }],
        })
        profile = extract(_hit(primary_category="Sanctions", nationality="United Kingdom"), data)
        self.assertEqual(profile.births[0].source, "SR-UK-1")

    def test_reworded_age_and_birth(self):
        profile = extract(_hit(
            profile_notes="He was aged 45 at the time of the March 2019 report.",
        ), data=None)
        self.assertEqual(profile.births[0].years, (1973, 1974))
        profile = extract(_hit(
            profile_notes="The file cites the March 2019 report. He was then 45.",
        ), data=None)
        self.assertEqual(profile.births[0].years, (1973, 1974))
        profile = extract(_hit(
            profile_notes="The file cites the March 2019 report. He was then a 45-year-old.",
        ), data=None)
        self.assertEqual(profile.births[0].years, (1973, 1974))
        profile = extract(_hit(
            profile_notes="March 2018 and March 2019 are both mentioned. He was then 45.",
        ), data=None)
        self.assertEqual(profile.births, [])
        profile = extract(_hit(profile_notes="Recorded as b. 1970 in the margin."), data=None)
        self.assertEqual(profile.births[0].years, (1970,))
        self.assertIsNone(profile.births[0].month)

    def test_death_wording_and_life_status(self):
        died = extract(_hit(profile_notes="The subject died in 2015.", life_status="unknown"), data=None)
        self.assertEqual(died.deceased.value, PartialDate(2015, None, None))
        self.assertEqual(died.deceased.source, "H-TEST-1")
        away = extract(_hit(profile_notes="She passed away on 12 Mar 2015."), data=None)
        self.assertEqual(away.deceased.value, PartialDate(2015, 3, 12))
        since = extract(_hit(profile_notes="He has been deceased since March 2015."), data=None)
        self.assertEqual(since.deceased.value, PartialDate(2015, 3, None))
        nodate = extract(_hit(profile_notes="Described only as the late patron.", life_status="Unknown"), data=None)
        self.assertIsNone(nodate.deceased)
        self.assertIn("deceased but no date of death", nodate.missing)
        alive = extract(_hit(
            profile_notes="His father died in 2015.", life_status="Alive", deceased_date="2015-01-01",
        ), data=None)
        self.assertIsNone(alive.deceased)
        status = extract(_hit(life_status="DECEASED", deceased_date="2015-06-01"), data=None)
        self.assertEqual(status.deceased.value, PartialDate(2015, 6, 1))
        dead = extract(_hit(life_status="Dead"), data=None)
        self.assertIsNone(dead.deceased)
        clash = extract(_hit(profile_notes="He died in 2014. She passed away in 2016."), data=None)
        self.assertIsNone(clash.deceased)
        firm = extract(_hit(
            entity_type="Company", name="Example Holdings",
            profile_notes="The founder died in 2015.",
        ), data=None)
        self.assertIsNone(firm.deceased)

    def test_age_in_a_search_snippet(self):
        data = types.SimpleNamespace(search_by_query={
            "ada example": [{
                "result_id": "SR-AGE-1",
                "title": "a sanctioned individual",
                "snippet": "In March 2019, when he reached the age of 38 in Portugal.",
            }],
        })
        profile = extract(_hit(primary_category="Sanctions", countries="Portugal"), data)
        self.assertEqual(profile.births[0].source, "SR-AGE-1")
        self.assertEqual(profile.births[0].years, (1980, 1981))


if __name__ == "__main__":
    unittest.main()
