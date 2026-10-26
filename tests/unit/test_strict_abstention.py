"""Tests for the opt-in strict abstention gate."""

from __future__ import annotations

from typing import Any

from code_search.engine.search import HybridSearch


def _envelope(
    band: str = "low",
    definition: bool = False,
    content: str = "unrelated implementation detail",
) -> dict[str, Any]:
    """Build a minimal ranked envelope for the gate."""
    return {
        "results": [
            {
                "confidence_band": band,
                "is_definition": definition,
                "content": content,
            }
        ],
        "total_matches": 1,
        "vector_health": True,
        "confidence": band,
        "mode": "ranked",
        "content": "all",
    }


def test_strict_abstention_rejects_low_confidence_low_coverage(
    indexed_robustness: dict[str, Any], monkeypatch: Any
) -> None:
    """Low confidence, no definition, and zero coverage becomes no_match."""
    hs: HybridSearch = indexed_robustness["search"]
    monkeypatch.setattr(
        hs._bm25, "informative_tokens", lambda _query: ["payment", "checkout", "refund"]
    )
    rejected = hs._strict_abstention(_envelope(), "payment checkout refund")
    assert rejected["no_match"] is True
    assert rejected["results"] == []
    assert rejected["alternatives"][0]["content"] == "unrelated implementation detail"
    assert rejected["no_match_signals"]["coverage"] == 0.0


def test_strict_abstention_keeps_definition_hits(
    indexed_robustness: dict[str, Any], monkeypatch: Any
) -> None:
    """A definition is an answer even when its band is low."""
    hs: HybridSearch = indexed_robustness["search"]
    monkeypatch.setattr(hs._bm25, "informative_tokens", lambda _query: ["payment"])
    original = _envelope(definition=True)
    assert hs._strict_abstention(original, "payment") is original


def test_strict_abstention_keeps_medium_confidence(
    indexed_robustness: dict[str, Any], monkeypatch: Any
) -> None:
    """Only a low top-1 band is eligible for strict abstention."""
    hs: HybridSearch = indexed_robustness["search"]
    monkeypatch.setattr(hs._bm25, "informative_tokens", lambda _query: ["payment"])
    original = _envelope(band="medium")
    assert hs._strict_abstention(original, "payment") is original


def test_strict_abstention_keeps_covered_results(
    indexed_robustness: dict[str, Any], monkeypatch: Any
) -> None:
    """Sufficient informative coverage is never rejected."""
    hs: HybridSearch = indexed_robustness["search"]
    monkeypatch.setattr(hs._bm25, "informative_tokens", lambda _query: ["payment", "checkout"])
    original = _envelope(content="payment checkout handling")
    assert hs._strict_abstention(original, "payment checkout") is original
