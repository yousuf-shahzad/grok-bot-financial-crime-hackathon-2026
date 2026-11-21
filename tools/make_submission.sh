#!/usr/bin/env bash
# Build the public submission folder: ONLY system/ and output/ plus a short top-level README.
# Never copies data/, dev/, .env*, *.xlsx, tools/, docs/, tests/ or the board.
#
# Usage: tools/make_submission.sh <dest folder> [data folder to test the copy on]
#   tools/make_submission.sh ../submission "$PWD/data/dev"
# The dest folder must not exist yet, or must be an empty folder / an existing git repo whose
# tracked files we replace (its .git is kept, so you can commit and push from there).
set -euo pipefail

die() { echo "make_submission: $*" >&2; exit 1; }
[ $# -ge 1 ] || die "usage: tools/make_submission.sh <dest folder> [data folder]"

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || die "run inside the team repo"
DEST="$1"
DATA="${2:-}"

[ -f "$ROOT/system/run" ] || die "no system/run in $ROOT"
[ -s "$ROOT/output/dev.jsonl" ] || die "no output/dev.jsonl: run system/run first"
[ -s "$ROOT/system/README.md" ] || die "no system/README.md"

# refuse to build from a dirty system/ or output/: the submission must be what is committed
if [ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no -- system output)" ]; then
  die "system/ or output/ has uncommitted changes; commit them (or stash) first"
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
  # keep an existing .git; replace everything else
  find "$DEST" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
else
  mkdir -p "$DEST"
fi

# copy exactly what git tracks under system/ and output/ (no untracked caches or local files)
git -C "$ROOT" ls-files -z -- system output | while IFS= read -r -d '' f; do
  mkdir -p "$DEST/$(dirname "$f")"
  cp "$ROOT/$f" "$DEST/$f"
done
chmod +x "$DEST/system/run"

cat > "$DEST/README.md" <<'EOF'
# Same Person or Not? (Track 2 submission)

Run: `system/run <data folder> <output file>` (Python 3.8+ standard library, no network, no API key needed).

- `system/` is the system; its README explains the architecture, how we resolve both sides,
  the evidence, determinism, time and cost, and three worked cases: [system/README.md](system/README.md).
- `output/dev.jsonl` is our prediction for every dev hit, produced by `system/run`.
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
bad="$(cd "$DEST" && find . -path ./.git -prune -o -type f -print | grep -Ev '^\./(system/|output/dev\.jsonl$|README\.md$|\.gitignore$)' || true)"
[ -z "$bad" ] || die "unexpected files in submission: $bad"
if (cd "$DEST" && find . -path ./.git -prune -o \( -name '*.xlsx' -o -name '.env*' -o -name 'customers.jsonl' -o -name 'kyc_checks.jsonl' -o -name 'notes.jsonl' \) -print | grep -q .); then
  die "data or env file found in submission"
fi
if grep -rIlE 'sk-or-v1-[A-Za-z0-9]{20,}|xai-[A-Za-z0-9]{20,}|(OPENROUTER|XAI)_API_KEY *= *[^ $]' "$DEST/system" "$DEST/README.md" >/dev/null 2>&1; then
  die "something that looks like an API key is in the submission"
fi
if grep -rlE '^(from|import) +(tools|demo|docs)\b' "$DEST/system" >/dev/null 2>&1; then
  die "system/ imports from tools/, demo/ or docs/"
fi

echo "make_submission: wrote $(cd "$DEST" && find . -path ./.git -prune -o -type f -print | wc -l | tr -d ' ') files to $DEST"

# ---- optional: prove the copy runs on its own and reproduces output/dev.jsonl ----
if [ -n "$DATA" ]; then
  TMP="$(mktemp -d)"
  (cd "$DEST/system" && ./run "$DATA" "$TMP/dev.jsonl") >/dev/null
  if cmp -s <(tr -d '\r' < "$TMP/dev.jsonl") <(tr -d '\r' < "$DEST/output/dev.jsonl"); then
    echo "make_submission: the copy runs from inside system/ and reproduces output/dev.jsonl exactly"
  else
    die "the copy's run does NOT match output/dev.jsonl: regenerate output/dev.jsonl and commit it"
  fi
  rm -rf "$TMP"
fi
