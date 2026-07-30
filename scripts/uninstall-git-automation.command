#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
cd "$PROJECT_DIR"

CURRENT_HOOKS_PATH="$(git config --local --get core.hooksPath || true)"
if [[ "$CURRENT_HOOKS_PATH" == ".githooks" ]]; then
  git config --local --unset core.hooksPath
fi
if [[ "$(git config --local --get push.autoSetupRemote || true)" == "true" ]]; then
  git config --local --unset push.autoSetupRemote
fi

print "Local automatic PR binding removed. No branch, commit, or remote PR was deleted."
