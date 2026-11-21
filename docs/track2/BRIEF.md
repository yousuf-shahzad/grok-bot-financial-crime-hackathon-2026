# Track 2 brief: "Is my customer sanctioned?" (Same Person or Not?)

Our notes on Diligent's Track 2 brief. Sources: the event page (https://gb-fincrime-hackathon-11-2026.teamdeel.workers.dev/hackathon), Diligent's full brief (Google Doc `1L0dvhyJ4JOLhOu0g3uOXGM_7UgwgZaDrfbWS7RwPX5I`) and the dataset workbook's "Start here" and "Policy" tabs. If this file and the official brief disagree, the official brief wins: tell the team lead.

## The task in one paragraph

A bank screens its customers against sanctions, PEP, enforcement and adverse-media lists. A similar name raises an **alert**, and each listed profile that might be the customer is a **hit**. For every hit, decide whether the hit **is the customer**. This is identity only. How serious the listing is, or whether the bank would accept the customer anyway, is out of scope.

Both sides are messy. The customer's real details are spread over five internal systems with no shared key. The hit's best fact (a date of birth) may be buried in free text or only in web search results, most of which are about namesakes.

## Decisions

| Decision | Meaning |
|---|---|
| `DIFFERENT_ENTITY` | Evidence shows the hit is a different person or company. Cleared. |
| `SAME_ENTITY` | Evidence shows the hit is the customer. Goes to compliance. |
| `REVIEW` | Evidence is insufficient or contradictory. A human decides. |

An alert is cleared only if every hit in it is `DIFFERENT_ENTITY`. Scoring is per hit.

## Deliverable (what we submit)

1. **A runnable system**: an executable called as `system/run <data folder> <output file>`.
   - Reads only that folder and writes one JSON line per hit.
   - Python 3 or Node.js **standard library only**, or shell.
   - May call a language model **only through the OpenRouter API**, key in `OPENROUTER_API_KEY` (use our own while building; they set theirs when testing).
   - A run must finish in **under 30 minutes**.
2. **Predictions on the dev set** in `output/dev.jsonl`, produced by that system.
3. **A short `system/README.md`**: architecture (a diagram helps), how we find the customer and the listed person, how evidence is represented, how we keep results the same run to run, which model and prompts (if any), time and cost of a run, plus three worked cases: a clear mismatch, a match, and one left for review.
4. **Submission**: put `system/` and `output/` in a **public GitHub repo** and submit its link with a project name where the event collects submissions (the portal at `/submit` on the event site). **Do not commit the `dev/` data or any API key.** They score the **last commit before the deadline**. Code freeze is **17:00, Saturday 21 November 2026**. Teams also submit a **video demo** at code freeze.

`validate.py` (in the data room, not in our workbook) checks an output file the way the organisers do, and `--score dev/practice_labels.jsonl` scores the 50 practice hits.

### Output line, one per hit

```json
{"hit_id": "H-...", "alert_id": "A-...", "decision": "DIFFERENT_ENTITY",
 "reason_code": "DOB_MISMATCH", "customer_record_id": "CUS-123456",
 "reason": "Two to four sentences naming the decisive facts.",
 "evidence": ["CUS-123456", "KYC-0001AB", "H-..."]}
```

| Field | Content |
|---|---|
| `hit_id`, `alert_id` | From `hits.jsonl` |
| `decision` | `DIFFERENT_ENTITY`, `SAME_ENTITY` or `REVIEW` |
| `reason_code` | One code from the table in [SPEC.md](SPEC.md), and it must belong to the decision |
| `customer_record_id` | The resolved customer record ID, `"AMBIGUOUS"` if more than one person fits, or `null` if none was found |
| `reason` | Two to four sentences with this hit's own facts |
| `evidence` | IDs of the records that **decided** it, exactly as in the files. Not everything we looked at |

## How we are scored (out of 100)

The organisers run our system **five times** on an **unseen set of about 550 hits** from the same bank: new customers, new hits, differently worded free text. Some situations the policy covers are rare in the dev set. They also run it once on the dev set to check our dev predictions came from the system.

| Part | Weight | What counts |
|---|---|---|
| Unseen set | 80% | Decisions 75%, reasons 25% |
| Dev set | 10% | Decisions 75%, reasons 25% |
| Reproducibility | 10% | Same decision **and** reason code in all five runs, scaled by our unseen score |

### Decision cost (lower is better)

| Right answer \ We said | `DIFFERENT_ENTITY` | `SAME_ENTITY` | `REVIEW` |
|---|---|---|---|
| `DIFFERENT_ENTITY` | 0 | 3 | 3 |
| `SAME_ENTITY` | **60** | 0 | 2 |
| `REVIEW` | **60** | 2 | 0 |

The decision score is the share of cost saved against sending everything to `REVIEW`. Sending everything to `REVIEW` scores 0. Clearing everything also scores 0 (negative counts as 0). Some hits are not scored because their answer depends on information not in the files: answer them anyway.

**Consequence:** wrongly clearing a hit costs 60. Wrongly confirming or reviewing costs 2 to 3. Only clear a hit when a rule in [SPEC.md](SPEC.md) gives a contradiction. Break-even is roughly: clear only if we are more than about 95% sure.

### Reasons

For every correct decision they check: the reason code fits; `evidence` cites the records that decided it; `customer_record_id` is right; the reason states the real grounds with this hit's own facts (not generic wording).

Reported as well: unsafe clearances, share of false positives cleared, clearance precision, same-entity recall, review rate.

### Judges (finalists)

Judges read the README and talk to us about: how we resolve people on both sides, how we represent evidence, how we keep it deterministic, and whether our explanations are honest about what is missing.

## The four rules that apply throughout

1. **Unknown stays unknown.** A missing field is not a mismatch, and neither is the missing part of a partial date (a birth year alone can still agree with a full date). Do not fill it in.
2. **Verified beats declared.** A passed identity check beats what the customer typed. A rejected check is not evidence.
3. **Build for the principles, not for these files.** The unseen set has new customers, new hits and rephrased free text. Memorising dev wording loses points.
4. **Handle the data with care.** It is invented or pseudonymised, and the watchlist profiles come from a screening provider. Share it only through the event's participant access.

## Event facts

- Saturday 21 November 2026, Radisson Blu Hotel London Bloomsbury (Folio Suite). Building starts 11:00, office hours from 15:00 (YC founding teams), **code freeze 17:00**, live demos of the top 5 at 17:30 (3 minutes each), awards 17:50.
- Teams of up to 5. Event-wide judging criteria on the site: **Execution** (a working prototype, does it solve the problem), **Creativity**, **UX**.
- Prizes: Cursor Ultra for the top three teams (3, 2 and 1 months per member).
- Credits: Grok credits from the Discord credits bot after the 10:30 kick-off (checked in on Luma). Supabase codes and more partner credits "coming soon".
- Partner tools listed: Diligent, Grok Bot, Cursor, Supabase, Tavily. (Our `system/` may not call any of them at run time except OpenRouter: see [SCOPE.md](SCOPE.md).)

## Discrepancies to check with the organisers

- The event page card says 379 dev alerts, 766 hits and 71,865 customers. The full brief and the workbook say about 440 alerts, 819 hits and 72,265 customers (the workbook matches the brief). We treat the workbook as correct.
- The brief's submission line still says "By [deadline]". We assume 17:00 code freeze.
