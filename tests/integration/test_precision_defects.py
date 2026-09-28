"""Integration tests for search precision defect fixes.

Runs against the real engine over the synthetic regression fixtures
(``resource_noise``, ``overload_symbols``, ``pattern_queries``) reproduced from
``docs/real-world-test/code-search-vs-grep-report.md``. Each test maps to the
acceptance behavior and its ``pytest -k`` gate.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.mark.integration
class TestUS1Resource:
    """Java-first results, no resource/boilerplate pollution."""

    def test_java_query_surfaces_java_over_resource(
        self, indexed_resource_noise: dict[str, Any]
    ) -> None:
        """A Java concept query ranks the AST chunk above any resource chunk."""
        results = indexed_resource_noise["search"].search("removeFavorite", limit=5)["results"]
        assert results, "query should surface results"
        top = results[0]
        assert top["chunk_type"] == "ast", f"resource chunk must not outrank Java, got {top}"
        assert "Article.java" in top["file_path"]

    def test_no_resource_in_top3_for_slug_query(
        self, indexed_resource_noise: dict[str, Any]
    ) -> None:
        """'create a slug from the article title' surfaces Java service in top."""
        results = indexed_resource_noise["search"].search("createSlug", limit=5)["results"]
        top = results[0]
        assert "ArticleService.java" in top["file_path"], str(top)

    def test_boilerplate_does_not_outrank_relevant_ast(
        self, indexed_resource_noise: dict[str, Any]
    ) -> None:
        """A tiny field_declaration chunk never outranks the relevant method."""
        results = indexed_resource_noise["search"].search("slugify", limit=5)["results"]
        relevant = [r for r in results if r["chunk_node_type"] != "field_declaration"]
        assert relevant, "at least one non-boilerplate result expected"
        assert relevant[0]["score"] >= results[0]["score"]

    def test_resource_intent_still_ranks_sql(self, indexed_resource_noise: dict[str, Any]) -> None:
        """A resource-intent query still surfaces the SQL file."""
        results = indexed_resource_noise["search"].search("migration", limit=5)["results"]
        assert results, "resource-intent query must return results"
        assert any("afterMigrate.sql" in r["file_path"] for r in results)


@pytest.mark.integration
class TestUS2Overload:
    """Signature-aware overload resolution."""

    def test_signature_resolves_2arg_overload(
        self, indexed_overload_symbols: dict[str, Any]
    ) -> None:
        envelope = indexed_overload_symbols["symbol_store"].resolve_name(
            "TokenService.generateToken(Map<String,Object>,String)"
        )
        assert envelope["kind"] == "exact", envelope
        assert envelope["symbol"]["signature"]["arity"] == 2, envelope["symbol"]["signature"]

    def test_formatting_variant_matches(self, indexed_overload_symbols: dict[str, Any]) -> None:
        envelope = indexed_overload_symbols["symbol_store"].resolve_name(
            "TokenService.generateToken(Map<String, Object>, String)"
        )
        assert envelope["kind"] == "exact", envelope
        assert envelope["symbol"]["signature"]["param_types"] == ["Map", "String"]

    def test_bare_overloaded_name_ambiguous(self, indexed_overload_symbols: dict[str, Any]) -> None:
        envelope = indexed_overload_symbols["symbol_store"].resolve_name("generateToken")
        assert envelope["kind"] == "ambiguous", envelope
        arities = {c["signature"]["arity"] for c in envelope["candidates"]}
        assert arities == {1, 2}, envelope["candidates"]


@pytest.mark.integration
class TestCallGraph:
    """Receiver-keyed, signature-carrying call edges."""

    @pytest.fixture
    def save_3arg(self, indexed_overload_symbols: dict[str, Any]) -> int:
        with indexed_overload_symbols["db"].connect() as conn:
            row = conn.execute(
                "SELECT id FROM symbols WHERE name = 'save' "
                "AND file_path LIKE '%ArticleService%' "
                "AND conventional_fqn LIKE '%(Article,Profile,%';"
            ).fetchone()
            assert row is not None
            return int(row["id"])

    def test_call_graph_callers_carry_target_signature_and_overloads(
        self, indexed_overload_symbols: dict[str, Any], save_3arg: int
    ) -> None:
        graph = indexed_overload_symbols["edge_store"].get_call_graph(
            save_3arg, direction="callers", max_depth=1
        )
        callers = graph["callers"]
        assert callers, "3-arg ArticleService.save must have callers"
        for c in callers:
            assert c.get("target_signature") is not None, c
            assert isinstance(c.get("overloads"), list) and c["overloads"], c

    def test_call_graph_controller_is_a_caller(
        self, indexed_overload_symbols: dict[str, Any], save_3arg: int
    ) -> None:
        graph = indexed_overload_symbols["edge_store"].get_call_graph(
            save_3arg, direction="callers", max_depth=1
        )
        paths = [c.get("file_path", "") for c in graph["callers"]]
        assert any("ArticleController.java" in p for p in paths), paths

    def test_call_graph_unknown_receiver_same_name_produces_no_wrong_edge(
        self, indexed_overload_symbols: dict[str, Any], save_3arg: int
    ) -> None:
        """repository.save must never appear as a caller of ArticleService.save.

        ``ArticleService.profileFavorited`` calls ``repository.save`` on a
        different receiver; that must NOT be attributed as a caller of the
        service's own 3-arg save. The real callers are the controller methods
        and the test, not a ``repository`` call site.
        """
        graph = indexed_overload_symbols["edge_store"].get_call_graph(
            save_3arg, direction="callers", max_depth=1
        )
        fqns = [c.get("fqn", "") for c in graph["callers"]]
        for fqn in fqns:
            assert "profileFavorited" not in fqn and "profileUnfavorited" not in fqn, fqn


@pytest.mark.integration
class TestUS4Negative:
    """Negative lookups return clean not_found, never crash."""

    def test_nonexistent_service_not_found(self, indexed_overload_symbols: dict[str, Any]) -> None:
        envelope = indexed_overload_symbols["symbol_store"].resolve_name(
            "NonexistentService.fooBar"
        )
        assert envelope["symbol"] is None
        assert envelope["kind"] in ("not_found", "suggestion", "ambiguous")

    def test_malformed_never_crashes(self, indexed_overload_symbols: dict[str, Any]) -> None:
        envelope = indexed_overload_symbols["symbol_store"].resolve_name("Not.A.(Symbol")
        assert envelope["symbol"] is None or envelope["kind"] == "not_found"

    def test_empty_never_crashes(self, indexed_overload_symbols: dict[str, Any]) -> None:
        envelope = indexed_overload_symbols["symbol_store"].resolve_name("")
        assert envelope is not None


@pytest.mark.integration
class TestUS5Pattern:
    """Annotation/literal queries return exact matches."""

    def test_transactional_readonly_returns_occurrences(
        self, indexed_pattern_queries: dict[str, Any]
    ) -> None:
        results = indexed_pattern_queries["search"].search(
            "@Transactional readOnly = true", limit=10
        )["results"]
        assert len(results) >= 1, "annotation query must return exact occurrences"

    def test_exception_handler_enumerates_handlers(
        self, indexed_pattern_queries: dict[str, Any]
    ) -> None:
        results = indexed_pattern_queries["search"].search("@ExceptionHandler", limit=10)["results"]
        assert results
        assert any("GlobalExceptionHandler" in r["file_path"] for r in results)

    def test_settoken_surfaces_definition(self, indexed_pattern_queries: dict[str, Any]) -> None:
        results = indexed_pattern_queries["search"].search("setToken", limit=10)["results"]
        assert results
        assert any("TokenHolder" in r["file_path"] for r in results)

    def test_prose_with_symbol_does_not_misfire(
        self, indexed_pattern_queries: dict[str, Any]
    ) -> None:
        results = indexed_pattern_queries["search"].search("token", limit=10)["results"]
        assert isinstance(results, list)


@pytest.mark.integration
class TestUS6Explainable:
    """Score_sources present, no silent zero-vector."""

    def test_score_sources_on_every_result(self, indexed_pattern_queries: dict[str, Any]) -> None:
        results = indexed_pattern_queries["search"].search("setToken", limit=10)["results"]
        assert results
        for r in results:
            ss = r.get("score_sources", {})
            assert {"bm25", "vector", "fused", "weights", "reranked"} <= set(ss), ss
            assert {"code", "boilerplate", "resource"} <= set(ss["weights"]), ss

    def test_vector_headings_present_when_relevant(
        self, indexed_pattern_queries: dict[str, Any]
    ) -> None:
        results = indexed_pattern_queries["search"].search("password", limit=10)["results"]
        if results:
            assert all("vector" in r["score_sources"] for r in results)

    def test_semantic_contribution_fields_are_additive(
        self, indexed_pattern_queries: dict[str, Any]
    ) -> None:
        """The additive ``vector_retrieved`` / ``semantic_contribution``
        fields are present on every result, the existing fields and
        ``score_sources`` keys are unchanged, and a zero ``vector_score`` is
        always explained by a non-``semantic`` contribution."""
        results = indexed_pattern_queries["search"].search("setToken", limit=10)["results"]
        assert results
        allowed = {"semantic", "lexical_only", "deferred", "unavailable"}
        for r in results:
            assert isinstance(r["vector_retrieved"], bool)
            assert r["semantic_contribution"] in allowed
            if not r["vector_retrieved"]:
                assert r["vector_score"] == 0.0
            assert {"bm25", "vector", "fused", "weights", "reranked"} <= set(r["score_sources"])


@pytest.mark.integration
class TestUS7Envelope:
    """Search results carry total_matches/truncated."""

    def test_truncated_query_reports_total(self, indexed_pattern_queries: dict[str, Any]) -> None:
        envelope = indexed_pattern_queries["search"].search(
            "@Transactional readOnly = true", limit=5
        )
        assert envelope["total_matches"] > len(envelope["results"])
        assert envelope["truncated"] is True

    def test_uncapped_query_reports_total(self, indexed_pattern_queries: dict[str, Any]) -> None:
        envelope = indexed_pattern_queries["search"].search("setToken", limit=100)
        assert envelope["total_matches"] >= len(envelope["results"])
        assert envelope["truncated"] == (envelope["total_matches"] > len(envelope["results"]))


@pytest.mark.integration
class TestUS4ProductionNotDominatedByTests:
    """Production code outranks test code for production queries."""

    FAVORITE_QUERY = "what happens when a user favorites an article"
    FAVORITE_MAIN = "favorite/FavoritesTracker.java"
    FAVORITE_TEST = "favorite/FavoritesTrackerTest.java"

    def test_favorite_query_ranks_production_top3_no_test_outranks(
        self, indexed_semantic_vector: dict[str, Any]
    ) -> None:
        """The favorite conceptual query ranks the known production
        code in the top 3 with no test method outranking it.
        """
        results = indexed_semantic_vector["search"].search(self.FAVORITE_QUERY, limit=5)["results"]
        assert results, "favorite query must not return zero results"
        top3 = results[:3]
        assert any(self.FAVORITE_MAIN in r["file_path"] for r in top3), [
            r["file_path"] for r in top3
        ]
        prod_rank = min(i for i, r in enumerate(results) if self.FAVORITE_MAIN in r["file_path"])
        for r in results:
            if r["is_test_file"]:
                assert (
                    r["file_path"].count(self.FAVORITE_TEST) == 0 or results.index(r) > prod_rank
                ), (
                    f"test method must not outrank production, got "
                    f"{[r['file_path'] for r in results]}"
                )

    def test_favorite_query_production_only_setting_reproduces_top_answer(
        self, indexed_semantic_vector: dict[str, Any]
    ) -> None:
        """The production-only setting (``--include-test-files=false``)
        reproduces the same top answer as the default run's production rank.
        """
        default_top = indexed_semantic_vector["search"].search(
            self.FAVORITE_QUERY, limit=5, include_tests=True
        )["results"]
        production_only = indexed_semantic_vector["search"].search(
            self.FAVORITE_QUERY, limit=5, include_tests=False
        )["results"]
        assert production_only, "production-only run must return results"
        assert all(not r["is_test_file"] for r in production_only)
        default_prod = [r for r in default_top if not r["is_test_file"]]
        assert default_prod, "default run must contain production results"
        assert default_prod[0]["chunk_id"] == production_only[0]["chunk_id"], (
            "production-only top answer must match the default run's top production "
            f"answer, got {production_only[0]['file_path']} vs {default_prod[0]['file_path']}"
        )
