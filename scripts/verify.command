#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
cd "$PROJECT_DIR"

if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

EVIDENCE_DIR="${PROJECT_DIR:h}/evidence"
if [[ -d "$EVIDENCE_DIR" ]]; then
  cmp -s "$EVIDENCE_DIR/live-contract.json" "$PROJECT_DIR/docs/live-contract.json"
  cmp -s "$EVIDENCE_DIR/verification-report.md" "$PROJECT_DIR/docs/verification-report.md"
fi

export PYTHONPATH="$PROJECT_DIR"
"$PYTHON_BIN" -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/extension-core.test.js
node --test tests/content-runtime.test.js
"$PYTHON_BIN" -m compileall -q xianyu_ops
node --check extension/core.js
node --check extension/content-runtime.js
node --check extension/content.js
node --check extension/service-worker.js
node --check extension/options.js
node --check extension/popup.js
node --check static/app.js
zsh -n scripts/start.command
zsh -n scripts/service-entry.command
zsh -n scripts/backup.command
zsh -n scripts/restore.command
zsh -n scripts/setup.command
zsh -n scripts/install-login-service.command
zsh -n scripts/uninstall-login-service.command
plutil -lint scripts/launch-agent.plist.template >/dev/null
