#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

_PY=""
for candidate in "$REPO_ROOT/.venv/bin/python3" "$REPO_ROOT/.venv/bin/python" $(command -v python3 2>/dev/null || true) $(command -v python 2>/dev/null || true); do
    if [ -x "$candidate" ]; then
        _PY="$candidate"
        break
    fi
done

if [ -z "$_PY" ]; then
    echo "Error: Python not found" >&2
    exit 1
fi

exec "$_PY" "$REPO_ROOT/scripts/bundle.py" "$@"
