#!/bin/zsh
set -euo pipefail

PLIST_PATH="$HOME/Library/LaunchAgents/io.github.harringtonwalker.xianyu-ops.plist"
if [[ ! -e "$PLIST_PATH" ]]; then
  echo "未发现登录启动服务。"
  exit 0
fi

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
mv "$PLIST_PATH" "$HOME/.Trash/io.github.harringtonwalker.xianyu-ops.plist.$(date +%Y%m%d%H%M%S)"
echo "登录启动服务已移到废纸篓，可恢复。"
