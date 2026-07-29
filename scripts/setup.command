#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON_BOOTSTRAP="${PYTHON_BOOTSTRAP:-$(command -v python3)}"

if [[ -z "$PYTHON_BOOTSTRAP" ]]; then
  echo "未找到 Python 3。请先安装 Python 3.11 或更高版本。" >&2
  exit 1
fi

"$PYTHON_BOOTSTRAP" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' || {
  echo "Python 版本过低；需要 Python 3.11 或更高版本。" >&2
  exit 1
}

"$PYTHON_BOOTSTRAP" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_DIR/requirements.lock"
"$VENV_DIR/bin/python" -c 'import PIL; raise SystemExit(PIL.__version__ != "12.2.0")'

echo "安装完成。下一步运行：./scripts/start.command"
