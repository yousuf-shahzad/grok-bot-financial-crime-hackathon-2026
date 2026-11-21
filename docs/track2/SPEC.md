# Track 2 decision spec (the bank's identity SOP, condensed)

This is our working summary of `POLICY.md`, the bank's identity SOP that ships with the data. **The SOP is the authority**: the unseen set is scored against it. The verbatim text is in `data/dev/policy_sheet.txt` (gitignored, with the data). When this file and the verbatim SOP differ, the SOP wins and this file gets fixed.

The SOP's own wording says the formats and phrases quoted below are worded the same in the unseen set, so matching them exactly is allowed and expected.

## 0. Core stance

- Decide **identity only** ("is the hit the customer?"), never seriousness or acceptability.
- Wrongly clearing a real match costs 60, so **when in doubt: `REVIEW`**.
- **Clear only on a contradiction. Confirm only on agreement. Otherwise `REVIEW`.**

## 1. Know who the customer is (principles 2, 3, 4)

The alert shows the customer *as screened* (name, entity type, dob, country, city, plus optional links). The real picture is spread over: system of record (`customers`), `accounts`, `onboarding`, KYC provider (`kyc_checks`) and the support tool (`notes`). They share no single key.

**Step A: find the candidate customer records.**
- Follow whatever link the alert carries: `account_ref` → accounts → `customer_id`; `login_handle` → accounts → `customer_id`; `email` → customers.
- A link can lead to **more than one person** (for example joint holders of an account). Then the screened details pick between them, exactly as in a search without a link.
- With **no link**, find records that fit what was screened: a full, preferred or login name that agrees with the screened name (rule in section 5, screened names can hold nicknames and typos); a date of birth equal to the screened one in **every part both give**; the screened country as residence **or** nationality; the screened city in the record's city or address.
- **Never use another customer's records.**

**Step B: merge records into one person.**
- Records that share a **phone number AND the same full date of birth** are one person.
- Records whose **approved** identity checks carry the **same document number** are one person.
- A record linked to either of those in either way is also that person. All their facts count.
- A shared phone **or** address alone does **not** merge anyone (families share them).

**Step C: ambiguity.**
- If more than one person fits, decide the hit **for each** person. If all lead to the same decision, give it. If they differ: `REVIEW` with `AMBIGUOUS_CUSTOMER_RECORD`.
- Either way `customer_record_id` = `"AMBIGUOUS"`.
- When one person has several records, **any** of them is accepted as `customer_record_id`.

