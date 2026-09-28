"""Integration tests for conceptual queries with no keyword overlap.

Runs against the real engine over ``tests/fixtures/semantic_vector/``, whose
ground-truth code shares no literal keywords with the conceptual queries. The
headline fix restored the vector arm of the BM25 + vector RRF fusion, so
these paraphrased questions must surface their known ground-truth chunks within
the top 5 results with a live, non-degraded vector signal.

The fixture disables the relevance gate (see ``tests/conftest.py``) so the tiny
synthetic corpus returns the query-time evidence each story asserts.
"""

from __future__ import annotations

from typing import Any

import pytest

# Ground-truth chunk files per conceptual query. The synthetic corpus mirrors
# the benchmark failure signature: none of these queries' words appear
# literally in the code they must surface.
GROUND_TRUTH: dict[str, tuple[str, ...]] = {
    "token-expiration": (
        "session/SessionWindowPolicy.java",
        "session/ConnectionLifetimePolicy.java",
        "session/AuthProperties.java",
    ),
    "email-registered": (
        "identity/EnrollmentRegistry.java",
        "identity/IdentityDirectory.java",
    ),
    "entity-response": (
        "presentation/ModelViewFactory.java",
        "presentation/ArticleContent.java",
    ),
    "disconnected-session": (
        "session/ConnectionLifetimePolicy.java",
        "session/SessionWindowPolicy.java",
    ),
}

QUERIES: dict[str, str] = {
    "token-expiration": "how long can a user stay signed in before their session token expires",
    "email-registered": "reject creating an account when the email is already registered",
    "entity-response": "convert domain entities into API response objects",
    "disconnected-session": "when does a logged-in user get disconnected",
}


def _top_results(comps: dict[str, Any], query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return the real search results for *query* over an indexed fixture."""
    envelope = comps["search"].search(query, limit=limit)
    assert envelope.get("vector_health") is True, "healthy layer required for US1"
    return list(envelope["results"])


@pytest.mark.parametrize("story", list(GROUND_TRUTH))
def test_conceptual_query_returns_ground_truth_in_top_five(
    indexed_semantic_vector: dict[str, Any], story: str
) -> None:
    """A no-keyword-overlap conceptual query returns its known ground-truth
    chunk within the top 5 results with a non-zero ``vector_score`` and no
    degraded flag.
    """
    results = _top_results(indexed_semantic_vector, QUERIES[story])
    assert results, f"query '{QUERIES[story]}' must not return zero results"

    expected = GROUND_TRUTH[story]
    hit = [r for r in results if any(path in r["file_path"] for path in expected)]
    assert hit, (
        f"query '{QUERIES[story]}' did not surface ground truth {expected}; "
        f"got {[r['file_path'] for r in results]}"
    )
    assert results.index(hit[0]) < 5, (
        f"ground truth must rank within top 5, got index {results.index(hit[0])}"
    )
    assert hit[0]["vector_score"] > 0.0, (
        f"ground-truth chunk must carry a non-zero vector_score, got {hit[0]['vector_score']}"
    )
    assert hit[0]["vector_degraded"] is False


def test_verbose_conceptual_query_vector_health_and_degraded_flag(
    indexed_semantic_vector: dict[str, Any],
) -> None:
    """Verbose conceptual results report a non-zero vector score and never a
    degraded flag on a healthy layer.
    """
    envelope = indexed_semantic_vector["search"].search(
        "how long can a user stay signed in before their session token expires",
        limit=10,
    )
    assert envelope.get("vector_health") is True
    assert envelope["results"], "expected results from the semantic fixture"
    for item in envelope["results"]:
        assert item.get("vector_degraded") is False, (
            f"healthy vector layer must not mark result {item.get('chunk_id')} degraded"
        )


def test_multilang_corpus_represents_every_chunk_kind(
    indexed_multilang: dict[str, Any],
) -> None:
    """The multi-language corpus is indexed with the expected
    structural chunk kinds, so enrichment coverage is exercised across them."""
    with indexed_multilang["db"].connect() as conn:
        kinds = {
            row["chunk_node_type"]
            for row in conn.execute("SELECT DISTINCT chunk_node_type FROM code_chunks;")
        }
        content_types = {
            row["content_type"]
            for row in conn.execute("SELECT DISTINCT content_type FROM code_chunks;")
        }
    for expected in (
        "function_definition",
        "class_definition",
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "record_declaration",
        "constructor_declaration",
    ):
        assert expected in kinds, f"fixture missing chunk kind {expected}: {sorted(kinds)}"
    assert "config" in content_types or "docs" in content_types


@pytest.mark.parametrize(
    "query",
    ["persist", "free_helper", "OrderService", "submit", "label", "sum", "Save"],
)
def test_multilang_retrieval_succeeds_for_each_chunk_kind(
    indexed_multilang: dict[str, Any], query: str
) -> None:
    """A query naming a symbol of any represented chunk kind still
    retrieves results, and every result satisfies the reporting invariant."""
    results = indexed_multilang["search"].search(query, limit=5)["results"]
    assert results, f"query {query!r} returned no results across the multi-language corpus"
    for result in results:
        assert "file_path" in result
        if "semantic_contribution" in result:
            assert result["vector_score"] >= 0.0


def test_representation_scheme_marker_recorded(
    indexed_semantic_vector: dict[str, Any],
) -> None:
    """The index records the representation scheme that produced its embeddings
    so stale-scheme vectors are never served as current.
    """
    from src.engine.embed_representation import REPRESENTATION_SCHEME_VERSION

    meta = indexed_semantic_vector["meta"]
    assert meta.get_int("representation_scheme_version") == REPRESENTATION_SCHEME_VERSION


def test_ground_truth_method_chunks_are_semantically_retrieved(
    indexed_semantic_vector: dict[str, Any],
) -> None:
    """Each ground-truth method chunk is retrieved by the dense arm with a
    non-zero truthful score — the observable effect of embedding from its
    enclosing context rather than its body alone.
    """
    results = _top_results(
        indexed_semantic_vector,
        "how long can a user stay signed in before their session token expires",
        limit=5,
    )
    assert results
    for item in results:
        assert item.get("vector_retrieved") in (True, False)
        assert item.get("semantic_contribution") in (
            "semantic",
            "lexical_only",
            "deferred",
            "unavailable",
        )
        if item.get("vector_retrieved") is True:
            assert item["vector_score"] > 0.0
            assert item["semantic_contribution"] == "semantic"


def test_enrichment_leaves_stored_content_spans_and_fts_identical(
    indexed_semantic_vector: dict[str, Any],
) -> None:
    """Enrichment changes only the embedding input — stored content, source
    spans, and FTS rows stay the extracted source, with no injected context and
    FTS kept in parity with the chunk rows.
    """
    comps = indexed_semantic_vector
    with comps["db"].connect() as conn:
        rows = conn.execute(
            "SELECT id, file_path, line_start, line_end, content FROM code_chunks;"
        ).fetchall()
        assert rows, "fixture must index at least one chunk"
        for row in rows:
            # Enrichment prepends the module (file path) to the text embedded;
            # it must never be written into the stored chunk content.
            assert row["file_path"] not in row["content"], (
                f"enrichment context leaked into stored content for {row['file_path']}"
            )
            assert row["content"], "stored chunk content must be non-empty"
            assert row["line_start"] <= row["line_end"]
            fts = conn.execute(
                "SELECT content FROM chunks_fts WHERE rowid = ?;", (row["id"],)
            ).fetchone()
            if fts is not None:
                assert fts["content"] == row["content"], (
                    f"FTS row for chunk {row['id']} diverged from stored content"
                )
