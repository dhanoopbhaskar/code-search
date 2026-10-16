#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTION]...

Run code quality checks for code-search.

Options:
  --all        Run all checks (default)
  --lint       Run ruff lint check only
  --format     Run ruff format check only
  --typecheck  Run mypy type check only
  --test       Run pytest only

Any additional arguments after -- are passed to pytest.
EOF
  exit 0
}

mode="all"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all) mode="all"; shift ;;
    --lint) mode="lint"; shift ;;
    --format) mode="format"; shift ;;
    --typecheck) mode="typecheck"; shift ;;
    --test) mode="test"; shift ;;
    -h|--help) usage ;;
    --) shift; break ;;
    -*) echo "Unknown option: $1"; usage ;;
    *) break ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Prefer an already-activated, still-existing venv; otherwise fall back to the
# repo's own .venv so the pre-commit hook and `make` targets work even when a
# stale VIRTUAL_ENV (e.g. after the checkout moved) lingers in the shell.
if [ ! -d "${VIRTUAL_ENV:-}" ]; then
  unset VIRTUAL_ENV
  if [ -x "$ROOT/.venv/bin/python3" ]; then
    export PATH="$ROOT/.venv/bin:$PATH"
  fi
fi

failed=0

run() {
  local name="$1"
  shift
  echo "========== $name =========="
  if "$@"; then
    echo "  PASS"
  else
    echo "  FAIL"
    failed=1
  fi
  echo
}

case "$mode" in
  all)
    run "ruff check"      ruff check code_search/ tests/
    run "ruff format"     ruff format --check code_search/ tests/
    run "comment refs"    python3 scripts/check_comment_refs.py code_search/ tests/ scripts/
    run "mypy"            mypy code_search/
    run "pytest"          pytest tests/ "$@"
    ;;
  lint)
    run "ruff check"      ruff check code_search/ tests/
    run "comment refs"    python3 scripts/check_comment_refs.py code_search/ tests/ scripts/
    ;;
  format)
    run "ruff format"     ruff format --check code_search/ tests/
    ;;
  typecheck)
    run "mypy"            mypy code_search/
    ;;
  test)
    run "pytest"          pytest tests/ "$@"
    ;;
esac

if [ "$failed" -eq 1 ]; then
  echo "Some checks failed."
  exit 1
fi

echo "All checks passed."
