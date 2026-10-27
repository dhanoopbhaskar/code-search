"""Tests for the single-question ``ask`` router."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from code_search.engine.ask import _route, ask


def test_route_prefers_quoted_literals() -> None:
    """A quoted literal is an explicit exact-text request."""
    assert _route('find "payment declined"') == ("literal", "payment declined")


def test_route_selects_call_graph_questions() -> None:
    """Caller/callee phrasing maps to the graph directions."""
    assert _route("who calls PaymentService") == ("callers", "PaymentService")
    assert _route("what does PaymentService call") == ("callees", "PaymentService")


def test_route_selects_implementations_and_definitions() -> None:
    """Implementation and definition phrasing map to their surfaces."""
    assert _route("who implements Animal") == ("implementations", "Animal")
    assert _route("where is PaymentService defined") == ("definition", "PaymentService")
    assert _route("PaymentService") == ("definition", "PaymentService")


def test_route_falls_back_to_ranked_search() -> None:
    """Prose without a surface-specific phrase stays ranked search."""
    assert _route("how are refunds processed") == ("ranked", None)


def test_ask_answers_a_definition(indexed_implementations: dict[str, Any]) -> None:
    """A bare type name returns a compact definition answer."""
    payload = ask(indexed_implementations, "CalculatorImpl")
    assert payload["answer_type"] == "definition"
    assert payload["outcome"] == "resolved"
    answer = payload["answer"]
    assert "CalculatorImpl" in str(answer["fqn"])
    assert answer["file_path"]
    assert payload["next"]


def test_ask_answers_implementations(indexed_implementations: dict[str, Any]) -> None:
    """An implementation question delegates to the shared implementation rule."""
    payload = ask(indexed_implementations, "who implements fixtures.Animal")
    assert payload["answer_type"] == "implementations"
    assert payload["answer"]["implementations"]


def test_ask_answers_a_literal(indexed_implementations: dict[str, Any]) -> None:
    """A quoted literal uses exhaustive literal search."""
    payload = ask(indexed_implementations, '"speak"')
    assert payload["answer_type"] == "literal"
    assert payload["answer"]["results"]


def test_ask_budget_trims_rows(indexed_implementations: dict[str, Any]) -> None:
    """A very small budget drops rows and marks the payload truncated."""
    payload = ask(indexed_implementations, "who implements fixtures.Animal", budget=1)
    assert payload.get("truncated") or payload.get("budget_exceeded")


def test_ask_reports_unknown_implementation_target(indexed_implementations: dict[str, Any]) -> None:
    """A missing target is reported honestly with candidates rather than fabricated."""
    payload = ask(indexed_implementations, "who implements NotARealType")
    assert payload["answer_type"] == "implementations"
    assert payload["outcome"] in {"not_found", "no_static_implementation"}
    assert payload["answer"]["implementations"] == []


def test_ask_payload_paths_are_relative_to_the_index(
    indexed_implementations: dict[str, Any], tmp_path: Path
) -> None:
    """Search rows never expose the absolute index root."""
    payload = ask(indexed_implementations, '"speak"', limit=3)
    root = str(indexed_implementations["metadata"].get("index_root") or "")
    for row in payload["answer"]["results"]:
        assert not str(row.get("file_path") or "").startswith("/") or not root
        assert root not in str(row.get("file_path") or "")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
