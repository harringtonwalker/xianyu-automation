#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
EXPECTED_REPOSITORY="harringtonwalker/xianyu-automation"
CHECK_ONLY=0

if [[ "${1:-}" == "--check-only" ]]; then
  CHECK_ONLY=1
elif (( $# > 0 )); then
  print -u2 "Usage: ./scripts/publish-pr.command [--check-only]"
  exit 2
fi

cd "$PROJECT_DIR"

if ! command -v gh >/dev/null 2>&1; then
  print -u2 "GitHub CLI (gh) is required."
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  print -u2 "GitHub CLI is not authenticated. Run: gh auth login"
  exit 1
fi

ORIGIN_URL="$(git remote get-url origin)"
case "$ORIGIN_URL" in
  "https://github.com/${EXPECTED_REPOSITORY}"|"https://github.com/${EXPECTED_REPOSITORY}.git"|"git@github.com:${EXPECTED_REPOSITORY}"|"git@github.com:${EXPECTED_REPOSITORY}.git")
    ;;
  *)
    print -u2 "Refusing to publish: origin is not ${EXPECTED_REPOSITORY}."
    exit 1
    ;;
esac

BRANCH="$(git branch --show-current)"
if [[ "$BRANCH" != codex/* ]] || [[ "$BRANCH" == *".."* ]] || [[ "$BRANCH" == *"//"* ]]; then
  print -u2 "Refusing to publish branch '${BRANCH}'. Use a codex/<slug> branch."
  exit 1
fi

if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  print -u2 "Refusing to publish: the worktree is not clean."
  print -u2 "Commit only the intended files or remove unrelated untracked files first."
  exit 1
fi

git fetch --quiet origin main
if ! git merge-base --is-ancestor origin/main HEAD; then
  print -u2 "Refusing to publish: this branch does not contain the latest origin/main."
  print -u2 "Rebase or recreate the branch, resolve it completely, then retry."
  exit 1
fi

./scripts/check-publication-boundary.command
./scripts/verify.command

if (( CHECK_ONLY )); then
  print "Automatic PR preflight: PASS for ${BRANCH}"
  exit 0
fi

git push --set-upstream origin "HEAD:refs/heads/${BRANCH}"

PR_URL="$(gh pr list \
  --repo "$EXPECTED_REPOSITORY" \
  --state open \
  --base main \
  --head "$BRANCH" \
  --json url \
  --jq '.[0].url // ""')"

if [[ -n "$PR_URL" ]]; then
  print "Draft PR updated: ${PR_URL}"
  exit 0
fi

COMMIT_SUBJECT="$(git log -1 --format=%s)"
SHORT_SHA="$(git rev-parse --short=12 HEAD)"
BODY_FILE="$(mktemp -t xianyu-auto-pr.XXXXXX)"
trap 'rm -f "$BODY_FILE"' EXIT

{
  printf '%s\n' \
    "## What changed" \
    "" \
    "Automatically synchronized the intentional Codex commit \`${SHORT_SHA}\` from \`${BRANCH}\`." \
    "" \
    "Commit: ${COMMIT_SUBJECT}" \
    "" \
    "## Safety and data boundary" \
    "" \
    "- The local publication-boundary check passed." \
    "- Runtime data, credentials, logs, backups, generated assets, and private product material are excluded." \
    "- This workflow never pushes \`main\`, enables auto-merge, or merges the PR." \
    "" \
    "## Verification" \
    "" \
    "- \`./scripts/verify.command\`" \
    "- GitHub CI and CodeQL must pass before human review and merge."
} > "$BODY_FILE"

PR_URL="$(gh pr create \
  --repo "$EXPECTED_REPOSITORY" \
  --base main \
  --head "$BRANCH" \
  --draft \
  --title "[codex] ${COMMIT_SUBJECT}" \
  --body-file "$BODY_FILE")"

print "Draft PR created: ${PR_URL}"
