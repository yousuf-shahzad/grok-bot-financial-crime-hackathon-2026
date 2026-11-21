# Tryll: the complete overview (for the presentation and the video)

Everything the presenter needs in one place. Numbers here are from our own runs on the dev set and the 50 practice labels. **Never show raw dataset records on screen or in narration**: film the GUI on the invented fixtures in `tests/fixtures/rare/`, and quote only our own output and the numbers below.

Owner of this file: Yousuf's Claude (lead agent). Ask on the board if a number looks stale.

## 1. One-line pitch

**Tryll decides whether a sanctions-screening hit is really your customer, clears only when the bank's own rules prove it is someone else, and puts a human in charge of every final call.**

Track 2 of the Grok Bot London Financial Crime Hackathon: "Is my customer sanctioned?" (Diligent designed the track; its founders are judges).

## 2. The problem (15 seconds in the video)

- Banks screen every customer against sanctions, PEP, enforcement and adverse-media lists. Similar names raise alerts; most are namesakes.
- Each hit must be decided by an analyst: same person or not. It is slow, repetitive and risky: clearing a real match means a sanctioned person stays a customer.
- Both sides are messy: the customer is spread over five bank systems with no shared key; the watchlist person's date of birth may only be in free text or in web search results about namesakes.
- Scoring reflects reality: **a wrong clearance costs 60, a needless review costs 2 to 3.**

## 3. What Tryll does

1. **Resolves the customer** across the system of record, accounts, onboarding, KYC checks and support notes: follows account, login and email links, searches when there is no link (a third of alerts), merges records by phone plus full date of birth or a shared document number, and trusts only the latest approved identity check.
2. **Resolves the listed person**: dates of birth from fields, ages in profile notes ("45 in March 2019" = born 1973 or 1974), and only search results that describe the same kind of listing in a country tied to the hit.
3. **Applies the bank's SOP as code**: clear only on a named contradiction (date of birth, location, verified name, entity type, too young at the report date, died before screening), confirm only on agreement, otherwise send to a person. Every decision cites the exact record IDs it rests on.
4. **Grok cross-examiner**: re-reads the free text behind every clearance and can only send it back to review, never clear anything.
5. **Grok judge + screening agent (dual path)**: Grok makes its own call on every hit; where it disagrees with the rules, a screening agent checks whether either side missed something significant; if neither has an obvious error the hit goes to review. **Hard rule: the LLM can never create a clearance.** A one-line switch (`DUAL_MODE=enforce|advisory|rules`) falls back to rules-only if needed.
6. **Human in the loop (the GUI)**: the system recommends; an analyst decides with a reason code, cited records and a rationale; a different person approves (four-eyes); everything lands in an audit log the database itself refuses to edit.

## 4. Headline numbers

| Measure | Result |
|---|---|
| Practice labels (50), rules + cross-examiner | **100% decision score, 50/50 right, 0 unsafe clearances** |
| Reason code and customer record on correct decisions | 50/50 and 50/50 |
| Evidence cited vs reference | 99% precision, 96% recall |
| Run time, full dev set (819 hits) | about 25 s rules-only; about 5 min with every Grok pass |
| Reproducibility | two full runs byte-identical (also from another working directory) |
| Robustness: 5 rewrites of the data (record order, date formats, name case and accents, JSON lists, country codes and demonyms) | **0 of 819 decisions moved** |
| Blindfold test (note parser switched off) | rules alone: 5 unsafe clearances, score 0 → with Grok cross-examiner: **0 unsafe, 88%** |
| KYC verification notes read | 99.8% (22,523 of 22,575) |
| Automated tests | about 330, incl. 39 invented end-to-end edge cases and 26 dual-path safety tests (968 LLM/screener combinations, no new clearance in any) |
| Dev recommendations (rules) | 447 clear, 123 match, 249 to a person |

