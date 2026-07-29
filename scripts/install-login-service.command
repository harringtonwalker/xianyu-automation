#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
PLIST_PATH="$HOME/Library/LaunchAgents/io.github.harringtonwalker.xianyu-ops.plist"
LOG_DIR="$PROJECT_DIR/data/logs"
if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi
mkdir -p "$LOG_DIR"

if [[ -e "$PLIST_PATH" ]]; then
  echo "登录服务已存在：$PLIST_PATH"
  echo "如需重装，请先运行 scripts/uninstall-login-service.command"
  exit 1
fi

escaped_project=${PROJECT_DIR//&/&amp;}
escaped_project=${escaped_project//</&lt;}
escaped_project=${escaped_project//>/&gt;}
escaped_python=${PYTHON_BIN//&/&amp;}
escaped_python=${escaped_python//</&lt;}
escaped_python=${escaped_python//>/&gt;}

temp_plist="$(mktemp)"
trap 'rm -f "$temp_plist"' EXIT
sed \
  -e "s|__PROJECT_DIR__|$escaped_project|g" \
  -e "s|__PYTHON_BIN__|$escaped_python|g" \
  "$PROJECT_DIR/scripts/launch-agent.plist.template" > "$temp_plist"
plutil -lint "$temp_plist" >/dev/null
install -m 600 "$temp_plist" "$PLIST_PATH"
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
echo "已安装登录启动服务：$PLIST_PATH"
echo "控制台地址：http://127.0.0.1:8766"
