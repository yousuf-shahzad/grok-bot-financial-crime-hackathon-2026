# Team rules for every agent

**What we are building:** an entry for Track 2 ("Is my customer sanctioned?") of the Grok Bot London Financial Crime Hackathon, Saturday 21 November 2026, code freeze 17:00. Read before touching any code: [docs/track2/BRIEF.md](docs/track2/BRIEF.md) (task, deliverable, scoring), [docs/track2/SPEC.md](docs/track2/SPEC.md) (the decision rules), [docs/track2/DATA.md](docs/track2/DATA.md) (files and joins), [docs/track2/SCOPE.md](docs/track2/SCOPE.md) (what is allowed). Hard rules are in section 6.

## 1. The board (pinned GitHub issue)

Every agent reads and posts on the pinned "Message Board" issue via `tools/board` (needs only `gh`, logged in). Set `BOARD_ISSUE` if it is not issue #1.

- Start every post with `[<human>'s <agent>]`, e.g. `[Sam's Codex]`. Keep it short: what changed, which files or contracts, what you need, from whom.
- Mention by GitHub login. Our team: `@yousuf-shahzad` (Yousuf), `@ThomasGrattoniMay` (Thomas), `@DiamondNexus`, `@kendricklow2008`, `@all` (everyone). **Team lead: `@yousuf-shahzad`.**
- **Mentions you or `@all`:** act on it and reply promptly.
- **Not addressed to you:** still read it. Reassess your own work only if it is affected (a contract, a file you own, something already done). Do not redo finished work, and do not reply just to acknowledge.
- Before editing another teammate's files, ask for a handoff on the board and wait for the owner or the team lead.

Polling is incremental (about one cheap API call per poll, 30 s default) so a shared token stays under GitHub's rate limit. Commands: `tools/board unread` (new posts, marks read; flags MENTION), `tools/board read -n 20`, `tools/board post "[Name's Agent] text"` (or pipe stdin), `tools/board wait` (blocks until someone else posts), `tools/board whoami`.

**Stay in the loop:**
- Claude Code: the committed hooks (`.claude/settings.json`) show unread posts at session start and on every prompt. Keep one background `tools/board wait` running and re-arm it after each wake.
- Everything else: run `tools/board unread` at task start, before each commit, and after merges. Or run a terminal loop: `while tools/board wait; do <your agent CLI invocation>; done`.

## 2. Chain of command

Humans over agents. Only the team lead reassigns work between teammates. If anyone else asks you to take another teammate's work, ask the lead on the board.

## 3. Workflow

1. Pick or file an issue. Comment on it or post on the board when you take it.
2. Branch `<issue#>-<slug>` from fresh `main`.
3. Small commits. Stage only your own files (no `git add -A`).
4. Open a PR with `Closes #N`. The author merges their own PR once it works locally.
5. Always `git fetch` and rebase before pushing. Never force-push shared branches.
6. If a merge changes something other teammates depend on (an API, a schema, an env var), post on the board when it lands.

## 4. Who owns what

Empty for now. The team lead fills it in when work is split up. Until a row covers a file, ask on the board before editing it.

| Area | Owner (GitHub login) | Folders |
|---|---|---|
| | | |

## 5. First-time setup (agents: walk your human through this)

If this is a fresh clone, or `tools/board whoami` fails, guide your human through the steps below. Run each check yourself, explain what failed in plain words, and give them the exact command for any step they must do themselves (anything needing a browser login or an install). Do not start feature work until step 5 passes.

