"""engine.notes slot parser. Made-up sentences only."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "system"))

from engine.model import PartialDate  # noqa: E402
from engine.notes import NoteFacts, parse  # noqa: E402


def kyc(text, note_id="NOTE-TEST-1", created="2024-06-01"):
    return {"note_id": note_id, "channel": "kyc", "created_at": created, "text": text}


class KycSlotsTest(unittest.TestCase):
    def test_caps_name_dob_and_from_country(self):
        facts = parse(kyc(
            "Verified via Veriff on 2024-03-01: passport from Spain, "
            "name ADA MARIA FERNANDEZ, DOB 17 February 1968."))
        self.assertTrue(facts.verified)
        self.assertFalse(facts.rejected)
        self.assertEqual(facts.name, "ADA MARIA FERNANDEZ")
        self.assertEqual(facts.dob, PartialDate(1968, 2, 17))
        self.assertEqual(facts.doc_country, "Spain")
        self.assertEqual(facts.date, PartialDate(2024, 3, 1))
        self.assertEqual(facts.source, "NOTE-TEST-1")

    def test_accented_caps_and_month_first_date(self):
        facts = parse(kyc(
            "Persona confirmed identity of JOSE FERNANDEZ on February 2, 2024, "
            "born February 17, 1968, document issued in Germany."))
        self.assertTrue(facts.verified)
        self.assertEqual(facts.name, "JOSE FERNANDEZ")
        self.assertEqual(facts.dob, PartialDate(1968, 2, 17))
        self.assertEqual(facts.doc_country, "Germany")
        self.assertEqual(facts.date, PartialDate(2024, 2, 2))

    def test_accented_letter_in_caps_name(self):
        facts = parse(kyc(
            "Sumsub validated passport from France for MARIA FERN\u00c1NDEZ, "
            "date of birth 1968-02-17, as of 2024-01-09."))
        self.assertEqual(facts.name, "MARIA FERN\u00c1NDEZ")
        self.assertEqual(facts.dob, PartialDate(1968, 2, 17))
        self.assertTrue(facts.verified)

    def test_slash_date_is_day_first(self):
        facts = parse(kyc(
            "Onfido approved the national ID from Italy for LUCA BIANCHI (03/04/1990) "
            "on 2024-05-06."))
        self.assertEqual(facts.dob, PartialDate(1990, 4, 3))
        self.assertEqual(facts.date, PartialDate(2024, 5, 6))
        self.assertEqual(facts.doc_country, "Italy")

    def test_paren_dob_without_born_keyword(self):
        facts = parse(kyc(
            "Onfido successfully verified the national ID for AMINA OKONKWO (12/05/1985) "
            "on 2024-08-15. The documentation is from Brazil."))
        self.assertTrue(facts.verified)
        self.assertEqual(facts.dob, PartialDate(1985, 5, 12))
        self.assertEqual(facts.doc_country, "Brazil")
        self.assertEqual(facts.name, "AMINA OKONKWO")

    def test_country_phrases(self):
        samples = [
            ("passport from the United Kingdom for ADA EXAMPLE, born 1968-02-17, on 2024-01-01.",
             "United Kingdom"),
            ("driving licence (Germany) for ADA EXAMPLE, DOB 1968-02-17, on 2024-01-01.",
             "Germany"),
            ("national ID originating from Bangladesh for ADA EXAMPLE, born 1968-02-17, on 2024-01-01.",
             "Bangladesh"),
            ("passport issued in Spain for ADA EXAMPLE, born 1968-02-17, on 2024-01-01.",
             "Spain"),
            ("validated the Serbia national ID for ADA EXAMPLE, born 1968-02-17, on 2024-01-01.",
             "Serbia"),
            ("referencing a France passport and a birth date of 17 February 1968 for ADA EXAMPLE on 2024-01-01.",
             "France"),
        ]
        for text, country in samples:
            facts = parse(kyc("Provider processed " + text))
            self.assertTrue(facts.verified, text)
            self.assertEqual(facts.doc_country, country, text)

    def test_placeholders_are_not_a_name(self):
        facts = parse(kyc(
            "Verified passport from Spain for N/A 0000, DOB 1968-02-17, on 2024-01-01."))
        self.assertFalse(facts.verified)
        self.assertIsNone(facts.name)

    def test_placeholder_inside_a_real_name_is_dropped(self):
        facts = parse(kyc(
            "Verified passport from Spain for ADA N/A EXAMPLE, DOB 1968-02-17, on 2024-01-01."))
        self.assertEqual(facts.name, "ADA EXAMPLE")
        self.assertTrue(facts.verified)

    def test_success_words(self):
        words = [
            "verified", "confirmed", "validated", "passed", "cleared",
            "matches", "processed", "approved", "completed", "successful check",
        ]
        body = "passport from Spain for ADA EXAMPLE, born 1968-02-17, on 2024-01-01."
        for word in words:
            facts = parse(kyc("Provider %s the document. %s" % (word, body)))
            self.assertTrue(facts.verified, word)

    def test_failure_words_are_not_evidence(self):
        for word in ("rejected", "failed", "expired", "could not"):
            facts = parse(kyc(
                "Check %s for ADA EXAMPLE, born 1968-02-17, passport from Spain." % word))
            self.assertTrue(facts.rejected, word)
            self.assertFalse(facts.verified, word)
            self.assertIsNone(facts.name, word)
            self.assertIsNone(facts.dob, word)
            self.assertIsNone(facts.doc_country, word)
            self.assertEqual(facts.source, "NOTE-TEST-1")

    def test_success_and_failure_stays_rejected(self):
        facts = parse(kyc(
            "First the check was rejected. Later it verified ADA EXAMPLE, "
            "born 1968-02-17, passport from Spain, on 2024-01-01."))
        self.assertTrue(facts.rejected)
        self.assertFalse(facts.verified)
        self.assertIsNone(facts.name)

    def test_not_verified_is_not_success(self):
        facts = parse(kyc(
            "Provider has not verified ADA EXAMPLE, born 1968-02-17, passport from Spain."))
        self.assertFalse(facts.verified)


class ResidenceSlotsTest(unittest.TestCase):
    def test_email_lived_and_worked(self):
        facts = parse({
            "note_id": "NOTE-TEST-2",
            "channel": "email",
            "created_at": "2021-04-04",
            "text": "The account holder reported living and working in the United States between 2013 and 2023.",
        })
        self.assertFalse(facts.verified)
        self.assertEqual(facts.lived_in, ["United States"])
        self.assertEqual(facts.source, "NOTE-TEST-2")
        self.assertEqual(facts.date, "2021-04-04")

    def test_country_named_before_the_verb(self):
        facts = parse({
            "channel": "phone",
            "note_id": "NOTE-TEST-10",
            "text": "Nigeria was where she lived before the move.",
        })
        self.assertEqual(facts.lived_in, ["Nigeria"])
        self.assertFalse(facts.verified)

    def test_country_may_come_first(self):
        facts = parse({
            "note_id": "NOTE-TEST-3",
            "channel": "phone",
            "text": "Nigeria was the location where the customer lived and worked.",
        })
        self.assertEqual(facts.lived_in, ["Nigeria"])
        self.assertFalse(facts.verified)

    def test_employment_and_residency(self):
        facts = parse({
            "channel": "email",
            "note_id": "NOTE-TEST-4",
            "text": "The client confirmed their employment and residency in Denmark from 2016 to 2018.",
        })
        self.assertEqual(facts.lived_in, ["Denmark"])

    def test_home_and_job(self):
        facts = parse({
            "channel": "phone",
            "note_id": "NOTE-TEST-5",
            "text": "User maintained both a home and a job in Kenya throughout 2018.",
        })
        self.assertEqual(facts.lived_in, ["Kenya"])

    def test_country_without_residence_word_is_ignored(self):
        facts = parse({
            "channel": "phone",
            "note_id": "NOTE-TEST-6",
            "text": "The caller asked about a branch in Portugal.",
        })
        self.assertEqual(facts.lived_in, [])

    def test_lowercase_in_and_and_are_not_countries(self):
        facts = parse({
            "channel": "email",
            "note_id": "NOTE-TEST-9",
            "text": "She lived in Portugal and kept a home there.",
        })
        self.assertEqual(facts.lived_in, ["Portugal"])

    def test_sentence_start_it_is_not_italy(self):
        facts = parse({
            "channel": "email",
            "note_id": "NOTE-TEST-7",
            "text": "It was a short stay. She lived in Poland.",
        })
        self.assertEqual(facts.lived_in, ["Poland"])

    def test_app_channel_is_ignored(self):
        facts = parse({
            "channel": "app",
            "note_id": "NOTE-TEST-8",
            "text": "Verified passport from Spain for ADA EXAMPLE, born 1968-02-17, on 2024-01-01. Lived in Kenya.",
        })
        self.assertFalse(facts.verified)
        self.assertEqual(facts.lived_in, [])
        self.assertIsNone(facts.name)

    def test_no_channel_stays_unknown(self):
        facts = parse("Verified passport from Spain for ADA EXAMPLE, born 1968-02-17.")
        self.assertIsInstance(facts, NoteFacts)
        self.assertFalse(facts.verified)
        self.assertEqual(facts.lived_in, [])

    def test_reworded_passive_and_country_first(self):
        facts = parse(kyc(
            "Identity was verified by Registrar for JOHN SMITH, born 12 Mar 1970, "
            "after a Spain-issued passport was read."))
        self.assertTrue(facts.verified)
        self.assertEqual(facts.name, "JOHN SMITH")
        self.assertEqual(facts.dob, PartialDate(1970, 3, 12))
        self.assertEqual(facts.doc_country, "Spain")

    def test_passport_was_checked_and_abbreviated_birth(self):
        facts = parse(kyc(
            "A passport issued in Spain was checked for JOHN SMITH, b. 1970, on 2020-06."))
        self.assertTrue(facts.verified)
        self.assertEqual(facts.name, "JOHN SMITH")
        self.assertEqual(facts.dob, PartialDate(1970, None, None))
        self.assertEqual(facts.doc_country, "Spain")
        self.assertEqual(facts.date, PartialDate(2020, 6, None))

    def test_month_precision_and_month_day_comma(self):
        facts = parse(kyc(
            "Onfido confirmed the driving licence from Portugal for ANA COSTA, "
            "DOB 1970-03, on Mar 12, 1970."))
        self.assertEqual(facts.dob, PartialDate(1970, 3, None))
        self.assertTrue(facts.verified)
        self.assertEqual(facts.doc_country, "Portugal")

    def test_two_birth_years_are_not_guessed(self):
        facts = parse(kyc(
            "Identity was verified for JOHN SMITH, born in 1970 or 1971, "
            "passport from Spain, on 2020-01-02."))
        self.assertFalse(facts.verified)
        self.assertIsNone(facts.dob)

    def test_kyc_is_a_verification_without_a_success_keyword(self):
        facts = parse(kyc(
            "Registrar successfully vetted the driving licence from Spain "
            "for JOHN SMITH, born 12 Mar 1970, on 2024-01-02."))
        self.assertTrue(facts.verified)
        self.assertEqual(facts.name, "JOHN SMITH")
        self.assertEqual(facts.dob, PartialDate(1970, 3, 12))
        self.assertEqual(facts.doc_country, "Spain")

    def test_name_first_and_placeholder_surname(self):
        facts = parse(kyc(
            "JOHN SMITH, born 17 February 1968, had his Spain passport "
            "successfully vetted by Registrar on 2024-02-02."))
        self.assertTrue(facts.verified)
        self.assertEqual(facts.doc_country, "Spain")
        facts = parse(kyc(
            "Registrar cleared the national ID for 0000 OKONKWO on 2024-03-03. "
            "The issuing country is Nigeria, and the DOB is 12 Mar 1970."))
        self.assertTrue(facts.verified)
        self.assertEqual(facts.name, "OKONKWO")
        self.assertEqual(facts.dob, PartialDate(1970, 3, 12))
        self.assertEqual(facts.doc_country, "Nigeria")
        self.assertEqual(facts.date, PartialDate(2024, 3, 3))

    def test_confirming_dob_and_bracket_alias_is_not_a_country(self):
        facts = parse(kyc(
            "Registrar performed an identity check on 2024-04-04 for "
            "JOHN SMITH (JOHNNY SMITH), confirming a DOB of 1970-03, "
            "using a passport from Portugal."))
        self.assertTrue(facts.verified)
        self.assertEqual(facts.name, "JOHN SMITH")
        self.assertEqual(facts.dob, PartialDate(1970, 3, None))
        self.assertEqual(facts.doc_country, "Portugal")

    def test_demonym_and_country_of_issue(self):
        facts = parse(kyc(
            "On 2024-05-05 Registrar verified the passport of ADA EXAMPLE, "
            "a Nigerian national born 2 January 1990."))
        self.assertTrue(facts.verified)
        self.assertEqual(facts.doc_country, "Nigeria")
        facts = parse(kyc(
            "National ID verified for ADA EXAMPLE, born 2 January 1990, "
            "using Registrar on 2024-05-05. The issuing country is France."))
        self.assertEqual(facts.doc_country, "France")
        self.assertTrue(facts.verified)

    def test_accented_capital_stays_in_the_name(self):
        facts = parse(kyc(
            "Sumsub validated a passport for Slovenia for ANA KOVA\u0106, "
            "born 9 February 1989, on 2024-02-02."))
        self.assertEqual(facts.name, "ANA KOVA\u0106")
        self.assertTrue(facts.verified)
        self.assertEqual(facts.doc_country, "Slovenia")

    def test_declined_is_not_evidence(self):
        facts = parse(kyc(
            "The check was declined for JOHN SMITH, born 2 January 1990, "
            "passport from Spain."))
        self.assertTrue(facts.rejected)
        self.assertFalse(facts.verified)
        self.assertIsNone(facts.name)

    def test_repeat_calls_match(self):
        note = kyc("Verified passport from Spain for ADA EXAMPLE, born 1968-02-17, on 2024-01-01.")
        self.assertEqual(parse(note), parse(note))


if __name__ == "__main__":
    unittest.main()
