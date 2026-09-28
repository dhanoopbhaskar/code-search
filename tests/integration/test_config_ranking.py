"""Integration tests for config and resource content
ranking for config questions.

Runs against the real ``HybridSearch.search`` path over the synthetic
``transparency`` fixture (an ``application-dev.properties`` config chunk plus
docs and code). Written FIRST — expect FAIL until the type-aware
config-scent ranking and the content-type filter are
implemented.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.engine.redactor import Redactor

CONFIG_SCENT_QUERY = "database connection pool settings"


class TestConfigRanking:
    def test_config_chunk_ranks_top5_in_all_mode(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """The fixture's ``application-dev.properties`` config chunk
        ranks within the top 5 for a config-scent query in ``all`` mode."""
        results = indexed_transparency["search"].search(CONFIG_SCENT_QUERY, limit=10)["results"]
        assert len(results) >= 1
        assert any(
            r["file_path"].endswith("application-dev.properties") and r["content_type"] == "config"
            for r in results[:5]
        )

    def test_config_scent_query_returns_config_content_type(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        results = indexed_transparency["search"].search(CONFIG_SCENT_QUERY, limit=10)["results"]
        assert any(r.get("content_type") == "config" for r in results)


class TestContentFilter:
    def test_content_config_returns_only_config_chunks(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """A ``content: config`` scope returns only config chunks."""
        envelope = indexed_transparency["search"].search(
            CONFIG_SCENT_QUERY, limit=10, content="config"
        )
        assert envelope["content"] == "config"
        results = envelope["results"]
        assert len(results) >= 1
        assert all(r["content_type"] == "config" for r in results)

    def test_content_code_excludes_config_below_code(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """A ``content: code`` scope returns only code chunks."""
        envelope = indexed_transparency["search"].search(
            CONFIG_SCENT_QUERY, limit=10, content="code"
        )
        assert envelope["content"] == "code"
        results = envelope["results"]
        assert all(r["content_type"] == "code" for r in results)

    def test_content_filter_default_is_code_focused(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """The default ranked scope is code-focused (docs
        excluded), not ``all``."""
        envelope = indexed_transparency["search"].search(CONFIG_SCENT_QUERY, limit=10)
        assert envelope["content"] == "code_focused"
        assert all(r.get("content_type") != "docs" for r in envelope["results"])

    def test_exhaustive_mode_obeys_content_filter(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """The content filter also scopes exhaustive mode."""
        envelope = indexed_transparency["search"].search(
            "pool", limit=10, mode="exhaustive", content="config"
        )
        assert envelope["content"] == "config"
        items = envelope.get("matches") or envelope.get("results") or []
        assert all(item.get("file_path", "").endswith(".properties") for item in items)


class TestCodeLanguageContext:
    def test_config_answer_surfaces_top10_with_code_language_context(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """Under an active code-language context a config-scent
        query still surfaces the config answer within the top 10. The explicit
        ``language`` argument is a hard filter, so the reconciliation is
        asserted at the weight-composition level (config-scent boost overrides
        the code-context demotion; the answer remains reachable and ranked
        below code but above docs) plus the unfiltered top-10 reachability."""
        weights = indexed_transparency["search"]._content_weights(
            config_scent=True, code_context=True
        )
        assert weights["code"] == 1.0
        assert weights["docs"] < 1.0
        assert weights["config"] < 1.0
        assert weights["config"] > weights["docs"]
        results = indexed_transparency["search"].search(CONFIG_SCENT_QUERY, limit=10)["results"]
        assert len(results) >= 1
        assert any(
            r["file_path"].endswith("application-dev.properties") and r["content_type"] == "config"
            for r in results[:10]
        )


class TestSecretRedaction:
    def test_inline_secret_in_config_snippet_is_redacted(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """An inline secret in a returned config snippet is
        redacted by the shared secret redactor."""
        envelope = indexed_transparency["search"].search(
            CONFIG_SCENT_QUERY, limit=10, content="config"
        )
        config_results = [r for r in envelope["results"] if r["content_type"] == "config"]
        assert config_results
        redacted = Redactor().redact_results(config_results)
        for result in redacted:
            assert "super-secret-jwt-signing-key" not in result["content"]
            if result["redacted_count"] > 0:
                assert "[REDACTED]" in result["content"]


class TestUS4ConfigRanking:
    """Type-aware config ranking over the ``relevance`` fixture."""

    def test_config_scent_query_ranks_properties_above_build_noise(
        self, indexed_relevance: dict[str, Any]
    ) -> None:
        """A config-scent query ranks the relevant
        ``.properties`` resource in the top 10 with no irrelevant
        ``pom.xml``/``package-lock.json`` outranking it."""
        envelope = indexed_relevance["search"].search("server port", limit=10)
        results = envelope["results"]
        assert results
        top10 = [Path(r["file_path"]).name for r in results[:10]]
        props_rank = next((i for i, n in enumerate(top10) if n == "application.properties"), None)
        assert props_rank is not None, f"application.properties missing from top 10: {top10}"
        for noise in ("pom.xml", "package-lock.json"):
            noise_rank = next((i for i, n in enumerate(top10) if n == noise), None)
            if noise_rank is not None:
                assert props_rank < noise_rank, f"{noise} outranks the config answer ({top10})"

    def test_concrete_config_query_preserved(self, indexed_relevance: dict[str, Any]) -> None:
        """A concrete config query ("mysql database connection")
        preserves current behavior — the datasource properties rank."""
        envelope = indexed_relevance["search"].search("mysql database connection", limit=10)
        results = envelope["results"]
        assert results
        top10 = [Path(r["file_path"]).name for r in results[:10]]
        assert "application.properties" in top10, f"config answer missing: {top10}"

    def test_on_topic_build_file_query_still_ranks_pom(
        self, indexed_relevance: dict[str, Any]
    ) -> None:
        """An on-topic build-file query still ranks the
        ``pom.xml`` — the resource-intent gate is a demotion of irrelevant
        build noise, never a hard exclusion."""
        envelope = indexed_relevance["search"].search(
            "which dependency provides the web starter", limit=10
        )
        results = envelope["results"]
        assert results
        top10 = [Path(r["file_path"]).name for r in results[:10]]
        assert "pom.xml" in top10, f"on-topic pom.xml suppressed: {top10}"
