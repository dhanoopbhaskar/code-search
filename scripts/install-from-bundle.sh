#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if command -v python3 &>/dev/null; then
    _PY="python3"
elif command -v python &>/dev/null; then
    _PY="python"
else
    echo "Error: Python not found" >&2
    exit 1
fi

exec "$_PY" "$SCRIPT_DIR/install-from-bundle.py" "$@"
