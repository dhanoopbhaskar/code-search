"""Integration tests for the honest, non-zero semantic signal.

Runs against the real engine over the hermetic ``semantic_vector`` fixture and
the ``robustness`` fixture. Pins the truthful reporting contract: a zero
``vector_score`` always carries a non-``semantic`` contribution label, a
retrieved chunk reports its actual positive similarity, and the same labelling
holds on the rescue/tier paths. Also pins representation-scheme staleness
detection.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.engine.embed_representation import REPRESENTATION_SCHEME_VERSION

QUERIES: tuple[str, ...] = (
    "how long can a user stay signed in before their session token expires",
    "reject creating an account when the email is already registered",
    "convert domain entities into API response objects",
    "when does a logged-in user get disconnected",
)

ALLOWED_CONTRIBUTIONS = {"semantic", "lexical_only", "deferred", "unavailable"}


def _assert_result_invariant(result: dict[str, Any]) -> None:
    """Assert the truthful per-result vector reporting invariant."""
    assert isinstance(result["vector_retrieved"], bool)
    assert result["semantic_contribution"] in ALLOWED_CONTRIBUTIONS
    if result["vector_retrieved"]:
        assert result["semantic_contribution"] == "semantic"
        assert result["vector_score"] > 0.0
    else:
        assert result["vector_score"] == 0.0
    if result["semantic_contribution"] == "semantic":
        assert result["vector_score"] > 0.0


def test_fused_path_has_no_unexplained_zero(
    indexed_semantic_vector: dict[str, Any],
) -> None:
    """On a healthy layer, every returned result either
    reports a positive semantic score or is explicitly labelled non-semantic."""
    search = indexed_semantic_vector["search"]
    semantic_seen = False
    for query in QUERIES:
        envelope = search.search(query, limit=10)
        assert envelope.get("vector_health") is True
        for result in envelope["results"]:
            _assert_result_invariant(result)
            semantic_seen = semantic_seen or result["vector_retrieved"]
    assert semantic_seen, "the dense arm must retrieve at least one result"


def test_ground_truth_results_report_non_zero_semantic_scores(
    indexed_semantic_vector: dict[str, Any],
) -> None:
    """Ground-truth chunks surfaced in the top 5 carry a non-zero
    semantic score (or are labelled lexical-only), so no relevant result shows a
    confusing zero."""
    search = indexed_semantic_vector["search"]
    ground_truth = ("SessionWindowPolicy", "ConnectionLifetimePolicy", "AuthProperties")
    results = search.search(
        "how long can a user stay signed in before their session token expires", limit=5
    )["results"]
    hits = [r for r in results if any(name in r["file_path"] for name in ground_truth)]
    assert hits, "expected a ground-truth result in the top 5"
    for result in hits:
        _assert_result_invariant(result)
        assert result["semantic_contribution"] != "semantic" or result["vector_score"] > 0.0


def test_zero_and_negative_dense_similarity_is_lexical_only(
    indexed_semantic_vector: dict[str, Any],
) -> None:
    """A dense candidate whose actual similarity is ``<= 0.0`` is
    not a semantic retrieval — it reports a zero score labelled ``lexical_only``.
    """
    search = indexed_semantic_vector["search"]
    for raw_score in (0.0, -0.25):
        reported, retrieved, contribution = search._resolve_semantic_report(
            42,
            {42: raw_score},
            vector_health=True,
            defer_vector=False,
            model_warm=True,
            lexical_only_query=False,
        )
        assert (reported, retrieved, contribution) == (0.0, False, "lexical_only")


def test_positive_dense_similarity_reports_actual_score(
    indexed_semantic_vector: dict[str, Any],
) -> None:
    """A positive dense hit reports its actual similarity, not a
    post-filter default."""
    search = indexed_semantic_vector["search"]
    reported, retrieved, contribution = search._resolve_semantic_report(
        7,
        {7: 0.42},
        vector_health=True,
        defer_vector=False,
        model_warm=True,
        lexical_only_query=False,
    )
    assert (reported, retrieved, contribution) == (0.42, True, "semantic")


def test_deferred_and_unavailable_labels(indexed_semantic_vector: dict[str, Any]) -> None:
    """The cold reduced path and a degraded layer are labelled
    without fabricating a non-zero score."""
    search = indexed_semantic_vector["search"]
    assert search._resolve_semantic_report(
        1, {}, vector_health=True, defer_vector=True, model_warm=False, lexical_only_query=False
    ) == (0.0, False, "deferred")
    assert search._resolve_semantic_report(
        1,
        {},
        vector_health=False,
        defer_vector=False,
        model_warm=True,
        lexical_only_query=False,
    ) == (0.0, False, "unavailable")


def test_rescue_path_labels_zero_scores(
    indexed_robustness: dict[str, Any],
) -> None:
    """A rescue-surfaced result (``ranked-lexical``/``literal``)
    is labelled ``lexical_only`` and never carries an unexplained zero."""
    from dataclasses import replace

    settings = replace(
        indexed_robustness["settings"],
        informative_tokens_min=2,
        relevance_gate=True,
        relevance_threshold=0.0,
        match_boost_enabled=False,
    )
    comps = indexed_robustness
    search = comps["search"].__class__(
        comps["db"], comps["vector_index"], comps["embedding_gen"], settings
    )
    envelope = search.search("comment", limit=5)
    assert envelope["mode"] in ("ranked-lexical", "literal")
    assert envelope["results"]
    for result in envelope["results"]:
        _assert_result_invariant(result)
        assert result["semantic_contribution"] == "lexical_only"


# --- Scenario D: representation-scheme staleness -------------------------------


def test_search_rejects_older_scheme_index(
    indexed_semantic_vector: dict[str, Any],
) -> None:
    """A search against an old-scheme index raises the
    re-index error instead of silently serving old-scheme scores."""
    meta = indexed_semantic_vector["meta"]
    meta.set_int("representation_scheme_version", REPRESENTATION_SCHEME_VERSION - 1)
    with pytest.raises(ValueError, match="--force"):
        indexed_semantic_vector["search"].search("session token", limit=5)


def test_search_rejects_pre_marker_engine_built_index(
    indexed_semantic_vector: dict[str, Any],
) -> None:
    """An engine-built index that holds vectors but has no
    scheme marker (a pre-marker index) is detected as stale on search."""
    db = indexed_semantic_vector["db"]
    with db.write_transaction() as conn:
        conn.execute("DELETE FROM index_metadata WHERE key = 'representation_scheme_version';")
    assert indexed_semantic_vector["meta"].get("vector_model_name")
    assert indexed_semantic_vector["vector_index"].size > 0
    with pytest.raises(ValueError, match="--force"):
        indexed_semantic_vector["search"].search("session token", limit=5)


def test_search_accepts_current_scheme_index(
    indexed_semantic_vector: dict[str, Any],
) -> None:
    """An index carrying the current scheme is compatible."""
    assert (
        indexed_semantic_vector["meta"].get_int("representation_scheme_version")
        == REPRESENTATION_SCHEME_VERSION
    )
    envelope = indexed_semantic_vector["search"].search("session token", limit=5)
    assert envelope["vector_health"] is True


def test_index_run_forces_full_reindex_on_stale_scheme(
    indexed_semantic_vector: dict[str, Any],
) -> None:
    """A stale scheme forces a full, non-incremental re-index that
    regenerates the chunks an incremental run would have skipped."""
    comps = indexed_semantic_vector
    db = comps["db"]
    meta = comps["meta"]
    with db.connect() as conn:
        before = conn.execute("SELECT COUNT(*) AS n FROM code_chunks;").fetchone()["n"]
    assert before > 0
    with db.write_transaction() as conn:
        conn.execute("DELETE FROM code_chunks WHERE id = (SELECT MIN(id) FROM code_chunks);")
    meta.set_int("representation_scheme_version", REPRESENTATION_SCHEME_VERSION - 1)

    comps["orchestrator"].index_codebase(root_path=comps["repo"], force=True, incremental=True)

    with db.connect() as conn:
        after = conn.execute("SELECT COUNT(*) AS n FROM code_chunks;").fetchone()["n"]
    assert after == before, "stale scheme must force a full re-index"
    assert meta.get_int("representation_scheme_version") == REPRESENTATION_SCHEME_VERSION
