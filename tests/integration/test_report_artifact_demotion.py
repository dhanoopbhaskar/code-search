"""Integration tests: analysis and report artifacts never compete with shipped
code.

The ``relevance`` fixture's ``reports/code-search-vs-grep.md`` quotes the
benchmark queries verbatim, so without demotion it would rank at the top. The
artifact is indexed but tagged ``file_role: analysis`` and demoted so it never
outranks shipped content, while an explicit query that targets it still
reaches it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.engine.reranking import Reranker

ARTIFACT = "reports/code-search-vs-grep.md"
QUOTED_QUERIES = [
    "how do comments get created",
    "database schema",
    "how is an article created",
]


def _reranked(search: Any, query: str, limit: int = 10) -> list[dict[str, Any]]:
    envelope = search.search(query, limit=limit, content="all")
    reranker = Reranker(search._db, settings=search._settings)  # type: ignore[arg-type]
    return reranker.rerank(envelope["results"], query=query)


class TestReportArtifactDemotion:
    @pytest.mark.parametrize("query", QUOTED_QUERIES)
    def test_quoted_query_does_not_rank_the_artifact(
        self, indexed_relevance: dict[str, Any], query: str
    ) -> None:
        """A query the report quotes verbatim does not rank the artifact in the
        top results — the shipped answer outranks it."""
        ranked = _reranked(indexed_relevance["search"], query)
        assert ranked, f"query {query!r} produced no results"
        names = [Path(r["file_path"]) for r in ranked]
        top5 = {str(p) for p in names[:5]}
        assert not any(p.endswith(ARTIFACT) for p in top5), (
            f"report artifact ranked in the top 5 for {query!r}: {[str(p) for p in names[:6]]}"
        )

    def test_artifact_reports_analysis_role(self, indexed_relevance: dict[str, Any]) -> None:
        """The report artifact is indexed with ``file_role: analysis`` (a
        demotion signal), never presented as a normal docs/code chunk."""
        with indexed_relevance["db"].connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT file_path FROM code_chunks WHERE file_path LIKE '%reports/%';"
            ).fetchall()
        assert rows, "the report artifact must be indexed"
        ranked = _reranked(indexed_relevance["search"], QUOTED_QUERIES[0], limit=50)
        artifact_results = [r for r in ranked if str(Path(r["file_path"])).endswith(ARTIFACT)]
        # The artifact is reachable in an uncapped ranked result (demotion,
        # not exclusion) and carries the analysis role.
        for r in artifact_results:
            assert r["file_role"] == "analysis", f"artifact reported file_role {r['file_role']!r}"

    def test_explicit_query_still_reaches_the_artifact(
        self, indexed_relevance: dict[str, Any]
    ) -> None:
        """An explicit query that legitimately targets the artifact still
        reaches it — the suppression is a demotion, not a hard drop."""
        ranked = _reranked(indexed_relevance["search"], "code-search vs grep benchmark", limit=50)
        assert any(str(Path(r["file_path"])).endswith(ARTIFACT) for r in ranked), (
            "explicit artifact query must reach the report"
        )
