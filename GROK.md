# Instructions for Grok (and any agent that reads GROK.md)

**Read [AGENTS.md](AGENTS.md) in full before doing anything.** It is the single source of truth for this repo: team, board, workflow, ownership and the Track 2 hard rules. If anything here conflicts with AGENTS.md, AGENTS.md wins. CLAUDE.md and GEMINI.md just point at it, and so does this file.

Then read, before touching code: [docs/track2/BRIEF.md](docs/track2/BRIEF.md), [docs/track2/SPEC.md](docs/track2/SPEC.md), [docs/track2/DATA.md](docs/track2/DATA.md), [docs/track2/SCOPE.md](docs/track2/SCOPE.md).

## The essentials (summary of AGENTS.md, do not skip the original)

- **Project:** Track 2 ("Is my customer sanctioned?") of the Grok Bot London Financial Crime Hackathon, 21 Nov 2026, **code freeze 17:00**. Team lead: `@yousuf-shahzad`.
- **Board:** pinned issue #1 "Message Board". Use `tools/board`. Run `tools/board unread` at the start of every task, before each commit and after merges. Every post starts with `[<human>'s Grok]`, e.g. `[Thomas's Grok]`. Reply to posts that mention you or `@all`.
- **Workflow:** branch `<issue#>-<slug>` from fresh `main`, small commits, stage only your own files (never `git add -A`), PR with `Closes #N`, `git fetch` + rebase before pushing, never force-push shared branches. Ask on the board before editing a teammate's files.
- **Never commit or post data or keys.** `data/`, `dev/`, `*.xlsx`, `.env*` are gitignored; never `git add -f` them. Never paste dataset records anywhere public; cite IDs (`CUS-...`, `H-...`, `NOTE-...`, `KYC-...`). Never print or log `OPENROUTER_API_KEY` or `XAI_API_KEY`.
- **`system/` rules:** entry point `system/run <data folder> <output file>`; Python 3 or Node standard library only (no pip/npm packages); LLM only through `system/engine/llm.py`: OpenRouter if `OPENROUTER_API_KEY` is set (the organisers use this one), else the xAI Grok API via `XAI_API_KEY` (the lead confirmed the organisers allow it), else rules only. The model may only turn a clearance into `REVIEW` (the cross-examiner), never decide on its own; deterministic (temperature 0, sorted iteration, cache by input hash); under 30 minutes; nothing dev-specific hardcoded; `system/` never imports from `tools/`, `demo/` or `docs/`.
- **Decision safety:** the SOP wins. Wrongly clearing a hit costs 60, a needless review costs 2 to 3: clear only on a contradiction the SOP names, confirm only on agreement, otherwise `REVIEW`. A missing field is not a mismatch.
- **Never hand-edit `output/dev.jsonl`.** Keep `main` runnable at all times.

## Running commands on this machine (Windows)

- `tools/board` and `.claude/hooks/*.sh` are bash scripts. If your shell is PowerShell or cmd and `bash` is not on PATH, run them through Git Bash:
  `& "C:\Program Files\Git\bin\bash.exe" tools/board unread`
  (or start Grok from a Git Bash terminal, where `tools/board unread` works directly).
- Python is the `py` launcher with Python 3.12 (AGENTS.md mentions `py -3.14`; 3.12 works, the scripts are stdlib only):
  `py -3 -X utf8 tools/xlsx_to_jsonl.py data/ScreeningDevSet-browse.xlsx data/dev`
- If `tools/board` fails with `\r` / `bad interpreter`, see Troubleshooting in AGENTS.md section 5.
- Keys: copy `.env.example` to `.env` and put `XAI_API_KEY` (or `OPENROUTER_API_KEY`) there yourself (the human does this; never ask them to paste a key into chat). `LLM_DISABLE=1` runs rules only.
- Run and score: `bash system/run "$PWD/data/dev" "$PWD/output/dev.jsonl"` then `py -3 -X utf8 tools/score.py output/dev.jsonl data/dev/practice_labels.jsonl`. Before merging anything risky: `py -3 -X utf8 tools/stress.py data/dev`.
