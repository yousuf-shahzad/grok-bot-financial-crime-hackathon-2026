#!/usr/bin/env bash
# Build the public submission folder from what git tracks, and only these paths:
#   system/  output/dev.jsonl  demo/  tests/  tools/score.py  tools/stress.py  docs/track2/SPEC.md
# plus a top-level README.md and .gitignore written here.
# NEVER: data/, dev/, .env*, *.xlsx, practice labels, the board tooling (tools/board, .claude/,
# .github/), AGENTS.md / CLAUDE.md / GROK.md / GEMINI.md, or the rest of docs/.
#
# Usage: tools/make_submission.sh <dest folder> [data folder to test the copy on]
#   tools/make_submission.sh ../submission "$PWD/data/dev"
# The dest folder must not exist yet, or be empty, or hold a previous submission (its .git is kept,
# so you can commit and push from there).
set -euo pipefail

INCLUDE=(system output/dev.jsonl demo tests tools/score.py tools/stress.py docs/track2/SPEC.md)
# what may appear in the copy, as regexes on ./relative/path
ALLOWED='^\./(system/|output/dev\.jsonl$|demo/|tests/|tools/score\.py$|tools/stress\.py$|docs/track2/SPEC\.md$|README\.md$|\.gitignore$)'

die() { echo "make_submission: $*" >&2; exit 1; }
[ $# -ge 1 ] || die "usage: tools/make_submission.sh <dest folder> [data folder]"

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || die "run inside the team repo"
DEST="$1"
DATA="${2:-}"

[ -f "$ROOT/system/run" ] || die "no system/run in $ROOT"
[ -s "$ROOT/output/dev.jsonl" ] || die "no output/dev.jsonl: run system/run first"
[ -s "$ROOT/system/README.md" ] || die "no system/README.md"

# the submission must be what is committed (untracked caches do not count: we copy tracked files only)
if [ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no -- "${INCLUDE[@]}")" ]; then
  die "uncommitted changes under: ${INCLUDE[*]}; commit them (or stash) first"
fi

# compare in one path form (git can report C:/... while the shell says /c/...)
ROOT_ABS="$(cd "$ROOT" && pwd)"
mkdir -p "$(dirname "$DEST")"
DEST_ABS="$(cd "$(dirname "$DEST")" && pwd)/$(basename "$DEST")"
case "$DEST_ABS" in
  "$ROOT_ABS"|"$ROOT_ABS"/*) die "dest must be OUTSIDE the team repo (it is private)" ;;
esac

if [ -e "$DEST" ]; then
  [ -d "$DEST" ] || die "$DEST exists and is not a folder"
  others="$(find "$DEST" -mindepth 1 -maxdepth 1 ! -name .git | head -1)"
  # only ever clear a folder that is empty or already holds a previous submission
  if [ -n "$others" ] && [ ! -f "$DEST/system/run" ]; then
    die "$DEST is not empty and is not a previous submission; pick a new or empty folder"
  fi
  find "$DEST" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
else
  mkdir -p "$DEST"
fi

git -C "$ROOT" ls-files -z -- "${INCLUDE[@]}" | while IFS= read -r -d '' f; do
  mkdir -p "$DEST/$(dirname "$f")"
  cp "$ROOT/$f" "$DEST/$f"
done
chmod +x "$DEST/system/run"

cat > "$DEST/README.md" <<'EOF'
# Same Person or Not? (Track 2 submission)

Decides, for every watchlist hit, whether it is the bank's customer (`DIFFERENT_ENTITY`, `SAME_ENTITY`
or `REVIEW`), by implementing the bank's identity SOP as rules over the bank's own records, with the
record IDs behind every decision.

**Run:** `system/run <data folder> <output file>`. Python 3.8+ standard library only. With no API key
it runs on rules alone and makes no network calls; with `OPENROUTER_API_KEY` (or `XAI_API_KEY`) an
optional cross-examiner can send a clearance back to `REVIEW`, never the other way.

| Path | What |
|---|---|
| [system/](system/) | The system. [system/README.md](system/README.md): architecture, how we resolve both sides, evidence, determinism, model, time and cost, three worked cases |
| `output/dev.jsonl` | Our prediction for every dev hit, produced by `system/run` |
| [docs/track2/SPEC.md](docs/track2/SPEC.md) | Our summary of the SOP the rules implement |
| [tests/](tests/) | Unit and end-to-end tests. `tests/fixtures/rare/` is invented data covering rare SOP cases and reworded text. Run: `python -m unittest discover -s tests` |
| `tools/score.py` | Scores an output file against practice labels (cost matrix, unsafe clearances, evidence) |
| `tools/stress.py` | Rewrites a data folder in answer-preserving ways (formats, accents, order) and reports any decision that moves |
| [demo/](demo/) | Local analyst GUI: `python demo/app.py <data folder>`, then open http://127.0.0.1:8765 |

No dataset files are included: the data is for event participants only.
EOF

cat > "$DEST/.gitignore" <<'EOF'
__pycache__/
*.pyc
data/
dev/
.env*
*.xlsx
EOF

# ---- safety checks on what we are about to publish ----
files="$(cd "$DEST" && find . -path ./.git -prune -o -type f -print)"
bad="$(printf '%s\n' "$files" | grep -Ev "$ALLOWED" || true)"
[ -z "$bad" ] || die "unexpected files in submission: $bad"
# data-like files: any .xlsx/.csv/.env, a data/ or dev/ folder, dataset names, and any .jsonl/.json
# outside tests/fixtures/ and output/dev.jsonl
datalike="$(printf '%s\n' "$files" | grep -Ei '\.xlsx$|\.csv$|\.(db|sqlite3?)$|node_modules/|(^|/)\.reviews/|/\.env|(^|/)(data|dev)/|practice_labels|policy_sheet|start_here' || true)"
# .json/.jsonl only as invented fixtures, our output, or the GUI's build config
datalike="$datalike$(printf '%s\n' "$files" | grep -Ei '\.jsonl?$' | grep -Ev '^\./(tests/fixtures/|output/dev\.jsonl$|demo/ui/(package|package-lock|tsconfig)\.json$)' || true)"
[ -z "$datalike" ] || die "data-like files in submission: $datalike"
if grep -rIlE 'sk-or-v1-[A-Za-z0-9]{20,}|xai-[A-Za-z0-9]{20,}|(OPENROUTER|XAI)_API_KEY *[=:] *["'"'"']?[A-Za-z0-9_-]{16,}' "$DEST" --exclude-dir=.git >/dev/null 2>&1; then
  die "something that looks like an API key is in the submission"
fi
if grep -rlE '^(from|import) +(tools|demo|docs)\b' "$DEST/system" >/dev/null 2>&1; then
  die "system/ imports from tools/, demo/ or docs/"
fi

echo "make_submission: wrote $(printf '%s\n' "$files" | wc -l | tr -d ' ') files to $DEST"

# ---- optional: prove the copy works on its own ----
if [ -n "$DATA" ]; then
  TMP="$(mktemp -d)"
  (cd "$DEST/system" && LLM_DISABLE=1 ./run "$DATA" "$TMP/dev.jsonl") >/dev/null
  if cmp -s <(tr -d '\r' < "$TMP/dev.jsonl") <(tr -d '\r' < "$DEST/output/dev.jsonl"); then
    echo "make_submission: the copy runs from inside system/ and reproduces output/dev.jsonl exactly"
  else
    die "the copy's run does NOT match output/dev.jsonl: regenerate output/dev.jsonl and commit it"
  fi
  rm -rf "$TMP"
  PY=python3; $PY -c 'import sys' >/dev/null 2>&1 || PY=python; $PY -c 'import sys' >/dev/null 2>&1 || PY="py -3"
  # shellcheck disable=SC2086
  if (cd "$DEST" && LLM_DISABLE=1 $PY -X utf8 -m unittest discover -s tests -q) >"$DEST/../.make_submission_tests.log" 2>&1; then
    echo "make_submission: the copy's own test suite passes"
  else
    tail -20 "$DEST/../.make_submission_tests.log" >&2
    die "the copy's test suite FAILED (log above)"
  fi
  rm -f "$DEST/../.make_submission_tests.log"
  find "$DEST" -name __pycache__ -type d -prune -exec rm -rf {} +
fi