Dual-path status (being improved now by Thomas's Claude): first run agreed with the rules on 47% of hits and lowered the practice score, because Grok misread the SOP's location exception; prompts are being fixed. The scored default flips to enforce only when it is at least as good as rules-only. Check the board for the latest number before recording.

## 5. Safety story (the part judges remember)

- **Asymmetric costs drive the design.** A wrong clearance is 60x worse than a needless review, so Tryll clears only on a contradiction the SOP names, and every AI component can only make it more cautious.
- **Unknown stays unknown.** A missing field is never a mismatch.
- **Verified beats declared.** Rejected or expired identity checks are never evidence.
- **The LLM never clears a hit**, enforced twice in code and by 26 tests across 968 combinations.
- **No key, no problem.** Without an LLM key the system runs on rules alone and produces byte-identical output.
- **Deterministic and reproducible.** Temperature 0, sorted iteration, no clocks.

## 6. The GUI (what to film)

Run: `py -3 -X utf8 demo/app.py tests/fixtures/rare` (invented data) and open http://127.0.0.1:8765. Built with **BoardUI** (React 19, Tailwind v4, React Aria).

- **Sign in** with a name and role (analyst, checker, QA). Every action is logged under that name.
- **Overview**: four stat cards (to decide, to approve, QA sample, closed) and "Start reviewing".
- **Work queues** in the sidebar: To decide, To approve, QA sample (1 in 10 engine clearances), Escalated, Closed, All.
- **Case page** (opens full width, inbox style):
  - Verdict strip: rules engine → Grok judge → screening agent → recommendation.
  - Tabs: **Summary** (plain-English "why" and a customer-vs-hit table: Same / Different / Unknown per field, each value with its source record), **Evidence** (tick which records the AI may read), **AI court**, **History** (append-only audit trail).
  - **What would settle this**: the missing facts, as a request for information.
- **AI court (on request only)**: prosecution argues it is the customer, defence argues it is not, an adjudicator summarises against the SOP and suggests a disposition. Advisory, labelled AI-written; only the records the analyst ticked are sent.
- **Decision card**: Clear / Match / Escalate, a reason code from the SOP, the records relied on, a rationale; a checker sees Approve / Return; the server refuses self-approval.
- **Blind review** switch: hides the machine's recommendation until the analyst chooses (FCA good practice against anchoring).
- **Case report** (one-page Markdown per alert) and **decisions export**.
- Demo mode `--blindfold`: switches the note parser off so you can show Grok catching clearances that would go wrong.

## 7. Why Tryll stands apart (research, with sources in the team brief)

- **Diligent's own public pitch** shows an agent recommending dispositions with an audit trail, but no human-in-the-loop or QA step. Tryll adds both.
- **FCA, AI good practice (19 Oct 2026)**: log prompts, outputs and whether staff approved, overrode or escalated each AI output; keep people in control; hide the AI's proposal to avoid anchoring. Tryll does all of these.
- **FCA, sanctions systems and controls (28 May 2026)**: poor practice included weak QA and true matches wrongly discounted. Tryll's QA sample and asymmetric safety rules answer exactly that.
- **OFAC**: 10-year record keeping. Tryll's audit log is append-only.
- **Wolfsberg / FATF**: explainability, transparency, human oversight. Every Tryll decision cites its records and names the SOP rule.
- **EU AMLR Art. 76**: meaningful human intervention for key decisions. Four-eyes, server-enforced.
- **No vendor publicly shows prosecution and defence agents** arguing a case. Tryll does, and keeps them advisory.
- **Database and auth**: SQLite (one file on the laptop; participants-only data never leaves it). Reviewer sign-in plus server-enforced four-eyes; single sign-on plugs in at the same point in production.

## 8. Pitch lines

1. "The machine recommends, a person decides, and a second person approves. The log cannot be edited."
2. "We clear only when the bank's own SOP names a contradiction, and every decision cites the records behind it."
3. "Grok cross-examines every clearance and can only send it back to a human. Blindfold our parser and it still catches the misses."
4. "Blind review hides our recommendation until the analyst commits: the FCA's own good practice against anchoring."
5. "100% on the practice labels, zero unsafe clearances, identical results on every run."

## 9. Architecture in one picture

```
alert + hit ──► resolve.py (customer: 5 systems, merge, verified facts)
             └► hitfacts.py + notes.py (listed person: DOB, ages, countries, reports)
                      │
                      ▼
               judge.py (SOP as code) ──► explain.py (2-4 sentence reason + cited IDs)
                      │
                      ▼
               crossexam.py (Grok re-reads clearances; can only downgrade)
                      │
                      ▼
               llm_judge.py + arbiter.py (Grok's own call + screening agent; never clears)
                      │
                      ▼
               output/dev.jsonl ──► demo/app.py + review_api.py (SQLite audit, four-eyes)
                                   └► demo/ui (BoardUI GUI) + court_llm.py (AI court)
```

Standard library only in `system/`; LLM via the xAI Grok API or OpenRouter; `system/run <data folder> <output file>`.

## 10. Team

| Person | Agent(s) | Built |
|---|---|---|
| Yousuf (lead) | Claude (lead agent), Grok | customer resolver, loader, cross-examiner, stress harness, review API, GUI, plan and docs |
| Thomas | Claude | shared model, SOP judge, reasons and evidence, entry point, scorer, LLM court, dual decision path, submission script, README |
| Kendrick | Claude, grokhack | name, date and country matchers; rare-case and reworded-text fixtures; API and dual-path tests; video script |
| Averneesh | Grok | hit facts and customer-note extraction (99.8% of KYC notes read), arbiter audit |

## 11. Video do's and don'ts

- Film only `tests/fixtures/rare` (invented). Never `data/dev`.
- Show a review end to end: open a case, read the verdict strip, run the AI court, decide with a reason, switch reviewer, approve.
- Mention the safety rule (the LLM never clears) and the blindfold numbers.
- Two minutes; any public link (unlisted YouTube, Loom, Drive) is accepted.
