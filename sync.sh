#!/usr/bin/env bash
#
# Run the local classification chores and get them onto main safely.
#
#   export GEMINI_API_KEY='...'
#   ./sync.sh              # backfill unrated rows, then merge + push
#   ./sync.sh --digest     # also rebuild the per-area digest
#   ./sync.sh --push-only  # skip classification, just merge + push
#
# The scheduled workflow commits to the same branch three times a day, so a plain
# `git push` after a local backfill loses the race roughly whenever you are
# unlucky. This merges by re-deriving through the store, which preserves both
# sides: the bot's newly collected rows AND your freshly rated ones.
set -euo pipefail

cd "$(dirname "$0")"
ok() { printf "  \033[32m✓\033[0m %s\n" "$*"; }
bold() { printf "\n\033[1m%s\033[0m\n" "$*"; }

PUSH_ONLY=0
DIGEST=0
for arg in "$@"; do
  case "$arg" in
    --push-only) PUSH_ONLY=1 ;;
    --digest) DIGEST=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [ "$PUSH_ONLY" -eq 0 ]; then
  [ -n "${GEMINI_API_KEY:-}" ] || { echo "GEMINI_API_KEY is not exported" >&2; exit 1; }
  bold "Classifying unrated rows"
  python3 reclassify.py
  if [ "$DIGEST" -eq 1 ]; then
    bold "Rebuilding the per-area digest"
    python3 build_digest.py --days 7
  fi
fi

bold "Merging with origin/main"
if git diff --quiet && git diff --cached --quiet && [ -z "$(git status --porcelain)" ]; then
  ok "no local changes"
else
  git add -A
  git commit -q -m "Update classification data"
  ok "committed $(git rev-parse --short HEAD)"
fi

for attempt in 1 2 3; do
  git fetch origin main --quiet
  if [ -z "$(git log --oneline HEAD..origin/main)" ]; then
    ok "up to date with origin"
  else
    # Save our data, take the remote's, then re-derive: merge_into_store adds the
    # rows the remote lacks AND enriches rows whose ratings only we have.
    cp data/articles.json /tmp/roofline-ours.json
    git merge origin/main --no-edit >/dev/null 2>&1 || true
    git checkout origin/main -- data/articles.json data/rejected.json 2>/dev/null || true
    rm -rf data/archive
    python3 merge_into_store.py /tmp/roofline-ours.json
    git add -A data/
    git commit -q --no-edit 2>/dev/null || git commit -q -m "Merge origin/main" 2>/dev/null || true
    ok "merged origin/main"
  fi

  if git push origin main 2>/dev/null; then
    ok "pushed $(git rev-parse --short HEAD)"
    python3 - <<'PY'
import json
d = json.load(open("data/articles.json"))
rated = sum(1 for a in d["articles"] if isinstance(a.get("importance"), (int, float)))
print(f"  {d['count']} rows, {rated} rated, {d['count'] - rated} unrated")
PY
    exit 0
  fi
  echo "  push raced, retrying ($attempt/3)"
done

echo "could not push after 3 attempts — run ./sync.sh --push-only once more" >&2
exit 1
