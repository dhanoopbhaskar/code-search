#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

REPO_PATH=""
PYTEST_ARGS="-v --tb=short"

usage() {
    cat <<EOF
Usage: run_acceptance.sh [OPTIONS]

Run the code-search acceptance test suite against a real repository.

Options:
  --repo-path PATH     Path to a git repository (required)
  --keep-index         Skip re-indexing if .context/ already exists
  --quick              Run only fast tests (skip slow indexing tests)
  -x                   Stop on first failure
  -k EXPR              Only run tests matching expression
  --markers EXPR       Filter by pytest markers
  -h, --help           Show this help

Examples:
  # Test against this repo itself
  ./run_acceptance.sh --repo-path .

  # Test against another repo, keep cached index
  ./run_acceptance.sh --repo-path /path/to/project --keep-index

  # Quick smoke test
  ./run_acceptance.sh --repo-path . -k "test_search_returns_results or test_index_populates"

  # Run with pip installed first
  pip install -e "$ROOT_DIR"
  ./run_acceptance.sh --repo-path /some/repo
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo-path)
            REPO_PATH="$2"
            shift 2
            ;;
        --keep-index)
            PYTEST_ARGS="$PYTEST_ARGS --keep-index"
            shift
            ;;
        --quick)
            PYTEST_ARGS="$PYTEST_ARGS -m 'not slow'"
            shift
            ;;
        -k)
            PYTEST_ARGS="$PYTEST_ARGS -k '$2'"
            shift 2
            ;;
        -x)
            PYTEST_ARGS="$PYTEST_ARGS -x"
            shift
            ;;
        --markers)
            PYTEST_ARGS="$PYTEST_ARGS -m '$2'"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

if [[ -z "$REPO_PATH" ]]; then
    echo "Error: --repo-path is required"
    usage
fi

if [[ ! -d "$REPO_PATH" ]]; then
    echo "Error: '$REPO_PATH' is not a valid directory"
    exit 1
fi

REPO_PATH="$(cd "$REPO_PATH" && pwd)"

echo "============================================"
echo "code-search Acceptance Test Suite"
echo "============================================"
echo "Repo:  $REPO_PATH"
echo "Root:  $ROOT_DIR"
echo ""

if [[ "$VIRTUAL_ENV" != "" ]]; then
    echo "venv:  $VIRTUAL_ENV"
fi

echo "--- Installing code-search (editable) ---"
pip install -e "$ROOT_DIR" --quiet 2>&1 | tail -1

echo ""
echo "--- Running acceptance tests ---"
echo ""

cd "$ROOT_DIR"
python -m pytest tests/acceptance/ \
    $PYTEST_ARGS \
    --repo-path "$REPO_PATH" \
    "$@"

EXIT_CODE=$?

echo ""
echo "============================================"
if [[ $EXIT_CODE -eq 0 ]]; then
    echo "All acceptance tests PASSED"
else
    echo "Some acceptance tests FAILED (exit code: $EXIT_CODE)"
fi
echo "============================================"

exit $EXIT_CODE
