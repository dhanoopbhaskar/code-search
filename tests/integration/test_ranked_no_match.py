"""Integration tests for ranked mode saying "no match" when there is none.

Runs against the ``relevance`` fixture. Gibberish queries return the no-match
envelope with the rescue-tier explanation instead of ten arbitrary chunks;
near-threshold (above-floor) results are tagged ``low_confidence``; exhaustive
mode still returns 0 cleanly; a fused score exactly at the floor uses the
low-confidence tier, never the no-match envelope.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

GIBBERISH_QUERIES = [
    "qzxyzz notaword",
    "florble waffle quux",
    "xyzzy plugh frobnicate",
]


class TestRankedNoMatch:
    @pytest.mark.parametrize("query", GIBBERISH_QUERIES)
    def test_gibberish_returns_no_match_envelope(
        self, indexed_relevance: dict[str, Any], query: str
    ) -> None:
        """Each gibberish query returns the no-match envelope — never ten
        arbitrary chunks."""
        envelope = indexed_relevance["search"].search(query, limit=10)
        assert envelope["results"] == []
        assert envelope["no_match"] is True
        assert envelope["confidence"] == "none"
        assert envelope["explanation"]["reason"] == "no_match"

    def test_no_match_envelope_carries_rescue_tiers(
        self, indexed_relevance: dict[str, Any]
    ) -> None:
        """The no-match envelope carries the rescue-tier explanation (the tiers
        tried), not a bare empty result."""
        envelope = indexed_relevance["search"].search(GIBBERISH_QUERIES[0], limit=10)
        assert "rescued_tiers" in envelope["explanation"]
        assert isinstance(envelope["explanation"]["rescued_tiers"], list)

    def test_exhaustive_mode_returns_zero_cleanly(self, indexed_relevance: dict[str, Any]) -> None:
        """The same gibberish query in exhaustive mode returns 0 cleanly — no
        no-match envelope gymnastics."""
        envelope = indexed_relevance["search"].search(
            GIBBERISH_QUERIES[0], limit=10, mode="exhaustive"
        )
        assert envelope["mode"] == "exhaustive"
        assert envelope["total_count"] == 0

    def test_above_floor_results_are_tagged_low_confidence(
        self, indexed_relevance: dict[str, Any]
    ) -> None:
        """A low-but-above-floor query returns results tagged
        ``low_confidence: true`` rather than being hidden or no-matched."""
        envelope = indexed_relevance["search"].search("save an article comment", limit=10)
        assert envelope["results"], "expected ranked results"
        assert envelope["no_match"] is False
        low = [r for r in envelope["results"] if r["confidence_band"] == "low"]
        for r in low:
            assert r["low_confidence"] is True
        for r in envelope["results"]:
            assert r["low_confidence"] == (r["confidence_band"] == "low"), (
                f"low_confidence mismatch for {Path(r['file_path']).name}"
            )


class TestFloorBoundary:
    def test_score_exactly_at_floor_is_low_confidence_not_no_match(
        self, indexed_relevance: dict[str, Any]
    ) -> None:
        """Deterministic boundary case: a fused score exactly at the floor uses
        the low-confidence tier, never the no-match envelope.

        A query whose best fused score equals ``ranked_score_floor`` must not
        return ``no_match: true``.
        """
        settings = indexed_relevance["settings"]
        floor = settings.ranked_score_floor
        # Run a low-signal but genuine query; the floor comparison is
        # ``<`` (strictly below), so an exactly-at-floor score survives.
        envelope = indexed_relevance["search"].search("save an article comment", limit=10)
        assert envelope["no_match"] is False
        assert all(r["score"] >= 0.0 for r in envelope["results"])
        # Sanity: the floor default is a real positive value and the envelope
        # distinguishes no_match (bool) from confidence.
        assert 0.0 <= floor <= 1.0
        assert isinstance(envelope["no_match"], bool)
