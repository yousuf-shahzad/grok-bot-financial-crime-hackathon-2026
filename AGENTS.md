# Team rules for every agent

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
