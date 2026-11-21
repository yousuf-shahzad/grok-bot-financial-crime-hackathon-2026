# Tryll: 2-minute video script

For the submission video (2:00 hard limit). Built from [OVERVIEW.md](OVERVIEW.md); if a number there changes, change it here too. Five parts: problem, engine and numbers, one human review, safety, close. Each part lists the shot, what to click, and the voice-over. Voice-over is about 150 words a minute, so each line fits its slot when read at a calm pace.

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
4. Two reviewers for four-eyes: sign in as **"Analyst A"** (role analyst) first; you will switch to **"Analyst B"** (role checker).
5. Before recording, as Analyst A, decide one other case (for example `H-RC08`) so the **To approve** queue has something for Analyst B in part 3.
6. Title cards for parts 1, 2, 4 and 5 as full-screen slides: white text on dark, one idea per card.
7. Check the board for the latest dual-path number (OVERVIEW.md section 4 note) and use whatever is current on the day.

The cases used, both invented:

| Hit | Why it is a good shot |
|---|---|
| `H-RC07` Lucan Ferreby | Name and date of birth agree but the countries differ. The SOP says that is **not** enough to clear, so Tryll sends it to a person. Shows judgement, not a rubber stamp. |
| `H-RC08` Daria Holtzmann | Decided by Analyst A before recording, so it waits in **To approve** for the four-eyes shot. |

## Shot list

### 0:00 – 0:15 · The problem (15 s)

**Shot:** title card "Tryll", then "Is the hit the customer?", then cut to the GUI **Overview** with its four stat cards.

**Voice-over (≈35 words):**
> Banks screen every customer against sanctions lists. Most hits are namesakes, but each one needs an analyst. Clear a real match by mistake and a sanctioned person stays a customer. Review everything and the team drowns.

### 0:15 – 0:45 · The engine and its numbers (30 s)

**Shot:** card with four numbers, then the **To decide** queue in the sidebar.

**Card:**
- 50 / 50 practice hits right · **0 unsafe clearances**
- 819 hits in about 25 s · rules only, no model needed
- Byte-identical on every run
- 0 decisions moved under 5 stress rewrites of the data

**Voice-over (≈75 words):**
> Tryll follows the bank's procedure literally. It works out who the customer really is across five systems, merges duplicate records, and trusts a verified identity check over what was typed in. It clears a hit only on a contradiction the procedure names, confirms only on agreement, and otherwise asks a person. On the practice set it gets fifty out of fifty with zero unsafe clearances, runs the whole set in under half a minute, and gives the same answer every time.

### 0:45 – 1:35 · One human review, with the AI court and four-eyes (50 s)

**Shot:** open `H-RC07` from **To decide**. The case opens full width.

**Clicks, in order:**
1. Point at the **verdict strip** (rules engine → Grok judge → screening agent → recommendation), then the **Summary** tab: name **Same**, date of birth **Same**, country **Different**, each with its source record. *(≈8 s)*
2. Point at **What would settle this**. *(≈4 s)*
3. **Evidence** tab: tick the customer record and the hit's record. **AI court** tab: run prosecution, defence, adjudicator. Let the adjudicator's summary and cited IDs show. *(≈15 s)*
4. **Decision card**: Escalate, pick the reason code, keep the ticked records, type a one-line rationale, submit. *(≈9 s)*
5. Switch reviewer to Analyst B (checker). Open `H-RC08` from **To approve**: **Approve**. Then, as Analyst A, try to approve something they decided themselves and show the refusal. *(≈10 s)*
6. **History** tab: the append-only audit trail. *(≈4 s)*

**Voice-over (≈125 words):**
> Here is a hit Tryll would not decide alone. The name and date of birth agree, but the countries do not, and the procedure says that is not enough to clear. So it recommends a human review and says what would settle it. The analyst ticks the records they trust and asks our AI court: a prosecution, a defence and a neutral adjudicator argue only over those records, and every claim cites its evidence. The analyst makes the call, with a reason code, the records and a rationale. Nothing is final until a second person approves it. Tryll enforces four eyes, so you cannot approve your own decision, and every step goes into an audit log that the database itself refuses to edit.

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

## When the BoardUI restyle is final

Labels above follow OVERVIEW.md section 6. When Yousuf posts that the GUI is final, click through the shot list once on the invented data and fix any label that changed (queue names, tab names, decision buttons), and check that `H-RC07` still shows name and date of birth **Same** and country **Different**.
