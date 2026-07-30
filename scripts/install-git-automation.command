#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
EXPECTED_REPOSITORY="harringtonwalker/xianyu-automation"
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
    print -u2 "Refusing to bind hooks: origin is not ${EXPECTED_REPOSITORY}."
    exit 1
    ;;
esac

for hook in pre-commit pre-push post-commit; do
  if [[ ! -x ".githooks/${hook}" ]]; then
    print -u2 "Missing executable hook: .githooks/${hook}"
    exit 1
  fi
  zsh -n ".githooks/${hook}"
done

git config --local core.hooksPath .githooks
git config --local push.autoSetupRemote true

print "GitHub binding installed for ${EXPECTED_REPOSITORY}."
print "Intentional commits on codex/* now verify, push, and create/update a draft PR."
print "Direct local pushes to main are blocked; PR merging remains manual."
