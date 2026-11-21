# Tryll: same person or not?

`system/run <data folder> <output file>` reads the bank's files, decides every watchlist hit as `DIFFERENT_ENTITY`, `SAME_ENTITY` or `REVIEW`, and writes one JSON line per hit with a reason code, the resolved customer record, a 2 to 4 sentence reason and the IDs of the records that decided it.

It is plain **Python 3 standard library** (3.8+). The decisions are made by **rules**, each a line of the bank's identity SOP, and every fact carries the ID of the record it came from. **Tryll** is the product name. Two optional uses of a language model sit on top of the rules, and **neither can ever create a clearance**: a *cross-examiner* that can only send a clearance back to `REVIEW`, and a *dual decision path* (an independent Grok decision for every hit plus a screening agent when it disagrees with the rules), switched by `DUAL_MODE`. With no API key the system runs on rules alone and makes no network calls.

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
| `engine/crossexam.py`, `engine/llm.py` | Optional: a model re-reads the free text behind each clearance; can only turn it into `REVIEW` | 6 (safety) |
| `engine/llm_judge.py`, `engine/arbiter.py`, `engine/sop.py` | Optional dual path: an independent Grok decision per hit, a screening agent on disagreement, `DUAL_MODE` | 6, 7 (safety) |

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

- The rules make no model calls and use no randomness. Alerts and hits are processed sorted by ID; every set or dict that can reach the output is iterated `sorted(...)`; people are sorted by `person_id` (the smallest record ID in the group); evidence is sorted and de-duplicated.
- "Today" is the alert's `screened_at`, never the clock. `system/run` sets `PYTHONHASHSEED=0`.
- The cross-examiner runs at temperature 0 with a strict JSON schema, processes hits in sorted order and merges results by hit ID, so thread timing cannot change the output. It can only move a hit from `DIFFERENT_ENTITY` to `REVIEW`, so even a model that answered differently between runs could never turn a review into a clearance.
- The dual path is order-independent the same way (results merged by hit ID) and, in the default advisory mode, never changes the output.
- Check: repeated runs on the dev set (from the repo root and from inside `system/`, rules only and with the cross-examiner) give byte-identical output. <!-- D: re-confirm at feature freeze -->

## Model and prompts

**Rules decide; the model can only add caution.** After the judge has decided every hit, each `DIFFERENT_ENTITY` goes to a *cross-examiner*: a language model re-reads the free text behind that clearance (the customer's notes, the hit's profile text and search snippets) as a careful clerk. It **extracts facts only**, as strict JSON: for each customer note whether it records a successful identity check and its verified name, date of birth, document country and lived-in countries; for the hit's text whether it is about this person, birth-year candidates, month, day and the earliest dated report. **Our code, not the model, compares those facts with the SOP rule that cleared the hit.** If the model's reading removes the contradiction (for example a verified date of birth the parser missed), the hit becomes `REVIEW / INSUFFICIENT_DATA`, with a reason saying so.

`main.py` enforces the limit itself: a cross-examiner result is applied only if it turns a `DIFFERENT_ENTITY` into a `REVIEW` for the same hit. It can never create a clearance or a confirmation, and any error, timeout or missing key leaves the rules' decision unchanged.

| | |
|---|---|
| Provider | `OPENROUTER_API_KEY` if set (model `x-ai/grok-4.20`), else `XAI_API_KEY` (model `grok-4.20-0309-non-reasoning`), else rules only. `LLM_DISABLE=1` forces rules only |
| Settings | temperature 0, strict JSON schema, 45 s timeout per call, 2 retries, calls cached by a hash of their input within a run |
| Prompt | "Careful clerk: extract only explicitly stated facts, never guess", with the field list above |
| Calls on the dev set | about 113 (one per clearance, run in parallel) |
| Effect on dev | 0 decisions changed: the rules already read the dev text. With the note parser switched off as a test, rules alone made 5 unsafe clearances; with the cross-examiner, 0 |

### Dual decision path (`DUAL_MODE`)

For every hit an independent Grok judge (`llm_judge.py`) decides from the same structured facts plus the raw texts behind them, and sees the rules engine's own comparison table (name, date of birth, country: agree / contradict / unknown, and whether the location exception applies). If it agrees with the rules, the line is unchanged. If not, a screening agent (`arbiter.py`) says where the error is, and it may side against the rules only by **citing a supplied record that disproves the rules' comparison**; otherwise the rules' line stands.

| Screener verdict | Final |
|---|---|
| error in the LLM, or no cited record | the rules' line stands |
| error in the rules, LLM said `SAME_ENTITY` or `REVIEW` | the LLM's decision |
| error in the rules, LLM said `DIFFERENT_ENTITY` | `REVIEW`: **a clearance can only come from the rules engine** |
| neither / both (with a cited record), or screener failure | `REVIEW / INSUFFICIENT_DATA` |

