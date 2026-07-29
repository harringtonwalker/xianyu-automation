#!/bin/zsh
set -euo pipefail
umask 077

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
PYTHON_BIN="${1:-$(command -v python3)}"
LOG_DIR="$PROJECT_DIR/data/logs"
mkdir -p "$LOG_DIR"
chmod 700 "$PROJECT_DIR/data" "$LOG_DIR"

for log_path in "$LOG_DIR/service.out.log" "$LOG_DIR/service.err.log"; do
  if [[ -f "$log_path" ]] && [[ $(stat -f %z "$log_path") -gt 10485760 ]]; then
    mv -f "$log_path" "$log_path.1"
    chmod 600 "$log_path.1"
  fi
done

if ! "$PYTHON_BIN" -c 'import PIL; raise SystemExit(PIL.__version__ != "12.3.0")'; then
  echo "Pillow 版本不匹配；必须安装 requirements.lock 中的 12.3.0。" >&2
  exit 1
fi

cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"
exec "$PYTHON_BIN" -m xianyu_ops.server \
  --host 127.0.0.1 \
  --port 8766 \
  --data-dir "$PROJECT_DIR/data"
