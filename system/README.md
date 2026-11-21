# Same Person or Not? A deterministic SOP engine

`system/run <data folder> <output file>` reads the bank's files, decides every watchlist hit as `DIFFERENT_ENTITY`, `SAME_ENTITY` or `REVIEW`, and writes one JSON line per hit with a reason code, the resolved customer record, a 2 to 4 sentence reason and the IDs of the records that decided it.

It is plain **Python 3 standard library** (3.8+), **no language model and no network calls**. Every rule is a line of the bank's identity SOP, and every fact carries the ID of the record it came from.

## Architecture

```
            alerts.jsonl, hits.jsonl                     customers, accounts, onboarding,
                    |                                    kyc_checks, notes, search_results
                    v                                                   |
   main.py  -- for each alert (sorted) -------------------------- load.py: Data (indexes)
                    |                                                   |
                    v                                                   v
          resolve.py: alert -> people  <------- names.py, dates.py, countries.py, notes.py
          (link or search, merge records, verified facts)
                    |
                    |     for each hit (sorted)
                    |            |
                    |            v
                    |    hitfacts.py: hit -> HitProfile (names, birth claims, countries,
                    |            |                       earliest dated report, death)
                    v            v
               judge.py: decide(HitProfile, Resolution, alert)  -- SOP principles 3, 6, 7
                         |
                         v
               explain.py: reason text + evidence IDs  ->  one JSON line
```

| Module | Job | SOP principle |
|---|---|---|
| `engine/model.py` | Shared shapes: `Fact` (value + source ID), `PartialDate`, `BirthClaim`, `Person`, `Resolution`, `HitProfile`, `Decision` | 9 |
| `engine/load.py` | Reads every `*.jsonl`, accepts lists or `"a; b"` strings, builds sorted indexes | |
| `engine/resolve.py` | Alert to candidate records, records to people, people to facts | 2, 3, 4 |
| `engine/notes.py` | Customer notes to verification facts and lived-in places | 4 |
| `engine/hitfacts.py` | Hit and its search results to a `HitProfile` | 5 |
| `engine/names.py`, `dates.py`, `countries.py` | Name agreement, partial-date logic, country normalisation | 8, 6, 7 |
| `engine/judge.py` | The decision rules below | 3, 6, 7 |
| `engine/explain.py` | Reason templates and evidence selection | 9 |

## Finding the customer and the listed person

<!-- A (Yousuf): please check / extend this section -->

**The customer.** We follow whatever link the alert carries (`account_ref`, `login_handle`, `email`). With no link (a third of the dev alerts) we search the system of record for records that fit **every** screened detail that is present: the name agrees (principle 8, so nicknames and typos still fit), the date of birth is equal in every part both give, the screened country is the residence or nationality, the city is in the record's city or address. A link that reaches several records (joint accounts) is narrowed by the same test. Records are then merged into people with union-find: a shared phone **and** the same full date of birth, or the same document number on **approved** identity checks. A shared phone or address alone never merges. The person's most recent approved check (a KYC row or an onboarding-team note) gives the verified name, date of birth and document country; rejected and expired checks are ignored.

**The listed person.** A hit's birth date is taken from `dobs`, else the first paragraph of the profile notes ("aged N in <date>" gives two possible years), else web search results for the hit's name, keeping a result only when it describes the same kind of listing in a country tied to the hit. Countries come from the hit's country, nationality, citizenship, address and place-of-birth fields, normalised; "International" and "Europe" are not countries. Only `According to <source>; <date>: ...` lines count as dated reports.

## Decision rules (`judge.py`)

Per person, the first rule that fires wins. A contradiction fires only when it is **certain**: a missing field, or a missing part of a partial date, never fires anything.

1. No usable facts on the customer: `REVIEW / INSUFFICIENT_DATA`.
2. One is a person, the other a company: `DIFFERENT_ENTITY / ENTITY_TYPE_MISMATCH`.
3. Date of death before the screening date: `DECEASED`.
4. Customer certainly under 16 (or company not yet incorporated) at the earliest dated report: `TEMPORAL_IMPOSSIBILITY`.
5. Compute agreement: name (verified legal name first), date of birth (verified first), shared country.
6. **Every** birth date the hit gives is contradicted: `DOB_MISMATCH`. One agreeing date blocks it.
7. The verified legal name (2+ real parts) agrees with none of the hit's names: `NAME_MISMATCH_VERIFIED`. Placeholder-only hit names are skipped.
8. No shared country: `LOCATION_MISMATCH`, **except** when name and date of birth agree, which is `REVIEW`.
9. Individual: name and date of birth agree, `SAME_ENTITY` (`NAME_DOB_LOCATION_MATCH` if a country is shared, else `NAME_DOB_MATCH`). Company: name and country agree, `NAME_LOCATION_MATCH`.
10. Otherwise `REVIEW / INSUFFICIENT_DATA`.

No customer found: only the screened entity type can clear; everything else is `REVIEW` and `customer_record_id` is `null`. Several people fit: each is decided; if all agree that decision stands with `customer_record_id = "AMBIGUOUS"`, otherwise `REVIEW / AMBIGUOUS_CUSTOMER_RECORD`.

Why so cautious: wrongly clearing a real match costs 60, a needless review 2 to 3. We clear only on a contradiction the SOP names, and say what is missing when we cannot decide.

## Evidence

