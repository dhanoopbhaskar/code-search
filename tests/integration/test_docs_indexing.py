"""Integration tests that markdown/prose is indexed as ``docs`` chunks by
default and docs-scoped search returns only doc chunks.

Runs against the real ``HybridSearch.search`` path over the ``transparency``
fixture (two ``.md`` files) and the ``transparency_empty`` variant (no
markdown).
"""

from __future__ import annotations

from typing import Any

from src.engine.redactor import Redactor

DOCS_SCENT_QUERY = "how do I deploy"
DOCS_SCOPE = "docs"


class TestProseIndexing:
    def test_prose_indexed_as_docs_by_default(self, indexed_transparency: dict[str, Any]) -> None:
        """Markdown files are indexed as ``content_type: docs`` chunks."""
        db = indexed_transparency["db"]
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT file_path, content_type FROM code_chunks "
                "WHERE file_path LIKE '%.md' ORDER BY file_path;"
            ).fetchall()
        assert len(rows) >= 1, "No prose chunks indexed"
        for row in rows:
            assert row["content_type"] == "docs"

    def test_docs_scope_returns_only_doc_chunks(self, indexed_transparency: dict[str, Any]) -> None:
        """A ``content: docs`` scope returns only doc chunks and every prose
        file whose content answers the query."""
        envelope = indexed_transparency["search"].search(DOCS_SCENT_QUERY, content=DOCS_SCOPE)
        assert envelope["content"] == DOCS_SCOPE
        assert envelope["total_matches"] >= 1
        for result in envelope["results"]:
            assert result["content_type"] == "docs"
        answer_paths = {r["file_path"] for r in envelope["results"]}
        assert any(p.endswith("DEPLOYMENT.md") for p in answer_paths)


class TestDocsQuerying:
    def test_how_do_i_question_returns_answering_prose_file(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """A "how do I" question returns the answering prose file in docs
        mode."""
        envelope = indexed_transparency["search"].search(
            "how do I run the dev server", content=DOCS_SCOPE
        )
        assert envelope["total_matches"] >= 1
        assert any(r["file_path"].endswith("README.md") for r in envelope["results"])

    def test_code_query_does_not_let_docs_compete_with_code(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """For a code-language query the top-ranked results are code chunks,
        not docs."""
        envelope = indexed_transparency["search"].search("repository save article", content="all")
        assert envelope["total_matches"] >= 1
        assert any(r["content_type"] == "code" for r in envelope["results"][:5])
        for result in envelope["results"][:5]:
            if result["content_type"] == "docs":
                assert result["score"] < envelope["results"][0]["score"]


class TestDocsScopeEdgeCase:
    def test_docs_scope_without_markdown_returns_explicit_no_match(
        self, indexed_transparency_empty: dict[str, Any]
    ) -> None:
        """A docs-scoped query against a corpus with no markdown returns an
        explicit no-match explanation, never a bare empty set or a silent
        fallback to code."""
        envelope = indexed_transparency_empty["search"].search(DOCS_SCENT_QUERY, content=DOCS_SCOPE)
        assert envelope["content"] == DOCS_SCOPE
        assert envelope["total_matches"] == 0
        assert "no_match" in envelope["explanation"]["reason"]
        assert not any(r.get("content_type") == "code" for r in envelope["results"])


class TestDocsRedaction:
    def test_inline_secret_in_docs_snippet_is_redacted(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """An inline secret in a returned docs snippet is redacted."""
        envelope = indexed_transparency["search"].search("JWT signing key", content=DOCS_SCOPE)
        assert envelope["total_matches"] >= 1
        redacted = Redactor().redact_results(envelope["results"])
        for result in redacted:
            assert "super-secret-jwt-signing-key" not in result["content"]
