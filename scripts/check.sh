#!/usr/bin/env bash
# Thin Unix wrapper: the checks live in check.py so the same gate runs on
# Windows, macOS, and Linux. Arguments after -- are forwarded to pytest.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Prefer the repo venv (also covers a stale VIRTUAL_ENV after the checkout
# moved) so the pre-commit hook and `make` targets work without activation.
if [ -x "$ROOT/.venv/bin/python3" ]; then
    _PY="$ROOT/.venv/bin/python3"
elif [ -x "$ROOT/.venv/bin/python" ]; then
    _PY="$ROOT/.venv/bin/python"
elif [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
    _PY="$ROOT/.venv/Scripts/python.exe"
elif command -v python3 &>/dev/null; then
    _PY="python3"
elif command -v python &>/dev/null; then
    _PY="python"
else
    echo "Error: Python not found" >&2
    exit 1
fi

exec "$_PY" "$ROOT/scripts/check.py" "$@"
