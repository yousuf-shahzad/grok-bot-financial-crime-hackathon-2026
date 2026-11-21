# Track 2 build plan: deterministic SOP engine (no LLM yet)

Goal for today: a `system/run` that implements the SOP ([SPEC.md](SPEC.md)) end to end in **plain Python 3 standard library**, with no model calls, and produces a valid, scorable `output/dev.jsonl`. LLM tooling is out of scope for this plan. The only concession: hit and note text extraction sit behind one function each, so a model could be plugged in later without touching anything else.

Code freeze **17:00**. Plan written at about 12:30, so roughly 4.5 hours.

## 1. Who does what

Provisional: the lead can swap B, C and D. Post on the board when you start your module.

| Module | Owner | Files | Size |
|---|---|---|---|
| **A. Loader + customer resolver** (hardest) | `@yousuf-shahzad` | `system/engine/load.py`, `system/engine/resolve.py` | Large |
| **B. Text facts: hit facts + customer notes** | `@DiamondNexus` | `system/engine/hitfacts.py`, `system/engine/notes.py` | Medium-large |
| **C. Matchers: names, dates, countries** | `@kendricklow2008` | `system/engine/names.py`, `system/engine/dates.py`, `system/engine/countries.py` | Medium |
| **D. Model, judge, output, run, scorer** (integration) | `@ThomasGrattoniMay` | `system/engine/model.py`, `system/engine/judge.py`, `system/engine/explain.py`, `system/main.py`, `system/run`, `tools/score.py` | Medium-large |

Rules: you edit only your own files. Need a change in someone else's file? Ask on the board. `model.py` is shared: **only D edits it**; ask D on the board for any field you need.

## 2. Timeline

| By | Milestone | Who |
|---|---|---|
| **13:00** | `model.py` merged exactly as in section 4. `system/run` + `main.py` skeleton that writes every hit as `REVIEW / INSUFFICIENT_DATA`, valid format. Every other module merged as **stubs with the final signatures** (returning empty results) so the pipeline runs end to end | D first, then everyone |
| **14:00** | C: names, dates and countries done with unit tests. B: hit `dobs`, profile-note ages, dated reports, death date, countries. A: loader + link-following + person merging. D: `tools/score.py` (cost matrix, per-hit diff against practice labels) | all |
| **15:00** | A: no-link search, verified facts (KYC + notes). B: search-result relevance filter + customer-note parser. D: full judge (all contradictions, exceptions, agreement, ambiguity) + reason templates + evidence. **First real score on the 50 practice labels** | all |
| **16:00** | Error analysis from the scorer, fix by module owner. Determinism check (two runs, `diff` must be empty). Speed check (dev set must run in a few minutes, the limit is 30). **Feature freeze** | all |
| **16:00–16:45** | `system/README.md` (D + A), final `output/dev.jsonl`, push the public submission repo with `system/` and `output/` only. Video recording | D, A; video: B + C |
| **17:00** | Submitted. Last commit before 17:00 is scored | lead |

Keep `main` runnable at every merge: `bash system/run <data folder> output/dev.jsonl` must always succeed.

## 3. Layout

```
system/
  run                 # bash: finds python3 (or python) and runs main.py with the same args   [D]
  main.py             # args, load, for each alert: resolve once, for each hit: facts -> judge -> write   [D]
  README.md           # required by the brief   [D + A, written last]
  engine/
    __init__.py
    model.py          # shared data shapes, section 4   [D only]
    load.py           # read the data folder into indexes   [A]
    resolve.py        # alert -> candidate people   [A]
    notes.py          # customer note text -> facts   [B]
    hitfacts.py       # hit + search results -> HitProfile   [B]
    names.py          # SOP principle 8   [C]
    dates.py          # parsing, agree / contradict, age   [C]
    countries.py      # normalise country, code, nationality   [C]
    judge.py          # SOP principles 6 and 7, ambiguity   [D]
    explain.py        # reason text + evidence selection   [D]
tests/                # unit tests, synthetic fixtures only (never copy dev records)   [each owner]
tools/score.py        # scorer against data/dev/practice_labels.jsonl   [D]
```

