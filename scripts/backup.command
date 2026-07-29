#!/bin/zsh
set -euo pipefail
umask 077

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
DATA_DIR="$PROJECT_DIR/data"
BACKUP_DIR="$PROJECT_DIR/backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
chmod 700 "$PROJECT_DIR/backups" "$BACKUP_DIR"

if [[ -f "$DATA_DIR/automation.db" ]]; then
  sqlite3 "$DATA_DIR/automation.db" ".backup '$BACKUP_DIR/automation.db'"
fi
if [[ -f "$DATA_DIR/config.json" ]]; then
  install -m 600 "$DATA_DIR/config.json" "$BACKUP_DIR/config.json"
fi
if [[ -d "$DATA_DIR/assets" ]]; then
  ditto "$DATA_DIR/assets" "$BACKUP_DIR/assets"
fi
(cd "$BACKUP_DIR" && find . -type f ! -name SHA256SUMS -exec shasum -a 256 {} + > SHA256SUMS)
find "$BACKUP_DIR" -type d -exec chmod 700 {} +
find "$BACKUP_DIR" -type f -exec chmod 600 {} +
echo "备份完成：$BACKUP_DIR"