**Step D: pick the most reliable facts.**
- The **most recent approved** identity check of the person is the most reliable source for **legal name, date of birth and document country**. It may be a row in `kyc_checks` (via onboarding `kyc_applicant_id` → `applicant_id`) **or only a note** by the onboarding team (`notes`, keyed by email: a sentence saying a provider validated a named person's ID, with their date of birth and country).
- **Rejected or expired checks are not evidence.**
- The verified legal name **outranks** the record name and the screened name (which can be nicknames, login names or typos).

## 2. Gather the hit's facts (principle 5)

A hit's date of birth can be in three places, in this order of preference:
1. `dobs` field.
2. A sentence in the **first paragraph** of `profile_notes`. An age at a date gives **two possible birth years**: "aged 45 in March 2019" means born in 1973 or 1974.
3. Only if neither gives one: **web search results** (`search_results`) for the hit's name. The `query` is the name's lowercase words in **alphabetical order**.

**Search results are mostly about namesakes.** A result is about the hit only if it describes the **same kind of listing** in a **country tied to the hit**. The kind of listing follows the hit's primary category (or its first category):

| Primary category | The result must describe |
|---|---|
| Sanctions | "a sanctioned individual" |
| PEP | "a politically exposed person" |
| Enforcement | "the subject of enforcement action" |
| Adverse Media | "named in adverse media" |
| SOE | "a state-owned enterprise official" |
| anything else | "named on a watchlist" |

**Countries tied to a hit:** its `countries`, `nationality`, `citizenship`, `addresses` (the last part of each address) and `place_of_birth`. "International" and "Europe" are **not** countries.

**Dated reports** are exactly the English lines in the profile notes of the form `According to <source>; <date>: <text>` (the date may be a full date, a month and year, or a year). Other wordings do not count. Dates inside hit profiles are written as the provider wrote them (full dates, month and year, year only). For **companies**, only the `dobs` field is an incorporation date.

## 3. Clear only on a contradiction (principle 6)

A hit is `DIFFERENT_ENTITY` **only** if one of these holds:

| Check | Clear when | Reason code |
|---|---|---|
| **Time** | The customer was **younger than 16** at the earliest dated report; or a company was incorporated **after** it; or the profile gives a **date of death before the customer was screened** | `TEMPORAL_IMPOSSIBILITY` (age or incorporation), `DECEASED` (death date) |
| **Date of birth** | **Every** birth date the hit gives is contradicted: the customer's birth year is **more than 1 year outside** it, or both give a month in the same year and the months (or days) differ. **One agreeing date is enough to prevent this** | `DOB_MISMATCH` |
| **Location** | **Every** country tied to the customer (residence and nationality on all their records, the approved identity document country, and places the notes say they lived) differs from **every** country tied to the hit. Codes and nationalities are countries; territories count as their own country | `LOCATION_MISMATCH` |
| **Name** | The customer's **verified legal name** agrees with **none** of the hit's names or aliases, even if the name on their record does | `NAME_MISMATCH_VERIFIED` |
| **Type** | One is a person and the other a company | `ENTITY_TYPE_MISMATCH` |

**Exception:** a country difference does **not** clear a hit whose name and date of birth agree. That hit is `REVIEW`.

## 4. Confirm only on agreement (principle 7)

- **Dates of birth agree** when the customer's birth year is **one of the hit's possible birth years** and **every part both give** (month, day) is equal. A birth year alone can agree with a full date.
- Confirm a **person** (`SAME_ENTITY`) when **name and date of birth agree and nothing contradicts them**.
- Confirm a **company** when **name and country agree and nothing contradicts them**.
- Otherwise `REVIEW`.

## 5. Names (principle 8)

Compare name **parts**, ignoring case, accents, punctuation and anything in brackets. Single letters are initials, not parts. Each distinct part counts once.

Two parts **match** when any of these holds:
1. They are identical.
2. They are listed together in `name_variants.json` (a group such as `muhammad, mohammed, mohammad, mohamed, ...`, or `thomas, tom, tommy, ...`).
3. They are written together or apart (`Abdulsalam` matches `Abdul Salam`, counting as **one** part that covers both).
4. They differ by at most **1 edit** for parts of 4 to 6 letters, **2 edits** for longer parts. An edit adds, removes or changes one letter, so **swapping two letters is two edits**. Parts **shorter than 4 letters must be identical**. The **shorter** part's length decides the allowance.

**Names agree** when **at least two parts match, or every part of the shorter name matches.** Aliases count as names, nicknames included.

**Placeholders** (`NA`, `N/A`, `TEST`, `UNKNOWN`, `XXX`, `NONE`, digits and the like) are not name parts. An individual customer with fewer than two real name parts can be **neither confirmed nor cleared on name**. A hit's single-part alias can still agree with a customer's name.

For **companies**, the legal forms in `name_variants.json` (`ab, ag, as, asa, bv, co, company, corp, corporation, gmbh, inc, kg, limited, llc, llp, lp, ltd, na, nv, oy, oyj, plc, sa, sarl, sas, se, sf, sl, spa, srl`) are not name parts.

## 6. Cite what you used (principle 9)

Every decision names the records it relied on by ID, and the customer record it resolved (`null` if none). Cite what **decided** the hit, not everything looked at. Evidence IDs seen in practice labels: `CUS-...` (customer), `NOTE-...`, `KYC-...`, `SR-...` (search result), `H-...` (hit), `ACC-...`, `APP-...`.

## 7. Reason codes

The reason code must **belong to the decision**. When several apply, any of them is accepted.

| Decision | Reason code | Use it when |
|---|---|---|
| `DIFFERENT_ENTITY` | `TEMPORAL_IMPOSSIBILITY` | The customer could not have done what the profile reports: too young, or not yet incorporated, at the earliest dated report |
| `DIFFERENT_ENTITY` | `DOB_MISMATCH` | The customer's date of birth (or a company's incorporation date) contradicts every birth date the hit gives |
| `DIFFERENT_ENTITY` | `LOCATION_MISMATCH` | Every country tied to the customer differs from every country tied to the hit |
| `DIFFERENT_ENTITY` | `NAME_MISMATCH_VERIFIED` | The customer's verified legal name does not agree with any of the hit's names |
| `DIFFERENT_ENTITY` | `ENTITY_TYPE_MISMATCH` | One is a person and the other a company |
| `DIFFERENT_ENTITY` | `DECEASED` | The hit's profile gives a date of death before the customer was screened |
| `SAME_ENTITY` | `NAME_DOB_LOCATION_MATCH` | Name, date of birth and country all agree and nothing contradicts them |
| `SAME_ENTITY` | `NAME_DOB_MATCH` | Name and date of birth agree and nothing contradicts them |
| `SAME_ENTITY` | `NAME_LOCATION_MATCH` | Companies only: name and country agree and nothing contradicts them |
| `REVIEW` | `INSUFFICIENT_DATA` | Nothing settles it: no contradiction, and not enough agreement to confirm |
| `REVIEW` | `AMBIGUOUS_CUSTOMER_RECORD` | More than one person in the system of record fits the alert and they lead to different decisions |

## 8. Decision procedure (suggested skeleton, not mandated)

For each hit:

1. Resolve the customer (sections 1A to 1D). No usable customer facts at all → `REVIEW` / `INSUFFICIENT_DATA`.
2. Several people fit and decisions differ → `REVIEW` / `AMBIGUOUS_CUSTOMER_RECORD`, `customer_record_id = "AMBIGUOUS"`.
3. Extract the hit's facts (section 2).
4. Test the contradictions (section 3), most certain first. Apply the "name and date of birth agree" exception before clearing on location.
5. If none fire, test agreement (section 4). If it holds, `SAME_ENTITY`.
6. Else `REVIEW` / `INSUFFICIENT_DATA`.
7. Write the reason (own facts, 2 to 4 sentences) and cite only the deciding IDs.
