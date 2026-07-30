#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
cd "$PROJECT_DIR"

PYTHON_BIN="$(command -v python3)"
"$PYTHON_BIN" - "$PROJECT_DIR" <<'PY'
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import PurePosixPath


project_dir = sys.argv[1]


def git(*args: str) -> bytes:
    process = subprocess.run(
        ["git", *args],
        cwd=project_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        raise SystemExit(
            "publication boundary check could not inspect the Git index"
        )
    return process.stdout


records = git("ls-files", "--stage", "-z").split(b"\0")
failures: list[tuple[str, str]] = []

forbidden_roots = {
    ".agents",
    ".codex",
    ".venv",
    "backups",
    "data",
    "htmlcov",
    "logs",
    "node_modules",
}
forbidden_parts = {
    "__pycache__",
    ".pytest_cache",
}
forbidden_names = {
    ".env",
    "cookies.json",
    "hosts.yml",
    "id_dsa",
    "id_ed25519",
    "id_rsa",
}
forbidden_suffixes = {
    ".db",
    ".key",
    ".log",
    ".mobileprovision",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
    ".sqlite",
    ".sqlite3",
}
secret_patterns = [
    ("GitHub token", re.compile(rb"\bgh[opusr]_[A-Za-z0-9_]{20,}\b")),
    ("GitHub fine-grained token", re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("OpenAI-style API key", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("AWS access key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Slack token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("private key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("local home path", re.compile(rb"/Users/[A-Za-z0-9._-]+/")),
]
sensitive_identifier_pattern = re.compile(
    rb"(?i)\b(?:user|account)[_-]?id\b\s*[:=]\s*[\"']?[0-9]{6,}"
)

for raw_record in records:
    if not raw_record:
        continue
    metadata, raw_path = raw_record.split(b"\t", 1)
    mode, _object_id, stage = metadata.decode("ascii").split(" ")
    path = raw_path.decode("utf-8")
    pure_path = PurePosixPath(path)
    parts = pure_path.parts
    lower_name = pure_path.name.lower()
    lower_suffix = pure_path.suffix.lower()

    if stage != "0":
        failures.append((path, "unmerged index entry"))
        continue
    if mode in {"120000", "160000"}:
        failures.append((path, "symlinks and submodules are not public-source inputs"))
        continue
    if parts and parts[0] in forbidden_roots:
        failures.append((path, "private runtime directory"))
        continue
    if any(part in forbidden_parts for part in parts):
        failures.append((path, "generated cache directory"))
        continue
    if lower_name.startswith(".env") and lower_name != ".env.example":
        failures.append((path, "environment secret file"))
        continue
    if lower_name in forbidden_names or lower_suffix in forbidden_suffixes:
        failures.append((path, "private or generated file type"))
        continue

    content = git("show", f":{path}")
    if len(content) > 5 * 1024 * 1024:
        failures.append((path, "file exceeds the 5 MiB public-source limit"))
        continue
    if b"\0" in content:
        failures.append((path, "binary file requires explicit human review"))
        continue
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        failures.append((path, "non-UTF-8 file requires explicit human review"))
        continue
    for rule_name, pattern in secret_patterns:
        if pattern.search(content):
            failures.append((path, rule_name))
    if parts and parts[0] not in {"samples", "tests"}:
        if sensitive_identifier_pattern.search(content):
            failures.append((path, "account identifier"))

if failures:
    print("Publication boundary check failed:", file=sys.stderr)
    for path, reason in sorted(set(failures)):
        print(f"- {path}: {reason}", file=sys.stderr)
    print(
        "Remove the private material from the Git index; no matching content was printed.",
        file=sys.stderr,
    )
    raise SystemExit(1)

print(f"Publication boundary: PASS ({len([r for r in records if r])} tracked files)")
PY
