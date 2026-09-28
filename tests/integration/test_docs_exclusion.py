"""Integration tests that docs never pollute code-focused results and that
``file_role`` is honest.

Runs against the ``relevance`` fixture (prose in ``docs/``, a self-referential
report artifact in ``reports/``, config + DDL resources, and Spring-style
article code). The default ranked scope is code-focused, so a prose-scent
query returns no docs chunk unless an explicit ``docs`` scope is requested,
and every prose chunk reports ``file_role: docs`` consistent with its
``content_type: docs``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

PROSE_QUERY = "how do comments get created"
CODE_QUERY = "save an article comment"
GT_DOC = Path("docs") / "README.md"


def _names(results: list[dict[str, Any]]) -> set[str]:
    return {Path(r["file_path"]).name for r in results}


class TestDocsExclusion:
    def test_default_ranked_scope_excludes_docs(self, indexed_relevance: dict[str, Any]) -> None:
        """The default ranked scope is code-focused — no prose chunk appears
        in the default results for a prose-scent query."""
        envelope = indexed_relevance["search"].search(PROSE_QUERY, limit=10)
        assert envelope["content"] == "code_focused"
        results = envelope["results"]
        assert results, "the fixture must produce ranked results"
        assert all(r["content_type"] != "docs" for r in results), (
            "a docs chunk leaked into the code-focused default results"
        )

    def test_docs_scope_returns_prose(self, indexed_relevance: dict[str, Any]) -> None:
        """``content: docs`` re-opens the docs pool and the prose-scent query
        surfaces the answering markdown."""
        envelope = indexed_relevance["search"].search(PROSE_QUERY, limit=10, content="docs")
        assert envelope["content"] == "docs"
        results = envelope["results"]
        assert results, "docs-scoped query returned no prose"
        assert all(r["content_type"] == "docs" for r in results)
        assert GT_DOC.name in _names(results), "the answering README must rank in docs scope"

    def test_file_role_docs_agrees_with_content_type(
        self, indexed_relevance: dict[str, Any]
    ) -> None:
        """Every prose chunk reports ``file_role: docs`` consistent with
        ``content_type: docs`` — a filter on either field drops it. The report
        artifact (``reports/``) is the intentional exception, tagged
        ``analysis`` for within-docs demotion."""
        envelope = indexed_relevance["search"].search(PROSE_QUERY, limit=10, content="docs")
        for r in envelope["results"]:
            assert r["content_type"] == "docs"
            if r["file_role"] == "analysis":
                continue
            assert r["file_role"] == "docs", (
                f"prose chunk {r['file_path']} reported file_role {r['file_role']!r}"
            )
        prose_roles = {r["file_role"] for r in envelope["results"]}
        assert "docs" in prose_roles, "a plain prose chunk must report file_role docs"

    def test_code_scope_never_returns_docs(self, indexed_relevance: dict[str, Any]) -> None:
        """``content: code`` returns only code chunks — never a docs chunk,
        even for the prose-scent query."""
        envelope = indexed_relevance["search"].search(PROSE_QUERY, limit=10, content="code")
        assert envelope["content"] == "code"
        for r in envelope["results"]:
            assert r["content_type"] == "code", (
                f"code-scoped result carried content_type {r['content_type']}: {r['file_path']}"
            )

    def test_explicit_all_scope_restores_docs(self, indexed_relevance: dict[str, Any]) -> None:
        """``content: all`` is the explicit opt-in that includes docs."""
        envelope = indexed_relevance["search"].search(PROSE_QUERY, limit=10, content="all")
        assert envelope["content"] == "all"
        assert any(r["content_type"] == "docs" for r in envelope["results"]), (
            "all-scoped query should surface prose for a prose-scent query"
        )

    def test_code_query_defaults_never_include_docs(
        self, indexed_relevance: dict[str, Any]
    ) -> None:
        """A code-scent query in the default scope returns code/config, never
        docs."""
        envelope = indexed_relevance["search"].search(CODE_QUERY, limit=10)
        for r in envelope["results"]:
            assert r["content_type"] != "docs"