Every fact is a `Fact(value, source)` where `source` is the exact record ID it came from (`CUS-`, `KYC-`, `NOTE-`, `SR-`, `H-`). The judge passes the facts that decided the hit to `explain.py`, which cites them plus the person's records and latest approved check. Hit and account IDs are not cited. The reason names this hit's own facts ("The customer's date of birth 1980-01-02 (KYC-...) agrees with the hit's 1979 or 1980.") and, for `REVIEW`, what is missing.

## Determinism

- No model calls and no randomness. Alerts and hits are processed sorted by ID; every set or dict that can reach the output is iterated `sorted(...)`; people are sorted by `person_id` (the smallest record ID in the group); evidence is sorted and de-duplicated.
- "Today" is the alert's `screened_at`, never the clock. `system/run` sets `PYTHONHASHSEED=0`.
- Check: repeated runs on the dev set (from the repo root and from inside `system/`) give byte-identical output. <!-- D: re-confirm at feature freeze -->

## Model and prompts

None. The SOP is precise enough to implement as rules, and rules are reproducible run to run. The free-text readers (`notes.py`, `hitfacts.py`) each sit behind one function, so a model could be plugged in there later without touching anything else.

## Time and cost

Dev set (440 alerts, 819 hits, 72,265 customers, 54,488 KYC checks, 31,895 notes): **25 to 40 s** on a laptop, most of it loading the files. Cost: **zero**, there are no API calls. The limit is 30 minutes.

## Worked cases

The three lines below are copied from `output/dev.jsonl`. Each is a practice hit whose reference answer we match.

**1. A clear mismatch: `H-622EDD`, `DIFFERENT_ENTITY / DOB_MISMATCH`**

> The customer's date of birth is 1979-04-17 (NOTE-CA9BBC). The hit gives a date of birth of 1972 or 1973 (SR-A88751), which the customer's contradicts. The dates of birth show they are different people.

How we got there: the customer's verified date of birth comes from an onboarding-team note (`NOTE-CA9BBC`), which outranks the declared one. The hit has no `dobs` and no age in its profile notes, so the date comes from a search result. The result is kept only because it describes the same kind of listing in a country tied to the hit, and its "aged N in <month year>" gives two possible years. The customer's year is more than one year outside both, so every birth date is contradicted. Evidence: `NOTE-CA9BBC`, `SR-A88751`.

**2. A match: `H-4D76E3`, `SAME_ENTITY / NAME_DOB_LOCATION_MATCH`**

> The customer's name "MOHAMMAD NADEEM GHANI" (NOTE-4E8A14) agrees with the hit's name "Mohammad Nadeem Ghani". The customer's date of birth 1968-02-17 (NOTE-4E8A14) agrees with the hit's 1968-02. Both are tied to Pakistan and United Kingdom. Nothing in the records contradicts the match.

How we got there: the alert's account leads to `CUS-970916`; a second record, `CUS-906311`, is merged into the same person by the SOP's merge rules (shared phone and full date of birth, or the same document number on approved checks), so both are cited. That person's latest approved check is a note (`NOTE-4E8A14`), which gives the verified name and date of birth. The hit gives only a year and month, and the two agree in every part both give. This hit was an unsafe clearance (cost 60) in an early build, before notes were read: without the note's date of birth, a declared one contradicted the hit.

**3. Left for review: `H-7F2A6C`, `REVIEW / INSUFFICIENT_DATA`**

> No contradiction rules the hit out, but there is not enough agreement to confirm it. A customer note (NOTE-F1D4BE) says they lived in Denmark, which the hit is also tied to, so the hit cannot be cleared on location. The hit gives no date of birth. Known gaps: no date of birth in dobs, notes or search results, no dated report.

How we got there: the customer's own records name other countries, so without the note this would clear on `LOCATION_MISMATCH`. A support note says the customer lived in a country the hit is tied to, which counts as a country tied to the customer, so nothing contradicts. The hit gives no date of birth anywhere, so nothing confirms either. The reason says exactly what is missing, and cites only the note that decided it.

## Results

`tools/score.py` against the 50 practice labels (our own scorer with the brief's cost matrix; the official `validate.py` was not available to us):

| | |
|---|---|
| Decisions right | **50 / 50**, cost 0 vs 108 for all-`REVIEW` (decision score 100%) |
| Unsafe clearances | **0** |
| Reason code accepted, `customer_record_id` right | 50 / 50, 50 / 50 |
| Evidence precision / recall | 99% / 96% |

Dev set decision mix (819 hits): 446 `DIFFERENT_ENTITY`, 123 `SAME_ENTITY`, 250 `REVIEW`. Every run is byte-identical.

Checks beyond the 50 labels, because the unseen set has new customers, reworded text and rare SOP cases:
- **Clearance audit** over all dev clears: no hit is cleared where name **and** date of birth agree, except `NAME_MISMATCH_VERIFIED`, where the SOP says the verified legal name wins. Clears that rest on a verified name the customer did not type were checked by hand against the KYC rows and notes.
- **Search results** that decide a date of birth were re-checked independently for the listing phrase and a country tied to the hit. This caught and fixed a bug where lowercase words were read as country codes ("in" as India), which had let a namesake's age clear a hit.
- 50/50 on 50 practice hits is likely somewhat overfitted: we tuned on SOP principles, not on dev wording, and kept every ambiguous parse as "unknown".
