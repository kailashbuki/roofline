#!/usr/bin/env bash
#
# One-shot bootstrap for roofline: verify, collect with a real key, then create
# the PUBLIC repo, push, wire the secret, and enable Pages.
#
#   export GEMINI_API_KEY='...'
#   ./publish.sh
#
# Safe to re-run: every step checks whether it has already been done. The only
# irreversible action (creating a public repo) is gated behind a confirmation.
#
# Why a NEW repo rather than flipping the old one public: force-pushing scrubbed
# history does not remove the old objects from GitHub. The original commits in
# kailashbuki/inference-news remain fetchable by SHA, including the config.yaml
# that held the Twitter keys. A fresh repo is the only deterministic fix.
set -euo pipefail

OWNER="kailashbuki"
REPO="roofline"
SLUG="$OWNER/$REPO"
SITE="https://$OWNER.github.io/$REPO/"

bold() { printf "\n\033[1m%s\033[0m\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
bad()  { printf "  \033[31m✗\033[0m %s\n" "$*"; }
die()  { bad "$*"; exit 1; }

cd "$(dirname "$0")"

# ---------------------------------------------------------------- 1. preflight
bold "1/7  Preflight"

[ -n "${GEMINI_API_KEY:-}" ] || die "GEMINI_API_KEY is not exported."
ok "GEMINI_API_KEY is set"

command -v gh >/dev/null || die "gh CLI not found."
gh auth status >/dev/null 2>&1 || die "gh is not authenticated — run: gh auth login"
ok "gh authenticated as $(gh api user --jq .login)"

git rev-parse --git-dir >/dev/null 2>&1 || die "not a git repository"
ok "git repository present"

# Secrets must not exist in the tree or anywhere in history before going public.
bold "2/7  Secret scan (tree + every blob in history)"
PATTERN='4iIsZ6[A-Za-z0-9]|p9R79[A-Za-z0-9]|18718533-[A-Za-z0-9]|qf83eo[A-Za-z0-9]|AKIA[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{30}'

if grep -rInIE "$PATTERN" \
     --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ . 2>/dev/null; then
  die "Secret-shaped string found in the working tree (above). Refusing to publish."
fi
ok "working tree clean"

HITS=$(git rev-list --objects --all | awk '{print $1}' \
  | git cat-file --batch-check='%(objectname) %(objecttype)' \
  | awk '$2=="blob"{print $1}' \
  | while read -r o; do git cat-file blob "$o" 2>/dev/null | grep -aoIE "$PATTERN" || true; done \
  | sort -u)
[ -z "$HITS" ] || die "Secret-shaped strings still in git history: $HITS"
ok "git history clean"

# ------------------------------------------------------- 3. confirm the API works
bold "3/7  Confirm the Gemini key works"
python3 verify_gemini.py | sed 's/^/  /' || die "verify_gemini.py failed"

# --------------------------------------------- 4. collect + reclassify with a key
bold "4/7  Collect with real classification"
python3 collect_all.py 2>&1 | sed 's/^/  /'

read -r -p "
Re-judge the back catalogue too? Rows stored during keyword-only runs kept
wrong tags (an MHD paper tagged 'inference'). Costs ~40 requests. [y/N] " RECLASS
if [[ "$RECLASS" =~ ^[Yy]$ ]]; then
  python3 reclassify.py 2>&1 | sed 's/^/  /'
fi

# ------------------------------------------------------------------ 5. commit
bold "5/7  Commit"
git add -A
if git diff --cached --quiet; then
  ok "nothing to commit"
else
  git commit -q -m "roofline: static site, aggregator sources, batched classifier, pulse dashboard"
  ok "committed $(git rev-parse --short HEAD)"
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
[ "$BRANCH" = "main" ] || { git branch -M main; ok "renamed branch to main"; }

# ------------------------------------------------- 6. create the repo and push
bold "6/7  Create the PUBLIC repo and push"

if gh repo view "$SLUG" >/dev/null 2>&1; then
  ok "$SLUG already exists"
  # Do NOT skip the push here: the repo existing does not mean the current
  # commits are on it. Skipping this is how the pulse dashboard and the HF
  # Papers collector sat unpushed while the site served older code.
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "git@github.com:$SLUG.git"
  git fetch origin --quiet
  if [ -n "$(git log --oneline origin/main..HEAD 2>/dev/null)" ]; then
    git pull --no-rebase --no-edit origin main || die "merge with origin/main failed — resolve and re-run"
    git push origin main && ok "pushed $(git rev-parse --short HEAD)"
  else
    ok "remote already has this commit"
  fi
else
  cat <<EOF

  About to create $SLUG as a PUBLIC repository and push $(git rev-list --count HEAD) commits.
  This is the irreversible step: the code and data/articles.json become world-readable.
  The secret scans above passed, so no credentials are in the history being pushed.

EOF
  read -r -p "  Create it? [y/N] " GO
  [[ "$GO" =~ ^[Yy]$ ]] || die "aborted — nothing was published"

  git remote remove origin 2>/dev/null || true
  gh repo create "$SLUG" --public --source=. --remote=origin --push \
    --description "A daily feed on the full AI performance stack: architecture, training, inference, silicon"
  ok "created and pushed"
fi

# Prove the fresh remote carries none of the old secret-bearing objects.
for sha in 5a06443 0387fb6 1279f6b e356682; do
  if gh api "repos/$SLUG/commits/$sha" >/dev/null 2>&1; then
    bad "old commit $sha is reachable on $SLUG — stop and investigate"
    exit 1
  fi
done
ok "none of the old secret-bearing commits exist on the new remote"

gh secret set GEMINI_API_KEY --repo "$SLUG" --body "$GEMINI_API_KEY"
ok "GEMINI_API_KEY set as a repository secret"

# ------------------------------------------------------------------- 7. Pages
bold "7/7  Enable Pages and run the workflow"

if gh api "repos/$SLUG/pages" >/dev/null 2>&1; then
  ok "Pages already configured"
else
  gh api -X POST "repos/$SLUG/pages" -f build_type=workflow >/dev/null
  ok "Pages source set to GitHub Actions"
fi

gh workflow run collect.yml --repo "$SLUG" >/dev/null 2>&1 || true
sleep 6
gh run list --repo "$SLUG" --limit 3

cat <<EOF

$(bold "Done")
  Site (live within a minute or two of the run finishing):
    $SITE
    ${SITE}pulse.html

  Watch the run:   gh run watch --repo $SLUG
  Check for leaks: gh api repos/$SLUG/contents/config.yaml --jq .content | base64 -d | grep -i token

  Remaining manual decision: the old repo $OWNER/inference-news still contains
  the secret-bearing objects. Delete it once this site is confirmed working:
    gh repo delete $OWNER/inference-news --yes
EOF
