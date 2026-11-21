# Tryll: 2-minute video script

For the submission video (2:00 hard limit). Five parts: problem, engine and numbers, one human review, safety, close. Each part lists the shot, what to click, and the voice-over. Voice-over is about 150 words a minute, so each line fits its slot when read at a calm pace.

## Rule for everything on screen

**Never show the dataset.** The GUI on `data/dev` displays real records (names, notes, KYC rows), and the data is for event participants only. So:

- Record the GUI on our **invented** fixture folder, `tests/fixtures/rare` (every name, date and ID in it is made up).
- Numbers come only from our own output and scorer (they are in `system/README.md`).
- No terminal or editor window that shows `data/`, and no browser tab with a dev record.

## Setup before recording

1. `.env` holds `XAI_API_KEY` (needed for the AI court in part 3). Never show `.env` or a terminal that prints it.
2. Start the GUI on the invented data:

   ```
   py -3 -X utf8 demo/app.py tests/fixtures/rare
   ```

   then open http://127.0.0.1:8765. Wait for the queue to load before recording.
3. Browser at 1920×1080, light theme, zoom 110% so text reads on a phone. Close every other tab.
4. Use two reviewer names for the four-eyes step: **"Analyst A"** (maker) and **"Analyst B"** (checker). Sign in as Analyst A first.
5. Clean audit log so the queue starts fresh: set `CASE_REVIEW_DB` to a new temp file before starting the server.
6. Have the title cards (part 1, 2, 4, 5) as full-screen slides: white text on dark, one idea per card.

The cases used, both invented:

| Hit | Why it is a good shot |
|---|---|
| `H-RC07` Lucan Ferreby | Name and date of birth agree but the countries differ. The SOP says that is **not** enough to clear, so the engine sends it to a human. Shows judgement, not a rubber stamp. |
| `H-RC05` Imre Castellane | Two different customers fit the alert and lead to different answers, so the engine refuses to guess (backup shot if time allows). |

## Shot list

### 0:00 – 0:15 · The problem (15 s)

**Shot:** title card, then cut to the GUI queue (many rows, three colours).

**Voice-over (≈35 words):**
> A bank screens every customer against sanctions lists. Most hits are namesakes, but each one needs an analyst. Clear a real match by mistake and the bank is exposed. Review everything and the team drowns.

**On-screen text:** "Tryll" then "Is the hit the customer?"

### 0:15 – 0:45 · The engine and its numbers (30 s)

**Shot:** card with four numbers, then the GUI queue with the decision filter clicked through *Cleared*, *Confirmed*, *Review*.

**Card:**
- 50 / 50 practice hits right · **0 unsafe clearances**
- 819 hits in under 40 s · rules only, no model needed
- Byte-identical on every run
- 0 decisions moved under 5 stress rewrites of the data

**Click:** queue filter *Cleared* → *Confirmed* → *Review*.

**Voice-over (≈75 words):**
> Tryll follows the bank's procedure literally. It works out who the customer really is across five systems, merges duplicate records, and trusts a verified identity check over what was typed in. It clears a hit only on a contradiction the procedure names, confirms only on agreement, and otherwise asks a human. On the practice set it gets fifty out of fifty with zero unsafe clearances, runs the whole set in under forty seconds, and gives the same answer every time.

### 0:45 – 1:35 · One human review, with the AI court and four-eyes (50 s)

**Shot:** open `H-RC07` from the *Needs decision* queue.

**Clicks, in order:**
1. Open `H-RC07`. Point at the side-by-side comparison: name **agree**, date of birth **agree**, country **contradict**. *(≈8 s)*
2. Point at the engine's recommendation: **Review**, and its "what would settle this" line. *(≈5 s)*
3. Tick the customer record and the hit's record, then ask the AI court: **Prosecution**, **Defence**, **Adjudicator**. Let the adjudicator's summary and its cited IDs show. *(≈15 s)*
4. As Analyst A: choose **Escalate**, pick the reason code, cite the ticked records, type a one-line rationale, submit. The case moves to the escalated or pending list. *(≈10 s)*
5. Switch to Analyst B and show a different case waiting for approval: **Approve**. Then show that Analyst A cannot approve their own decision (the four-eyes refusal). *(≈8 s)*
6. Flash the audit history on the case. *(≈4 s)*

**Voice-over (≈125 words):**
> Here is a hit the engine would not decide alone. The name and date of birth agree, but the countries do not, and the procedure says that is not enough to clear. So it recommends a human review and says what would settle it. The analyst ticks the records they trust and asks our AI court: a prosecution, a defence and a neutral adjudicator argue only over those records, and every claim cites its evidence. The analyst makes the call, with a reason code, the records and a rationale. Nothing is final until a second person approves it. The system enforces four eyes, so you cannot approve your own decision, and every step goes into an audit log that cannot be edited.

### 1:35 – 1:50 · Safety (15 s)

**Shot:** card with two lines, then back to the GUI header showing the cross-examiner chip.

**Card:**
- Blindfold test: note parser switched off → rules alone **5 unsafe**, with the Grok cross-examiner **0 unsafe**
- The language model can turn a clearance into a review. **It can never create one.**

**Voice-over (≈37 words):**
> We stress-tested the safety net. With our note reader switched off, the rules alone made five unsafe clearances. Grok, reading the raw text, caught all five. And by design the model can only send a clearance back, never make one.

### 1:50 – 2:00 · Close (10 s)

**Shot:** card with the project name and the team.

**Card:** "Tryll · same person or not? · deterministic SOP engine · human-in-the-loop review" and the four names.

**Voice-over (≈25 words):**
> Rules you can audit, AI that can only make it safer, and a human who signs every call. That is Tryll.

## Checks before uploading

- Total length 2:00 or less (the form says 2 minutes, not 3).
- Pause on every frame and check: no name, date, note or ID appears that is not from `tests/fixtures/rare` or our own output.
- No `.env`, key or `data/` path visible anywhere.
- Upload as unlisted (YouTube, Loom or Drive) and test the link in a private window.

## To align once the BoardUI rebuild is up

The clicks above use generic names (queue filter, comparison, recommendation, AI court, decide, approve, audit history). When the new GUI lands, replace them with the exact button labels and check that `H-RC07` still shows name and date of birth **agree** and country **contradict** on the invented data.
