#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
cd "$PROJECT_DIR"

if (( $# != 1 )); then
  print -u2 "Usage: ./scripts/start-codex-change.command <short-slug>"
  exit 2
fi

SLUG="$1"
if [[ ! "$SLUG" =~ '^[a-z0-9][a-z0-9._-]*$' ]] || [[ "$SLUG" == *".."* ]]; then
  print -u2 "Slug must use lowercase letters, digits, dots, underscores, or hyphens."
  exit 2
fi
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  print -u2 "Refusing to start: the worktree is not clean."
  exit 1
fi

./scripts/install-git-automation.command
git fetch --quiet origin main

BRANCH="codex/${SLUG}"
if git show-ref --verify --quiet "refs/heads/${BRANCH}" || \
   git show-ref --verify --quiet "refs/remotes/origin/${BRANCH}"; then
  print -u2 "Branch already exists: ${BRANCH}"
  exit 1
fi

git switch --create "$BRANCH" --no-track origin/main
print "Ready on ${BRANCH}."
print "Stage only the intended files and commit normally; the draft PR is automatic."