Run locally: `bash system/run "$PWD/data/dev" "$PWD/output/dev.jsonl"`, then `py -3.14 -X utf8 tools/score.py output/dev.jsonl data/dev/practice_labels.jsonl` (on Mac or Linux use `python3`).

Python rules: standard library only; **target Python 3.8** (organisers' version unknown: no `match`, no `X | Y` type syntax, put `from __future__ import annotations` at the top). Open files with `encoding="utf-8"`. Never iterate a `set` or `dict` without `sorted(...)` where order can reach the output. No `datetime.now()`: "today" is the alert's `screened_at`.

## 4. Shared data shapes (`system/engine/model.py`, D writes this first, verbatim)

Every fact carries the ID of the record it came from. That is how the judge cites evidence.

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass(frozen=True, order=True)
class PartialDate:
    year: Optional[int] = None
    month: Optional[int] = None   # 1-12 or None if unknown
    day: Optional[int] = None     # 1-31 or None if unknown


@dataclass(frozen=True)
class Fact:
    value: object                 # str, PartialDate, ...
    source: str                   # record ID it came from: CUS-..., KYC-..., NOTE-..., SR-..., H-...
    kind: str = ""                # e.g. "full_name", "verified_name", "residence", "nationality", "doc_country", "lived_in"


@dataclass(frozen=True)
class BirthClaim:                 # one birth date the HIT gives
    years: Tuple[int, ...]        # possible years: (1973,) or (1973, 1974) from "aged 45 in March 2019"
    month: Optional[int]
    day: Optional[int]
    source: str                   # H-... (dobs or profile notes) or SR-...


@dataclass
class Person:                     # one real customer after merging records (SOP principle 3)
    person_id: str                # smallest record_id in the group (deterministic)
    record_ids: List[str]         # sorted
    entity_type: str              # "Individual" or "Company"
    names: List[Fact] = field(default_factory=list)       # full, preferred, login names from records
    verified_name: Optional[Fact] = None                  # latest approved KYC check or onboarding note
    dobs: List[Fact] = field(default_factory=list)        # PartialDate values from records (declared)
    verified_dob: Optional[Fact] = None                   # latest approved check
    countries: List[Fact] = field(default_factory=list)   # normalised names: residence, nationality, doc country, lived-in places
    path: List[str] = field(default_factory=list)         # IDs followed to get here (ACC-, APP-, ...), for the README and debugging


@dataclass
class Resolution:                 # what the resolver returns for one alert
    people: List[Person]          # 0 = nobody found, 1 = resolved, >1 = several people fit
    note: str = ""                # short human note: "joint account, screened dob picked CUS-...", "no link, 2 people fit"


@dataclass
class HitProfile:                 # one watchlist hit after fact extraction
    hit_id: str
    alert_id: str
    entity_type: str
    names: List[Fact] = field(default_factory=list)       # name + aliases, source = hit_id
    births: List[BirthClaim] = field(default_factory=list)
    countries: List[Fact] = field(default_factory=list)   # normalised; "International" / "Europe" dropped
    earliest_report: Optional[Fact] = None                # PartialDate of the earliest dated report
    deceased: Optional[Fact] = None                       # PartialDate
    incorporated: Optional[Fact] = None                   # companies only: PartialDate from dobs
    listing_kind: str = ""                                # "a sanctioned individual", "a politically exposed person", ...
    missing: List[str] = field(default_factory=list)      # known unknowns, e.g. "no date of birth in dobs, notes or search results"


@dataclass
class Decision:
    hit_id: str
    alert_id: str
    decision: str                 # DIFFERENT_ENTITY | SAME_ENTITY | REVIEW
    reason_code: str
    customer_record_id: Optional[str]   # record ID, "AMBIGUOUS", or None
    reason: str
    evidence: List[str]
```

Loader indexes (A owns, others read): `Data` object with dicts keyed as listed in section 5A. Variants and legal forms come from `name_variants.json` in the data folder if present, otherwise from the built-in copy in `names.py` (C), taken from the Policy tab.

## 5. Module specs

Each item names the SOP principle it implements ([SPEC.md](SPEC.md)). If the spec and the SOP disagree, the SOP wins.

### A. Loader + customer resolver (`@yousuf-shahzad`)

**load.py**: `load(folder) -> Data`. Read every `*.jsonl`. Accept list fields as real lists **or** `"a; b"` strings (helper `as_list(v)`). Build:
- `customers[record_id]`, `customers_by_email[lower(email)]`, `customers_by_phone[digits(phone)]`
- `accounts_by_id[account_id] -> [rows]` (joint accounts have several rows: 52 in dev), `accounts_by_login[login_handle]`, `accounts_by_customer[customer_id]`
- `onboarding_by_customer[customer_id] -> [rows]` (account_id, kyc_applicant_id)
- `kyc_by_applicant[applicant_id] -> [checks]`, `kyc_by_docnum[document_number] -> [checks]` (approved only)
- `notes_by_email[lower(email)] -> [notes]`
- `search_by_query[query] -> [results]`
- name blocking index for the no-link search: `customers_by_name_part[part] -> {record_ids}` over full, preferred and login names, with parts normalised by C's `names.parts()` and expanded by variant group. Add a one-edit deletion index for fuzzy parts if time allows.

**resolve.py**: `resolve(alert, data) -> Resolution`. Principles 2, 3, 4.
1. **Linked alerts:** `account_ref` → all holders on that account; `login_handle` → accounts → customer; `email` → customers with that email. If the link gives several records, keep those that **fit** the screened details (step 2's test). If none fit, keep all of them (they become several people → the judge decides each).
2. **No link (146 of 440 alerts):** find records that fit **every screened detail that is present**:
   - name: full, preferred or login name **agrees** with the screened name (`names.names_agree`, screened names can carry nicknames and typos)
   - dob: equal in **every part both give** (`dates.same_in_shared_parts`); a record with no dob does not fail this
   - country: screened country is the record's residence **or** nationality (`countries.normalise` both)
   - city: screened city appears in the record's city or address (case- and accent-insensitive)
   - entity type must match.
   Use the blocking index, then check only those candidates (72k records × 440 alerts is too slow to brute force).
3. **Merge into people:** union-find over records. Join two records when (a) they share a phone **and** the same **full** date of birth (year, month and day all known and equal), or (b) their **approved** KYC checks have the same `document_number`. Expand transitively from each candidate. A shared phone or address **alone** never joins.
4. **Facts per person:** from every record in the group: names (`full_name`, `preferred_name`, `login_name`), `dob`, countries (`residence_country`, `nationality`). KYC: `onboarding_by_customer` → `kyc_applicant_id` → checks; **approved only**, rejected and expired ignored. Notes: `notes_by_email` for each record's email → B's `notes.parse(note)` → verification facts and lived-in places. The **most recent approved** check (KYC row or note, by date) sets `verified_name`, `verified_dob` and adds the document country.
5. Return `Resolution(people=sorted by person_id, note=...)`. Never use records of a person who does not fit the alert.

Test against the `path` column of the practice labels: it shows the exact route for each answer (22 account_ref, 11 login_handle, 5 email, 12 no-link name searches; 13 resolve to several records of one person, 2 to `AMBIGUOUS`).

### B. Text facts (`@DiamondNexus`)

**hitfacts.py**: `extract(hit, data) -> HitProfile`. Principle 5.
- Names: `name` + every alias (as Facts with source `hit_id`).
- Births, in this order, stop at the first source that gives any: (1) `dobs` (years, `YYYY-MM`, full dates); (2) first paragraph of `profile_notes`: explicit birth dates and "aged N in <date>" → two years `(Y-N-1, Y-N)`; (3) only if neither: `search_by_query[name words lowercased, sorted alphabetically, joined by space]`, keeping a result **only if** its text describes the hit's listing kind (table in SPEC section 2) **and** a country tied to the hit. Extract the age or birth date from the snippet the same way. Source is the `SR-...` ID.
- Listing kind from `primary_category`, else the first of `categories`.
- Countries: `countries`, `nationality`, `citizenship`, the **last part** of each address, `place_of_birth`, normalised with C's `countries.normalise`; drop "International" and "Europe".
- Dated reports: only English lines exactly of the form `According to <source>; <date>: <text>`. `earliest_report` = the earliest date.
- Death: `deceased_date` (and `life_status`).
- Companies: `incorporated` only from `dobs`.
- Fill `missing` with what was not found.

**notes.py**: `parse(note) -> NoteFacts` (a small dataclass of your own: `verified` (bool), `rejected` (bool), `name`, `dob` (PartialDate), `doc_country`, `lived_in` (list), `date`). Recognise the onboarding team's verification sentences (provider validated or completed identity verification of NAME, born or DOB ..., document from or issued in COUNTRY) and failure wordings (rejected, could not verify, expired). Recognise "used to live in", "moved from", "previously lived in" style phrases for lived-in places. **Read many notes in `data/dev/notes.jsonl` and build patterns from the shapes, not from specific values.** Unseen notes may be worded differently, so return "unknown" rather than guess.

### C. Matchers (`@kendricklow2008`)

**names.py**: principle 8, exactly.
- `parts(name, company=False) -> List[str]`: lowercase, strip accents (`unicodedata`), drop punctuation and anything in brackets, split; drop single letters (initials), placeholders (`na`, `n/a`, `test`, `unknown`, `xxx`, `none`, digits) and, for companies, legal forms. Distinct parts once.
- `parts_match(a, b) -> bool`: identical; same variant group; or edit distance ≤ 1 for parts of 4 to 6 letters, ≤ 2 for 7+, with the **shorter** part deciding; parts under 4 letters must be identical. Swapping two letters is 2 edits (plain Levenshtein, **not** Damerau).
- `names_agree(a, b, company=False) -> bool`: at least two parts match, or every part of the shorter name matches. Handle joined or split parts (`abdulsalam` vs `abdul salam` count as **one** part covering both).
- `real_part_count(name) -> int` (individuals with fewer than 2 can be neither confirmed nor cleared on name).
- Built-in `VARIANTS` and `LEGAL_FORMS` from the Policy tab; prefer `name_variants.json` from the data folder when present.

**dates.py**:
- `parse(s) -> Optional[PartialDate]`: `YYYY-MM-DD`, `YYYY-MM`, `YYYY`, `DD/MM/YYYY` (**dev data is always day first**: 6,348 values have the first part over 12, none the second), `Month D, YYYY`, `D Month YYYY`, `Month YYYY`. Unknown parts stay `None`; never fill them in.
- `same_in_shared_parts(a, b)`: equal in every part both give.
- `birth_agrees(customer: PartialDate, claim: BirthClaim)`: customer year in `claim.years`, and month and day equal wherever both give them. A year alone agrees with a full date.
- `birth_contradicted(customer, claim)`: customer year more than 1 outside **every** year of the claim, **or** same year and both give a month and the months (or days) differ.
- `younger_than(dob, at: PartialDate, years=16) -> bool`: true only if **certainly** younger (use the oldest possible age when parts are missing).
- `before(a, b) -> Optional[bool]`: `None` when it cannot be told.

**countries.py**: `normalise(s) -> Optional[str]` mapping ISO-2 and ISO-3 codes, country names, common nationalities ("British", "Nigerian", ...) and demonyms to one canonical name; territories stay their own country; "International" and "Europe" → `None`. `from_address(addr)` = normalise the last comma-separated part. Built-in table in code is fine (it is general knowledge, not dev data).

### D. Model, judge, output (`@ThomasGrattoniMay`)

**judge.py**: `decide(hit: HitProfile, res: Resolution, alert) -> Decision`. Principles 3, 6, 7.

Per person (`decide_one(hit, person, alert)`), first match wins:
1. Person has no usable facts → `REVIEW / INSUFFICIENT_DATA`.
2. Entity types differ → `DIFFERENT_ENTITY / ENTITY_TYPE_MISMATCH`.
3. Hit `deceased` before `alert.screened_at` → `DIFFERENT_ENTITY / DECEASED`.
4. Individual certainly younger than 16 at `earliest_report`, or company incorporated after it → `DIFFERENT_ENTITY / TEMPORAL_IMPOSSIBILITY`.
5. Compute `name_ok` (any person name agrees with any hit name; use `verified_name` when present), `dob_ok` (any person dob agrees with any claim; `verified_dob` first), `shared_country`. An individual whose names have fewer than 2 real parts gets `name_ok = False` and can never be cleared on name (step 7), unless a single-part **hit alias** agrees with their name.
6. Hit gives births and **every** claim is contradicted by the customer's dob → `DIFFERENT_ENTITY / DOB_MISMATCH`. One agreeing claim blocks this.
7. `verified_name` exists, has at least 2 real parts, and agrees with **none** of the hit's names → `DIFFERENT_ENTITY / NAME_MISMATCH_VERIFIED`.
8. Both sides have countries and they share none: if `name_ok and dob_ok` → `REVIEW / INSUFFICIENT_DATA`, else `DIFFERENT_ENTITY / LOCATION_MISMATCH`.
9. Individual: `name_ok and dob_ok` → `SAME_ENTITY / NAME_DOB_LOCATION_MATCH` if `shared_country`, else `NAME_DOB_MATCH`. Company: `name_ok and shared_country` → `SAME_ENTITY / NAME_LOCATION_MATCH`.
10. Otherwise `REVIEW / INSUFFICIENT_DATA`.

Across people: 0 people → step 1 and 2 only (we cannot know the customer), `customer_record_id = null`. 1 person → its decision, `customer_record_id = person_id`. Several → decide each; all equal → that decision with `customer_record_id = "AMBIGUOUS"`; otherwise `REVIEW / AMBIGUOUS_CUSTOMER_RECORD`, `"AMBIGUOUS"`.

**explain.py**: reason text from templates, 2 to 4 sentences, naming this hit's facts and their source IDs. Example shapes (written by us, mirroring the practice labels' style): "The customer's date of birth 1980-01-02 (KYC-...) agrees with the hit's 1979 or 1980. Both the customer and the hit are linked to Portugal. The customer's name agrees with the hit's name ...". For `REVIEW`, say what is missing. **Evidence**: the person's record IDs plus the source IDs of the deciding facts (`KYC-`, `NOTE-`, `SR-`). Practice labels never cite `H-` or `ACC-` IDs; follow that. Sorted, no duplicates.

**main.py + run**: one `load`, then per alert one `resolve`, per hit `extract` → `decide` → write one JSON line. Wrap each hit in `try/except`: on any error write `REVIEW / INSUFFICIENT_DATA` and log to stderr, never crash. Output sorted by `alert_id`, `hit_id`.

**tools/score.py**: read output + practice labels; print cost per the matrix in [BRIEF.md](BRIEF.md), the decision score (cost saved versus all-`REVIEW`), unsafe clearances, review rate, reason-code accuracy (any listed code accepted), `customer_record_id` accuracy (any of the listed IDs accepted), and a per-hit diff table with the label's `path` for every miss.

## 6. Open decisions (lead decides; defaults below are what we build unless changed)

| Question | Default |
|---|---|
| Zero people found: judge on the screened details? | No: only entity-type mismatch can clear, everything else `REVIEW` |
| Phone for merging: customer record phone only, or account phones too? | Customer record phone only; A checks the practice paths and reports |
| Name for agreement when a verified name exists | Verified name for both agreement and mismatch; record names only when there is no verified name |
| Link leads to several holders and none fit the screened details | Keep all as candidates (judge treats as several people) |
| Order of contradictions when several fire | As in section 5D (any code that applies is accepted) |

## 7. Working rules

- Branch `<issue#>-<slug>` or `<module>-<slug>` from fresh `main`; small PRs; merge your own once `system/run` still works and `tools/score.py` is not worse.
- Unit tests use **made-up** values only. Never copy dev records into tests, docs, the board or commits.
- After every merge that changes a shape or a function signature, post on the board and tag who depends on it.
- If a practice label disagrees with the SOP, the SOP wins. Post the hit ID on the board.