The rule that the LLM can never create a clearance is enforced twice, in `arbiter.py` and again in `main.py`. A failed or invalid LLM answer is "no second view" (the rules' line stands), so an outage cannot push every hit to review.

**Switch:** `DUAL_MODE=enforce` (**default**) applies the dual path; `DUAL_MODE=advisory` runs it and keeps its trace for the analyst GUI but changes no output line, so the scored output is rules + cross-examiner; `DUAL_MODE=rules` makes no judge or screener calls at all. One-line switch back: `DUAL_MODE=advisory system/run <data> <out>` (or `DUAL_MODE=rules`, or set `DUAL_MODE_DEFAULT` in `system/main.py`). A line is only rewritten when the dual path changes its **decision or reason code**; when the rules' decision stands, the rules' line is kept byte for byte, so the output does not depend on whether an API key is set.

**Live result on dev (Grok, enforce):** practice 50/50, 0 unsafe clearances, 0 of 819 lines differ from rules only in decision or reason code. The Grok judge agreed with the rules on 750 of 819 hits (91.6%); on all 69 disagreements the screening agent found the error in the Grok judge and the rules stood. A keyed run is byte-identical to `output/dev.jsonl` (checked live). About 4 minutes for 1,002 judge and screener calls plus 114 cross-examiner calls. With no key the system is rules only and byte-identical, so a run without the model is safe too.

## Time and cost

Dev set (440 alerts, 819 hits, 72,265 customers, 54,488 KYC checks, 31,895 notes): **25 to 40 s** on a laptop with rules only, most of it loading the files; about the same with the cross-examiner, whose ~113 short calls run in parallel. Cost: zero on rules alone, a few cents per run with the model. The limit is 30 minutes.

## Worked cases

The dev data is for event participants only, so these three cases come from our **invented** test folder `tests/fixtures/rare/` (made-up people, IDs ending in `RC`), run through the same `system/run`. Each line below is copied from that output.

**1. A clear mismatch: `H-RC39`, `DIFFERENT_ENTITY / DOB_MISMATCH`**

> The customer's date of birth is 1960-01-01 (CUS-RC3901). The hit gives a date of birth of 1988 or 1989, which the customer's contradicts. The dates of birth show they are different people.

How we got there: the hit has no `dobs` field, so the birth date comes from the first paragraph of its profile notes, where an age is stated at a dated report. An age at a date gives two possible years, here 1988 or 1989. The customer's year is more than one year outside both, so every birth date the hit gives is contradicted, which is the SOP's `DOB_MISMATCH`.

**2. A match: `H-RC09`, `SAME_ENTITY / NAME_DOB_LOCATION_MATCH`**

> The customer's name "Yannick Strode" (KYC-RC0902) agrees with the hit's name "Yannick Strode". The customer's date of birth 1985-03-03 (CUS-RC0902) agrees with the hit's 1985-03-03. Both are tied to United Kingdom. Nothing in the records contradicts the match.

How we got there: the alert leads to `CUS-RC0901`; a second record, `CUS-RC0902`, is the same person under the SOP's merge rules, so all their facts count and both are cited. The verified legal name comes from that person's approved identity check `KYC-RC0902`, which outranks what the customer typed. Name, date of birth and country all agree and nothing contradicts them.

**3. Left for review: `H-RC07`, `REVIEW / INSUFFICIENT_DATA`**

> The customer's name "Lucan Ferreby" (CUS-RC0701) agrees with the hit's "Lucan Ferreby", and their date of birth 1968-11-03 (CUS-RC0701) agrees with the hit's 1968-11-03. However the customer is tied to United Kingdom and the hit only to Brazil. A country difference does not clear a hit whose name and date of birth agree, so an analyst must decide.

How we got there: every country tied to the customer differs from every country tied to the hit, which would normally clear on `LOCATION_MISMATCH`. But the SOP's exception applies here because name **and** date of birth both agree, so the engine does not clear and does not confirm: it sends the hit to an analyst and says why.

## Results

`tools/score.py` against the 50 practice labels (our own scorer with the brief's cost matrix; the official `validate.py` was not available to us):

| | |
|---|---|
| Decisions right | **50 / 50**, cost 0 vs 108 for all-`REVIEW` (decision score 100%) |
| Unsafe clearances | **0** |
| Reason code accepted, `customer_record_id` right | 50 / 50, 50 / 50 |
| Evidence precision / recall | 99% / 96% |

Dev set decision mix (819 hits): 447 `DIFFERENT_ENTITY`, 123 `SAME_ENTITY`, 249 `REVIEW`. Every run is byte-identical.

Checks beyond the 50 labels, because the unseen set has new customers, reworded text and rare SOP cases:
- **Clearance audit** over all dev clears: no hit is cleared where name **and** date of birth agree, except `NAME_MISMATCH_VERIFIED`, where the SOP says the verified legal name wins. Clears that rest on a verified name the customer did not type were checked by hand against the KYC rows and notes.
- **Search results** that decide a date of birth were re-checked independently for the listing phrase and a country tied to the hit. This caught and fixed a bug where lowercase words were read as country codes ("in" as India), which had let a namesake's age clear a hit.
- 50/50 on 50 practice hits is likely somewhat overfitted: we tuned on SOP principles, not on dev wording, and kept every ambiguous parse as "unknown".
