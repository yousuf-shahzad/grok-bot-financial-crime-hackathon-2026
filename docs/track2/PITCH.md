# Tryll: 3-minute live demo (top 5)

Talk track for the live demo, built from [OVERVIEW.md](OVERVIEW.md). What to say, what to click, and the questions judges are likely to ask with our answers. Diligent designed this track and its founders judge it, so speak their language: dispositions, audit trail, analyst workload, false positives, regulators.

**One presenter drives, one watches the clock.** Spoken text is about 150 words a minute; the timings leave a few seconds of slack.

## Same rule as the video

Demo **only** on the invented data in `tests/fixtures/rare`. Never open `data/dev` in front of anyone: it holds real records and the data is for participants only. Numbers come only from OVERVIEW.md section 4.

## Setup (10 minutes before)

1. Laptop on power, notifications off, one browser window, zoom 125% for the projector.
2. `.env` has `XAI_API_KEY`. Fresh audit log: set `CASE_REVIEW_DB` to a new temp path, then:

   ```
   py -3 -X utf8 demo/app.py tests/fixtures/rare
   ```

   Open http://127.0.0.1:8765 and sign in as **Analyst A** (analyst).
3. Pre-stage: as Analyst A, decide `H-RC08` (Match, a reason code, one record, a rationale) so **To approve** has a case for the four-eyes beat.
4. Run the AI court on `H-RC07` once so you know it works on this network. If it fails, use the fallback below.
5. Open the 2-minute video in a background tab as the last-resort fallback.

## Talk track

### 0:00 – 0:20 · Hook (≈45 words)

**Screen:** Tryll **Overview** (four stat cards).

> Every bank screens its customers against sanctions lists, and analysts spend their days deciding one question: is this hit really our customer? Clear a real match by mistake and a sanctioned person keeps their account. Tryll answers that question the way the bank's own procedure says to.

### 0:20 – 0:50 · What Tryll is (≈75 words)

**Screen:** stay on Overview, then click **Start reviewing**.

> Tryll works in three layers. First, rules: it rebuilds the customer from five bank systems, trusts a verified identity check over what was typed in, and applies the bank's SOP as code. It clears only when the SOP names a contradiction, confirms only on agreement, and otherwise asks a person. Second, Grok cross-examines every clearance and can only send it back. Third, a person makes every final call, and a second person approves it.

### 0:50 – 2:15 · Live review (≈200 words, clicks set the pace)

**Clicks and lines:**

1. Open `H-RC07` from **To decide**. Point at the verdict strip, then the **Summary** table.
   > Name: same. Date of birth: same. Country: different. Many tools would call this a match or clear it. The SOP says a country difference cannot clear a hit when name and date of birth agree, so Tryll hands it to a person, with every value traced to its source record.
2. Point at **What would settle this**.
   > It also says exactly what is missing, so the analyst knows what to ask the customer for.
3. **Blind review** switch on, then off.
   > With blind review on, our recommendation stays hidden until the analyst commits. That is the FCA's own good practice against anchoring.
4. **Evidence** tab: tick two records. **AI court** tab: run prosecution, defence, adjudicator.
   > The analyst chooses what the AI may read. A prosecution argues it is our customer, a defence argues it is not, and an adjudicator weighs both against the SOP. Every claim cites a record, and it is advisory only.
5. **Decision card**: Escalate, reason code, rationale, submit.
6. Switch to **Analyst B** (checker), open `H-RC08` in **To approve**, click **Approve**. Then show that Analyst A cannot approve their own decision.
   > Nothing is final until a different person approves. The server enforces that, not the screen.
7. **History** tab.
   > And every step lands in an audit log the database itself refuses to edit.

### 2:15 – 2:45 · Numbers and safety (≈70 words)

**Screen:** stay on History, or a one-slide numbers card if you have it.

> On the fifty practice labels: fifty out of fifty, zero unsafe clearances, identical output on every run, and no decision moves when we rewrite the data five different ways. When we blindfolded our note parser, the rules alone made five unsafe clearances; Grok caught all five. By design, the AI can send a clearance back to a person. It can never create one.

### 2:45 – 3:00 · Close (≈30 words)

> The machine recommends, a person decides, and a second person approves. Rules you can audit, AI that only makes it safer. That is Tryll. Thank you.

## If something breaks on stage

| Problem | What to do and say |
|---|---|
| AI court errors or hangs (no network, no key) | "The court is optional and advisory; Tryll decides on rules alone and produces identical output without any key." Move on to the decision card. |
| GUI will not start | Play the 2-minute video from the background tab and narrate over it. |
| Running long | Skip the blind-review beat (step 3), then the History beat (step 7). Never skip the four-eyes beat. |

## Likely judge questions

**How do you get the same answer every time, with an LLM in the loop?**
The scored decisions come from deterministic rules: sorted iteration, no clocks, no randomness. Two full runs are byte-identical, also from a different working directory. Grok runs at temperature 0 with a strict JSON schema, and in our measurement three fresh runs sent back exactly the same clearances. Without a key, output is byte-identical to rules-only.

**How do you stop the LLM from clearing a real match?**
It structurally cannot. The cross-examiner can only turn a clearance into a review. The dual path's arbiter enforces "a final clearance can only come from the rules" twice in code, and 26 safety tests across 968 LLM and screener combinations never produce a new clearance. `DUAL_MODE=rules` switches the AI off entirely in one line.

**Why rules first and not just an LLM?**
The costs are asymmetric: a wrong clearance costs 60, a needless review 2 to 3. Rules give a reason you can audit and an answer that does not drift. When we let Grok make every call, it misread the SOP's location exception and did worse than the rules, so the AI's job is to catch what the rules miss, never to overrule them towards a clearance.

**What is missing, or what would you do next?**
Be honest:
- Fifty practice labels is a small set, so 100% is probably somewhat tuned to them. We kept every ambiguous parse as "unknown" to limit that.
- The dual path is still being tuned to beat rules-only; until it does, the scored output stays on rules plus the cross-examiner (check the board for the latest status before going on stage).
- Sign-in is by name and role; in production it plugs into the bank's single sign-on at the same point.
- SQLite on one machine is right for a demo and keeps the data local; production would use the bank's database with the same append-only rule.
- Next: request-for-information workflows from "what would settle this", and QA sampling rates set by risk.

**How does it handle data it has not seen?**
It is tuned on the SOP's principles, not dev wording. We stress it by rewriting the data five ways (order, date formats, case and accents, list formats, country codes and demonyms) and nothing moves. 39 invented end-to-end cases cover rare SOP situations the practice labels never show: deceased, company vs person, two customers fitting one alert, rejected checks.

**Where does the data go?**
Nowhere. Everything runs on the laptop, the audit log is one local SQLite file, and the only outside call is the optional Grok request, which receives only the records the analyst ticks.

**How fast and how expensive?**
The full dev set of 819 hits runs in about 25 seconds on rules alone, and about 5 minutes with every Grok pass. Rules cost nothing; the Grok passes cost cents per run.

**How does this fit regulation?**
FCA AI good practice (log outputs and whether staff approved, overrode or escalated; hide the AI's proposal to avoid anchoring), FCA sanctions controls (QA, true matches wrongly discounted), OFAC record keeping, Wolfsberg and FATF explainability, and EU AMLR meaningful human intervention. Tryll covers each with the audit log, blind review, the QA sample, cited evidence and server-enforced four-eyes.

**How is this different from what vendors already show?**
Diligent's public demo recommends dispositions with an audit trail. Tryll adds a human decision with four-eyes and a QA sample, and no vendor we found shows prosecution and defence agents arguing a case, which Tryll keeps advisory.