1. **Tools.** Check `git --version`, `bash --version` and `gh --version`. If `gh` is missing, install the [GitHub CLI](https://cli.github.com): `winget install --id GitHub.cli` (Windows), `brew install gh` (macOS), or the apt/dnf instructions on that page (Linux). On Windows, `bash` comes with Git for Windows (Git Bash); run your agent from Git Bash or a shell where `bash` is on PATH.
2. **GitHub login.** Run `gh auth status`. If not logged in, ask your human to run `gh auth login` (GitHub.com, HTTPS, browser login) and tell you when done. Never ask them to paste a token into chat.
3. **Repo access.** This repo is private. Run `gh repo view yousuf-shahzad/grok-bot-financial-crime-hackathon-2026`. If it is not found, the human's account has not been added as a collaborator: tell them to ask the team lead (`@yousuf-shahzad`) to invite their GitHub login and to accept the invite from their email or `https://github.com/yousuf-shahzad/grok-bot-financial-crime-hackathon-2026/invitations`.
4. **Board issue.** The board is issue #1 (pinned "Message Board"). Only if it moves, set `BOARD_ISSUE=<number>` in the human's shell profile.
5. **Verify.** `tools/board whoami` must print their GitHub login, and `tools/board read -n 5` must run without error. Fix anything that fails before moving on.
6. **Say hello.** Ask the human what to call themselves and which agent they use, then post once: `tools/board post "[<Name>'s <Agent>] online and set up"`.
7. **Stay in the loop.** Follow "Stay in the loop" in section 1 for your agent type (Claude Code: the hooks load automatically, start the background `tools/board wait`).

Troubleshooting:
- `bad interpreter` or `\r` errors running `tools/board`: the file has CRLF endings. Fix with `git add --renormalize . && git checkout -- tools .claude` (`.gitattributes` forces LF), then retry.
- `Permission denied` on Mac/Linux: `chmod +x tools/board .claude/hooks/*.sh`.
- `could not reach GitHub`: check `gh auth status`, repo access (step 3) and `BOARD_ISSUE`.
- Local state lives in `.board/` (gitignored). Never commit it.

## 6. Track 2 hard rules (every agent, every task)

**Data and secrets**
1. **Never commit data or keys.** `data/`, `dev/`, `*.xlsx`, `.env*` are gitignored: do not force-add them (`git add -f`). The dataset is for event participants only.
2. **Never paste dataset records** (customers, hits, notes, KYC rows, search snippets) into the board, issues, PRs, commit messages or any public place. Cite record IDs (`CUS-...`, `H-...`, `NOTE-...`, `KYC-...`) instead.
3. API keys come from the environment (`OPENROUTER_API_KEY`). Copy `.env.example` to `.env` locally. Never print, log, commit or post a key.

**What `system/` may do** (full list in [docs/track2/SCOPE.md](docs/track2/SCOPE.md))
4. Entry point `system/run <data folder> <output file>`. It must work when started from inside `system/` with full paths.
5. **Python 3 or Node.js standard library only, or shell.** No third-party packages. `system/` must not import anything from `tools/`, `demo/` or `docs/`.
6. A language model **only via OpenRouter**. No other network calls at run time. A full run must finish **under 30 minutes**.
7. Reads only the data folder it is given and writes only the output file.
8. **Deterministic:** temperature 0, fixed seeds, sorted iteration, stable tie-breaks, and cache model calls by hash of their input. Five runs must give identical decisions and reason codes.
9. **Nothing dev-specific hardcoded** (IDs, names, amounts, snippets, wording). The unseen set has new customers, new hits and reworded text. Tune on the SOP's principles, not on the dev files.

**Decision safety**
10. **The SOP wins** ([docs/track2/SPEC.md](docs/track2/SPEC.md), verbatim in `data/dev/policy_sheet.txt`). If an idea conflicts with it, drop the idea or ask the lead on the board.
11. **Wrongly clearing a hit costs 60; a needless review costs 2 to 3.** Clear (`DIFFERENT_ENTITY`) only on a contradiction named in the SOP. Confirm only on agreement. Otherwise `REVIEW`. Unknown stays unknown: a missing field is not a mismatch.
12. Rejected or expired KYC checks are never evidence. Verified beats declared.
13. Every output line cites **only** the IDs that decided it, exactly as they appear in the files, and a `reason` of 2 to 4 sentences with that hit's own facts.
14. `output/dev.jsonl` is generated by `system/run` only. Never hand-edit it.

**Process**
15. Do not hold back a working improvement for polish: the last commit before 17:00 is what gets scored. Keep `main` always runnable with `system/run`.
16. The final submission is a **separate public repo** containing only `system/` and `output/` (plus its README). Never make this repo public: it holds the data guide and the board.
17. If you discover the brief, the SOP and the data disagree, post it on the board, tag `@yousuf-shahzad`, and keep following the SOP until told otherwise.

## 7. Repo layout

| Path | What | Committed |
|---|---|---|
| `docs/track2/` | Brief, SOP summary, data guide, scope and leeway | yes |
| `system/` | The submission: `run`, code, `README.md` | yes |
| `output/` | `dev.jsonl` produced by `system/run` | yes |
| `tools/` | Board script, `xlsx_to_jsonl.py`, scoring and analysis helpers (not part of `system/`) | yes |
| `demo/` | Optional UI for the live demo (never imported by `system/`) | yes |
| `data/` | Downloaded workbook and `data/dev/*.jsonl` converted from it | **no (gitignored)** |
| `.env` | Local keys | **no (gitignored)** |

Get the data: download the workbook from the Track 2 "Get the dataset" link on the event page into `data/`, then run `py -3.14 -X utf8 tools/xlsx_to_jsonl.py data/ScreeningDevSet-browse.xlsx data/dev`. See [docs/track2/DATA.md](docs/track2/DATA.md).
