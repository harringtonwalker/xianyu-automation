#!/bin/zsh
set -euo pipefail
umask 077

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
BACKUPS_ROOT="$PROJECT_DIR/backups"
DATA_DIR="$PROJECT_DIR/data"
BACKUP_DIR="${1:-}"
MODE="${2:-}"

if [[ -z "$BACKUP_DIR" ]]; then
  echo "用法：./scripts/restore.command /完整路径/backups/YYYYMMDD-HHMMSS" >&2
  exit 2
fi
BACKUP_DIR="${BACKUP_DIR:A}"
if [[ "$BACKUP_DIR" != "$BACKUPS_ROOT/"* ]] || [[ ! -d "$BACKUP_DIR" ]]; then
  echo "拒绝恢复：备份目录必须位于本项目 backups/ 内。" >&2
  exit 2
fi
if [[ ! -f "$BACKUP_DIR/SHA256SUMS" ]]; then
  echo "拒绝恢复：备份缺少 SHA256SUMS。" >&2
  exit 4
fi
(cd "$BACKUP_DIR" && shasum -a 256 -c SHA256SUMS)

STAGE_DIR="$(mktemp -d "$PROJECT_DIR/.restore-stage.XXXXXX")"
trap 'rm -rf "$STAGE_DIR"' EXIT
if [[ -f "$BACKUP_DIR/automation.db" ]]; then
  install -m 600 "$BACKUP_DIR/automation.db" "$STAGE_DIR/automation.db"
  integrity="$(sqlite3 "$STAGE_DIR/automation.db" 'PRAGMA integrity_check;')"
  [[ "$integrity" == "ok" ]] || { echo "拒绝恢复：SQLite 完整性检查失败。" >&2; exit 5; }
  PYTHONPATH="$PROJECT_DIR" python3 -c \
    'from pathlib import Path; from xianyu_ops.store import Store; Store(Path(__import__("sys").argv[1]) / "automation.db")' \
    "$STAGE_DIR"
fi
if [[ -f "$BACKUP_DIR/config.json" ]]; then
  install -m 600 "$BACKUP_DIR/config.json" "$STAGE_DIR/config.json"
  python3 -m json.tool "$STAGE_DIR/config.json" >/dev/null
fi
if [[ -d "$BACKUP_DIR/assets" ]]; then
  ditto "$BACKUP_DIR/assets" "$STAGE_DIR/assets"
fi
if [[ "$MODE" == "--check-only" ]]; then
  echo "恢复演练通过：校验和、SQLite 完整性、当前数据迁移与配置解析均通过；未改动 data/。"
  exit 0
fi
if [[ "$MODE" != "" ]]; then
  echo "未知参数：$MODE" >&2
  exit 2
fi
if lsof -nP -iTCP:8766 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "拒绝恢复：8766 端口上的服务仍在运行。请先停止登录服务或终端服务。" >&2
  exit 3
fi

required="确认恢复 $(basename "$BACKUP_DIR")"
echo "此操作会先保留当前 data/，再恢复备份。"
echo "请输入：$required"
read -r acknowledgement
[[ "$acknowledgement" == "$required" ]] || { echo "确认文字不匹配，未执行。"; exit 6; }

ROLLBACK_DIR="$PROJECT_DIR/data.pre-restore.$(date +%Y%m%d-%H%M%S)"
if [[ -d "$DATA_DIR" ]]; then
  mv "$DATA_DIR" "$ROLLBACK_DIR"
fi
mv "$STAGE_DIR" "$DATA_DIR"
trap - EXIT
find "$DATA_DIR" -type d -exec chmod 700 {} +
find "$DATA_DIR" -type f -exec chmod 600 {} +
echo "恢复完成。原 data/ 保存在：$ROLLBACK_DIR"
