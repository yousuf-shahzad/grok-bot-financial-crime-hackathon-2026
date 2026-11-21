# How much leeway do we have? (scope and limits)

Short answer: **a lot of freedom in how we decide and in what we show, almost none in what `system/` may depend on or do at run time.** The score (80% unseen, 10% dev, 10% reproducibility) only sees `system/run`'s output, so everything else is free but earns nothing from the Diligent score. It can still help with the event judges (Execution, Creativity, UX) and the live demo.

## Hard limits (breaking one can zero or disqualify the submission)

| Limit | Source |
|---|---|
| Entry point `system/run <data folder> <output file>`. Must work when run from inside `system/` with **full paths**, from any working directory | Brief, deliverable 1 |
| **Python 3 or Node.js standard library only, or shell.** No `pip install`, no `npm install`, no vendored third-party code | Brief |
| A language model only through **OpenRouter** (`OPENROUTER_API_KEY`, set by the organisers when testing) **or the xAI Grok API** (`XAI_API_KEY`; the lead confirmed with the organisers on the day that the Grok API is allowed). No other model or web APIs (OpenAI, Anthropic, Tavily ...) in `system/` | Brief, plus organisers' confirmation |
| Reads **only** the data folder it is given and writes **only** the output file. No network calls other than the LLM provider (our reading of the brief: it names OpenRouter as the only allowed external call) | Brief |
| Run time **under 30 minutes** for the unseen set (about 550 hits) | Brief |
| Output: one line per hit with `hit_id, alert_id, decision, reason_code, customer_record_id, reason, evidence`; reason code must belong to the decision | Brief and [SPEC.md](SPEC.md) |
| **Deterministic**: same decision and reason code in all five runs | Scoring (10%) |
| **Nothing from the dev data hardcoded**: no IDs, names, amounts or wording specific to dev records. Unseen data has new customers, new hits and reworded free text | Brief rule 3 |
| **Do not commit `dev/` data or any API key.** Data is for participants only | Brief |
| Submission is a **public repo** with `system/` and `output/`, last commit before the deadline (code freeze 17:00) | Brief |
| `system/README.md` with architecture, resolution approach, evidence representation, determinism, models and prompts, time and cost, three worked cases | Brief |

## Decisions that are free (our call)

- **Architecture**: pure rules, LLM-only, or a hybrid. The brief says "how your system gets there is up to you." (Recommended: deterministic first, LLM only for what rules cannot read: see below.)
- **Which model** (Grok via xAI or OpenRouter), prompts, retries, batching, caching, parallelism, as long as the 30-minute and determinism limits hold. A model can be used to read free text (profile notes, search snippets, customer notes) into structured facts.
- **How we resolve people** (indexes, blocking, scoring), as long as it follows the SOP's linking rules.
- **Internal design**: modules, data structures, intermediate evidence graph, caches.
- **Everything outside `system/`**: demo UI, evidence graph viewer, analyst-queue mock-up, slides, video, scoring and error-analysis tools. These do not count towards the Diligent score but do help the live demo and the event judges. Keep them in separate folders (for example `demo/`, `tools/`) and make sure `system/run` never depends on them.
- **Using any tools while building** (Grok, Cursor, Claude, Tavily, Supabase, and so on) to write code and analyse the dev set. Only the **run-time** behaviour of `system/` is restricted.

## Grey areas (do not rely on these without asking)

| Question | Why it is unclear | Safe default |
|---|---|---|
| A precomputed lookup or cache file shipped in `system/` (for example an LLM-response cache keyed by input hash) | Brief says it "reads only that folder" but a cache of model calls on **unseen** data cannot exist; a cache of **dev** answers reads like memorisation | Cache at run time into a temp or output-adjacent file only, key by input hash, never ship dev answers |
| Fixed tables in code (name variants, country code and nationality maps, month names) | Seems fine because they are knowledge, not dev data, but `name_variants.json` is supplied | Read `name_variants.json` from the data folder if present, otherwise use a built-in copy |
| Tuning thresholds on the 50 practice labels and dev set | Allowed in spirit (that is what they are for) but overfitting to 50 rows is a risk | Prefer SOP-derived rules over fitted thresholds; keep a held-out slice |
| Using the web search results file vs live search (Tavily) at run time | The brief gives `search_results.jsonl` and says only the data folder is read | Use only `search_results.jsonl` |
| Event-level judging vs the Track 2 score: how they combine | The site lists Execution, Creativity and UX; the brief gives a 100-point score | Optimise the 100-point score first, then add a demo |
| Whether clever extras (cross-alert linking, entity graphs, confidence calibration) are rewarded | Not scored, but judges "talk to finalists about architecture" | Allowed if they stay deterministic and inside the SOP |

## Where we must NOT go

- **Overriding the SOP.** Examples: clearing a hit on a weaker signal than the SOP allows, using a different name-edit rule, treating a missing field as a mismatch, using a rejected or expired KYC check as evidence. The SOP defines correct, and the unseen set is scored against it.
- **Deciding policy or risk** (seriousness of the listing, whether the customer is acceptable). Track 2 is identity only.
- **Clearing to look good.** A wrong clearance costs 60, a needless review 3. Never trade safety for a better headline number.
- **Memorising or fitting to dev records** (case IDs, names, exact snippets), or any behaviour that depends on running only the dev set.
- **Sharing the data or keys** outside the team (board, issues, PRs, public repo, screenshots, demo videos that show raw records).
- **Running longer than 30 minutes** or calling anything but the LLM provider (OpenRouter or xAI) at run time.

## Questions for the organisers (ask at kick-off 10:30 or in Discord)

1. Where is the official `dev/` data room (JSON Lines, `POLICY.md`, `name_variants.json`, `validate.py`)? We only have the browse workbook.
2. Counts differ between the event page (379 alerts, 766 hits) and the brief and workbook (440, 819). Which is final?
3. Is a shipped cache or a built-in lookup table inside `system/` acceptable?
4. How do the Track 2 100-point score and the event-wide judging (Execution, Creativity, UX, video demo) combine into the Top 5?
5. Is switching tracks, or a submission to both, allowed?
6. Which OpenRouter models will the organisers' key allow, and is there a spend cap?

## Suggested stance: where to spend ambition

Safe room for creativity: **how we resolve people** (this is where most score is lost), **the evidence representation** (graph of IDs with a decision trace that explains each verdict), **a calibrated "review" policy** (a principled way to decide the borderline hits), and **a demo** that shows an analyst queue with each hit's decision and the exact records behind it. Do not spend ambition on bigger models or extra data sources: the limits above remove most of the upside.

## Decided on the day (lead)

- **LLM use is one narrow cross-examiner** (`system/engine/crossexam.py`): it re-reads free text behind a clearance and can only turn that clearance into REVIEW. Provider order: `OPENROUTER_API_KEY` (the organisers' key when testing), then `XAI_API_KEY`, then none (rules only). Temperature 0, strict JSON schema, all comparisons done by our code.
- **No database** (Supabase, Neon): the data is local files, `system/` is stdlib-only, and participants-only data must not go to a cloud service.
- **No Tavily** in `system/` or the GUI: the brief supplies `search_results.jsonl`, live search breaks determinism, and dataset names must not be sent to outside services.
