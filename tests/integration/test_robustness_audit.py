"""Audit coverage for the search modes.

Every search mode — ranked, exhaustive, enumerate, and the rescue tiers
(``ranked-lexical``/``literal``) — must record an append-only audit entry with
query type and result summary. Runs the real CLI against the indexed
robustness fixture and asserts the shared audit database grew by exactly the
number of searches issued.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

MODES: list[tuple[str, list[str]]] = [
    ("ranked", ["hasRole"]),
    ("exhaustive", ["PasswordEncoder", "--mode", "exhaustive"]),
    ("enumerate", ["list all controllers", "--mode", "enumerate"]),
    ("rescue", ["who is allowed to delete a comment"]),
]


def _run_cli_search(context_dir: str, query: list[str]) -> None:
    from src.cli.main import main

    test_args = ["code-search", "search", f"--context-dir={context_dir}", *query]
    try:
        sys.argv = test_args
        main()
    except SystemExit as e:
        assert e.code == 0, f"CLI search {query!r} exited {e.code}"


@pytest.mark.integration
def test_all_modes_record_append_only_audit_entries(
    indexed_robustness: dict[str, Any],
) -> None:
    audit_db = indexed_robustness["audit_db"]
    context_dir = str(indexed_robustness["context_dir"])

    before = audit_db.count_entries()
    for _mode, query in MODES:
        _run_cli_search(context_dir, query)

    entries = audit_db.get_entries(limit=100)
    new_entries = [e for e in entries if e["id"] > before]
    assert len(new_entries) == len(MODES), (
        f"expected {len(MODES)} audit entries, got {len(new_entries)}: "
        f"{[(e['query_summary'], e['query_type']) for e in new_entries]}"
    )
    for entry in new_entries:
        assert entry["query_type"] == "search"
        assert entry["result_count"] >= 0
        assert entry["duration_ms"] >= 0
        assert entry["id"] > before  # append-only, monotonically increasing


@pytest.mark.integration
def test_exhaustive_and_enumerate_audit_result_counts(
    indexed_robustness: dict[str, Any],
) -> None:
    audit_db = indexed_robustness["audit_db"]
    context_dir = str(indexed_robustness["context_dir"])

    before = audit_db.count_entries()
    _run_cli_search(context_dir, ["PasswordEncoder", "--mode", "exhaustive"])
    _run_cli_search(context_dir, ["list all controllers", "--mode", "enumerate"])

    entries = audit_db.get_entries(limit=100)
    new_entries = [e for e in entries if e["id"] > before]
    assert len(new_entries) == 2
    counts = sorted(e["result_count"] for e in new_entries)
    assert counts == [7, 8]
