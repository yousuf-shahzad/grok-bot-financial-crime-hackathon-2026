# Track 2 data guide

**The data is for event participants only. Never commit it, paste records into the board, issues, PRs or commit messages, or upload it anywhere public.** Cite record IDs instead. Everything is invented or pseudonymised, and the watchlist profiles come from a screening provider.

## What we have, and where it lives

| What | Where | Status |
|---|---|---|
| Browse workbook `ScreeningDevSet-browse.xlsx` (24 MB, all tabs, no answers except the 50 practice labels) | `data/` (gitignored) | Downloaded. Source: the event page's Track 2 "Get the dataset" link (Google Sheets, export as xlsx). Anyone can re-download it the same way. |
| JSON Lines converted from the workbook | `data/dev/` (gitignored) | Made by `python tools/xlsx_to_jsonl.py data/ScreeningDevSet-browse.xlsx data/dev` (about 30 s). **An approximation** of the official files, see caveats below. |
| Official `dev/` JSON Lines, `POLICY.md`, `name_variants.json`, `validate.py` | The event's data room | **We do not have these yet.** Ask the organisers in Discord or at the 10:30 kick-off where the data room is. |

Python note: use `py -3.14 -X utf8 ...` on Windows (the default `python` is 3.7, and the default console encoding breaks on some characters).

## Files and links between them

The unseen set comes in the same format as the official `dev/` folder. The brief says the JSON Lines files are the source of truth.

| File (workbook tab) | Rows | Key columns |
|---|---|---|
| `alerts.jsonl` (Alerts) | 440 | `alert_id`, `screened_at`, `customer_name`, `entity_type`, `dob`, `country`, `city`, `account_ref`, `login_handle`, `email`, `hit_count`, `hit_ids` |
| `hits.jsonl` (Hits) | 819 | `hit_id`, `alert_id`, `match_score`, `entity_type`, `name`, `aliases`, `gender`, `dobs`, `place_of_birth`, `life_status`, `deceased_date`, `nationality`, `citizenship`, `countries`, `addresses`, `identifiers`, `categories`, `primary_category`, `position_or_allegation`, `details`, `relationships`, `profile_notes`, `sources`, `source_urls` |
| `customers.jsonl` (Customers) | 72,265 | `record_id` (`CUS-...`), `entity_type`, `full_name`, `preferred_name`, `login_name`, `dob`, `nationality`, `residence_country`, `city`, `address`, `email`, `phone`, `occupation`, `employer`, `registration_number`, `onboarded_at`, `status`, `last_kyc_refresh` |
| `accounts.jsonl` (Accounts) | 86,659 | `account_id` (`ACC-...`), `customer_id`, `login_handle`, `phone`, `opened_at`, `status` |
| `onboarding.jsonl` (Onboarding) | 72,265 | `account_id`, `customer_id`, `kyc_applicant_id` (`APP-...`), `onboarded_at` |
| `kyc_checks.jsonl` (KYC checks) | 54,488 | `check_id` (`KYC-...`), `applicant_id`, `provider`, `verified_name`, `verified_dob`, `document_type`, `document_number`, `document_country`, `result` (`approved`/`rejected`/`expired`), `checked_at` |
| `notes.jsonl` (Notes) | 31,895 | `note_id` (`NOTE-...`), `requester_email`, `created_at`, `channel`, `text` |
| `search_results.jsonl` (Search results) | 16,882 | `result_id` (`SR-...`), `query`, `title`, `snippet`, `source` |
| `practice_labels.jsonl` (Practice labels) | 50 | `hit_id`, `alert_id`, `decision`, `reason_codes`, `customer_record_ids`, `evidence`, `reference_reason`, `path` |

### Join paths

```
Alerts.hit_ids                       -> Hits.hit_id
Alerts.account_ref                   -> Accounts.account_id -> Accounts.customer_id -> Customers.record_id
Alerts.login_handle                  -> Accounts.login_handle -> Customers.record_id
Alerts.email                         -> Customers.email
Accounts.account_id + customer_id    -> Onboarding.account_id + customer_id -> Onboarding.kyc_applicant_id -> KYC checks.applicant_id
Customers.email                      -> Notes.requester_email
Hit name                             -> Search results.query   (the name's lowercase words in alphabetical order)
No link on the alert                 -> search Customers for records that fit the screened name and attributes
```

## What the dev set looks like (measured on the workbook)

- **440 alerts**: 395 individuals, 45 companies. **819 hits** (702 individual, 117 company). Most alerts have one hit (344), a few have up to 15.
- **Alert links**: 170 carry `account_ref`, 70 `login_handle`, 54 `email`, **146 carry no link at all** (a third), so a good no-link customer search is essential.
- **Alert dob**: 204 ISO full dates, 34 year-only, 188 blank.
- **Hit `dobs`**: present on only **152 of 819** hits (118 year-only, 31 full dates). For the other 667 the DOB must come from the profile notes or search results.
- **Hit primary category**: PEP 160, Enforcement 145, Adverse Media 87, Sanctions 50, Registration 23, SOE 7, other 2, blank 345 (the SOP says to use the first category if the primary is blank).
- **Customers**: 64,746 individuals, 7,519 companies. Status: active 61,276, closed 7,289, dormant 3,700.
- **KYC checks**: 49,574 approved, 2,481 rejected, 2,433 expired. 1,850 have a blank `verified_dob`.
- **Mixed date formats** in customers and KYC checks: `YYYY-MM-DD` (most), `DD/MM/YYYY`, `Month D, YYYY`, and some `D Month YYYY`. Parse all of them. **Slash dates are day first** (`DD/MM/YYYY`): of 11,015 slash dates in customers, 6,348 have a first part over 12 and none has a second part over 12, so the data itself settles the convention. Lead's decision: read every slash date day first, including ambiguous ones like `03/04/2004` (3 April 2004).
- **Practice labels (50)**: 28 `DIFFERENT_ENTITY`, 12 `SAME_ENTITY`, 10 `REVIEW`. Reason codes seen: `LOCATION_MISMATCH` (18 incl. combos), `INSUFFICIENT_DATA` (10), `NAME_DOB_LOCATION_MATCH` and `NAME_DOB_MATCH` (8 together), `DOB_MISMATCH` (7 incl. combos), `NAME_LOCATION_MATCH` (4), `NAME_MISMATCH_VERIFIED` (7 incl. combos), `TEMPORAL_IMPOSSIBILITY` (1). `AMBIGUOUS_CUSTOMER_RECORD` and `DECEASED` and `ENTITY_TYPE_MISMATCH` do not appear in the 50 but are in the SOP and the unseen set ("some situations are rare in the dev set"). Do not assume the 50 are representative.

The practice labels carry a `path` column showing exactly how the reference answer was reached (for example `account_ref ACC-... -> accounts: joint holders CUS-A and CUS-B -> the screened name and date of birth fit CUS-A -> customer email -> notes -> NOTE-... -> SAME_ENTITY`). Read several before designing the resolver.

## Caveats about the workbook-derived JSONL

- Lists are flattened to `"a; b; c"` strings (for example `aliases`, `dobs`, `countries`, `categories`). The official files probably have real lists. **Write the parser to accept both** a list and a `;`-joined string.
- Empty values are `null`; numbers such as `hit_count` come through as strings like `"1.0"`.
- Long text is cut at 32,000 characters.
- The workbook has no `validate.py`. Until we get it, write our own scorer against `practice_labels.jsonl` (decision and reason code, cost table in [BRIEF.md](BRIEF.md)).
- Because the official files are the source of truth, **`system/` must read the official format**. Treat `data/dev/` as a development convenience only.
