# Tryll: 2-minute video script

For the submission video (2:00 hard limit). Built from [OVERVIEW.md](OVERVIEW.md); if a number there changes, change it here too. Five parts: intro (John Smith), engine and numbers, one human review, safety, close. Each part lists the shot, what to click, and the voice-over. Voice-over is about 150 words a minute, so each line fits its slot when read at a calm pace.

## Rule for everything on screen

**Never show the dataset.** The GUI on `data/dev` displays real records (names, notes, KYC rows), and the data is for event participants only. So:

- Record the GUI on our **invented** fixture folder, `tests/fixtures/rare` (every name, date and ID in it is made up).
- Numbers come only from our own output and scorer (OVERVIEW.md section 4).
- No terminal or editor window that shows `data/`, and no browser tab with a dev record.

## Setup before recording

1. `.env` holds `XAI_API_KEY` (needed for the AI court and the verdict strip's Grok steps). Never show `.env` or a terminal that prints it.
2. Point the audit log at a fresh temp file so the queues start clean (set `CASE_REVIEW_DB` to a new path), then start the GUI on the invented data:

   ```
   py -3 -X utf8 demo/app.py tests/fixtures/rare
   ```

   and open http://127.0.0.1:8765. Wait for the queues to load before recording.
3. Browser at 1920×1080, light theme, zoom 110% so text reads on a phone. Close every other tab.
4. Two reviewers for four-eyes. On the **Welcome to Tryll** sign-in, enter **"Analyst A"** with role **Analyst**. Later you switch with the **Switch reviewer** icon next to the name in the sidebar and sign in as **"Analyst B"**, role **Checker**.
5. Before recording, as Analyst A, open `H-RC08` from **To decide** and submit **Match** (a reason, one record, a rationale) so the **To approve** queue has something for Analyst B in part 3.
6. Title cards for parts 1, 2, 4 and 5 as full-screen slides: white text on dark, one idea per card.
7. Check the board for the latest dual-path number (OVERVIEW.md section 4 note) and use whatever is current on the day.

The cases used, both invented:

| Hit | Why it is a good shot |
|---|---|
| `H-RC07` Lucan Ferreby | Name and date of birth agree but the countries differ. The SOP says that is **not** enough to clear, so Tryll sends it to a person. Shows judgement, not a rubber stamp. |
| `H-RC08` Daria Holtzmann | Engine says Match; decided by Analyst A before recording, so it waits in **To approve** for the four-eyes shot. |

## Shot list

### 0:00 – 0:30 · Intro: John Smith (30 s)

**Shot:** three title cards, then the GUI **Home** page.
1. "John Smith" (the customer) next to "JOHN SMITH" (a sanctions-list entry), with a red "MATCH?" between them.
2. The numbers: "85–90% of screening alerts are false positives" · "30–45 minutes for an analyst to clear each one" · "Miss a real one: £160,000 fine".
3. The hook: "Every John Smith deserves a fair trial." then "Tryll".

**Voice-over (≈76 words):**
> Meet John Smith. His name matches a man on a sanctions list, but he's almost certainly not that man: industry benchmarks say eighty-five to ninety percent of screening alerts are false positives, each taking an analyst up to forty-five minutes to clear. Wave through the wrong John Smith, though, and the fine is real: one UK bank paid a hundred and sixty thousand pounds. Every John Smith deserves a fair trial. That's why we built Tryll.

The figures are industry estimates, not audited studies: say "industry benchmarks say", never "studies prove" (sources at the end of this file). John Smith is an illustrative name only, not a record from the dataset.

### 0:30 – 0:50 · The engine and its numbers (20 s)

**Shot:** card with four numbers, then the **To decide** queue (a table: Watchlist hit, Listing, Engine says, Status).

**Card:**
- 50 / 50 practice hits right · **0 unsafe clearances**
- 819 hits in about 25 s · rules only, no model needed
- Byte-identical on every run
- 0 decisions moved under 5 stress rewrites of the data

**Voice-over (≈50 words):**
> Tryll rebuilds the customer from five bank systems, trusts verified identity checks, and applies the bank's procedure as code: clear only on a named contradiction, confirm only on agreement, otherwise ask a person. Fifty out of fifty on the practice set, zero unsafe clearances, the same answer every run.

### 0:50 – 1:35 · One human review, with the AI court and four-eyes (45 s)

**Shot:** click the `H-RC07` row in **To decide**. The case opens full width with "Back to To decide" at the top.

**Clicks, in order:**
1. Point at the **verdict strip** (Rules engine → Grok judge → Screening agent → Recommendation), then the **Summary** tab: the "Why" paragraph and the **Customer vs watchlist hit** table: Name **Same**, Date of birth **Same**, Countries **Different**, each with its source record. *(≈8 s)*
2. Point at **What would settle this**. *(≈4 s)*
3. **Evidence** tab: tick the customer record and the hit's record. **AI court** tab: run prosecution, defence, adjudicator. Let the adjudicator's summary and cited IDs show. *(≈12 s)*
4. **Your decision** card: **Escalate** ("Need more info"), pick the **Reason**, keep the **Records you rely on**, type a one-line **Rationale**, submit. *(≈9 s)*
5. **Switch reviewer** to Analyst B (Checker). Open `H-RC08` from **To approve**: **Approve**. Then, as Analyst A, try to approve something they decided themselves and show the refusal. *(≈10 s)*
6. **History** tab: the append-only audit trail. *(≈2 s)*

**Voice-over (≈110 words):**
> Here is a hit Tryll would not decide alone. The name and date of birth agree, but the countries do not, and the procedure says that is not enough to clear, so it asks a person and says what would settle it. The analyst ticks the records they trust and asks our AI court: a prosecution, a defence and a neutral adjudicator argue only over those records, citing each one. The analyst makes the call, with a reason, the records and a rationale. Nothing is final until a second person approves it: you cannot approve your own decision, and every step lands in an audit log that cannot be edited.

### 1:35 – 1:50 · Safety (15 s)

**Shot:** card with two lines.

**Card:**
- Blindfold test: note parser switched off → rules alone **5 unsafe**, with the Grok cross-examiner **0 unsafe**
- The AI can send a clearance back to a person. **It can never create one.**

**Voice-over (≈37 words):**
> We stress-tested the safety net. With our note reader switched off, the rules alone made five unsafe clearances. Grok, reading the raw text, caught all five. And by design the AI can only send a clearance back, never make one.

### 1:50 – 2:00 · Close (10 s)

**Shot:** card "Tryll · the machine recommends, a person decides, a second person approves" and the four names.

**Voice-over (≈25 words):**
> Rules you can audit, AI that can only make it safer, and a person who signs every call. That is Tryll.

## Checks before uploading

- Total length 2:00 or less (the form says 2 minutes, not 3).
- Pause on every frame and check: no name, date, note or ID appears that is not from `tests/fixtures/rare` or our own output.
- No `.env`, key or `data/` path visible anywhere.
- Upload as unlisted (YouTube, Loom or Drive) and test the link in a private window.

## Labels

Checked against the final GUI on main (#64) on the invented data: sidebar **Home**, **To decide**, **To approve**, **QA sample**, **Escalated**, **Closed**, **All hits**, with **Blind review** and the light/dark toggle at the bottom; case tabs **Summary**, **Evidence**, **AI court**, **History**; **Your decision** card with **Clear** / **Match** / **Escalate** (checkers see **Approve** / **Return**). `H-RC07` shows Name **Same**, Date of birth **Same**, Countries **Different**. Without a key the verdict strip shows "Grok judge: Off (no key)", so record with the key set. If the GUI changes again, click through once more before recording.

## Sources for the intro figures

Industry estimates, mostly from vendors; quote them as benchmarks, not as proven facts.

- 85–90% of alerts are false positives, 30–45 minutes per alert at first-level review: Everest Group 2025 benchmarking, as cited by [Sanctionscanner](https://www.sanctionscanner.com/blog/ai-powered-transaction-monitoring-how-to-reduce-false-positives-by-7080-1334). Other sources put it at 90% ([Sayari](https://sayari.com/resources/blog/financial-industry-compliance-challenges/)) or up to 99% for cross-border payments ([Retail Banker International](https://www.retailbankerinternational.com/comment/why-99-percent-sanctions-screening-alerts-false-positives/)).
- £160,000: OFSI's penalty on Bank of Scotland after a sanctioned person opened an account under a differently transliterated name that its screening did not match ([Duane Morris](https://blogs.duanemorris.com/europeansanctionsenforcement/?p=1136), [BCLP](https://www.bclplaw.com/en-US/events-insights-news/new-ofsi-decision-gives-best-guidance-yet-on-sanctions-due-diligence.html)).
