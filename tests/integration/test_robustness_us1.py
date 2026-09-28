"""Integration tests for the rescue ladder and honest envelopes.

Runs against the real engine over ``tests/fixtures/robustness/`` with the
relevance gate left ON (production settings). Three behaviors are pinned:

* A well-formed query with zero or one informative token that the ranked tier
  rejects is rescued by the lexical and literal tiers instead of being answered
  with an empty, unexplained result set.
* The envelope exposes ``mode``, per-result ``confidence`` bands, and an
  ``explanation`` object; a truly unmatched query never fabricates results and
  reports ``reason: no_match``.
* Envelope fields are stable: ``total_matches``/``truncated`` stay consistent
  and every result carries ``confidence``/``confidence_band``/``role``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ORACLE = json.loads(
    Path(__file__)
    .resolve()
    .parent.parent.joinpath("fixtures", "robustness.oracle.json")
    .read_text()
)


@pytest.mark.parametrize("term", ["hasRole"])
def test_ranked_query_is_complete_and_honest(indexed_robustness: dict[str, Any], term: str) -> None:
    """A plain identifier query returns ranked results with per-result metadata
    and an explicit mode/confidence envelope."""
    envelope = indexed_robustness["search"].search(term, limit=5)
    assert envelope["mode"] == "ranked"
    assert envelope["total_matches"] >= 1
    assert envelope["truncated"] in (True, False)
    assert envelope["confidence"] in ("high", "medium", "low", "none")
    assert "complete" not in envelope, "ranked envelopes must omit complete (FR-009)"
    assert envelope.get("best_effort") is True
    assert "explanation" in envelope
    for result in envelope["results"]:
        assert "confidence" in result
        assert result["confidence_band"] in ("high", "medium", "low")
        assert result["role"] in ("definition", "reference")
        assert "file_role" in result


def test_rescue_t1_answers_single_informative_token(indexed_robustness: dict[str, Any]) -> None:
    """A query the ranked tier's informative-token gate rejects
    ('comment' is the only informative sub-word; the rest is stopword/boilerplate)
    is rescued by the relaxed lexical tier instead of returning nothing.

    The match-boost layer is disabled so this stays a pure rescue-ladder test:
    ``comment`` also exactly names ``Comment.java``, and the filename-boost layer
    would otherwise admit it into the ranked path (covered by
    ``test_filename_exact_boost.py``).
    """
    from dataclasses import replace

    settings = replace(
        indexed_robustness["settings"],
        informative_tokens_min=2,
        relevance_gate=True,
        relevance_threshold=0.0,
        match_boost_enabled=False,
    )
    search = indexed_robustness["search"].__class__(
        indexed_robustness["db"],
        indexed_robustness["vector_index"],
        indexed_robustness["embedding_gen"],
        settings,
    )
    envelope = search.search("comment", limit=5)
    assert envelope["mode"] in ("ranked-lexical", "literal")
    assert envelope["confidence"] != "none"
    assert envelope["total_matches"] >= 1
    assert envelope["explanation"]["rescued_tiers"] == ["lexical"]
    assert any("Comment" in r["file_path"] for r in envelope["results"])


def test_no_match_never_fabricates_results(indexed_robustness: dict[str, Any]) -> None:
    """A query with no matching tokens in the index returns an empty
    result list with an explicit ``no_match`` explanation — nothing is invented."""
    envelope = indexed_robustness["search"].search("wqrble zorp", limit=5)
    assert envelope["results"] == []
    assert envelope["total_matches"] == 0
    assert envelope["confidence"] == "none"
    assert envelope["explanation"]["reason"] == "no_match"
    assert envelope["explanation"]["rescued_tiers"] == ["lexical", "literal"]
    assert envelope["explanation"]["confidence"] == "none"
    assert "complete" not in envelope, "ranked envelopes must omit complete (FR-009)"


def test_blank_query_reports_invalid_query(indexed_robustness: dict[str, Any]) -> None:
    envelope = indexed_robustness["search"].search("   ", limit=5)
    assert envelope["results"] == []
    assert envelope["explanation"]["reason"] == "invalid_query"


def test_rescue_result_metadata_is_complete(indexed_robustness: dict[str, Any]) -> None:
    """Every rescued result still carries the full per-result contract so
    consumers can render it uniformly."""
    from dataclasses import replace

    settings = replace(
        indexed_robustness["settings"],
        informative_tokens_min=2,
        relevance_gate=True,
        relevance_threshold=0.0,
    )
    search = indexed_robustness["search"].__class__(
        indexed_robustness["db"],
        indexed_robustness["vector_index"],
        indexed_robustness["embedding_gen"],
        settings,
    )
    envelope = search.search("comment", limit=5)
    for result in envelope["results"]:
        assert "chunk_id" in result
        assert "file_path" in result
        assert "content" in result
        assert result["confidence_band"] in ("high", "medium", "low")
        assert result["role"] in ("definition", "reference")
