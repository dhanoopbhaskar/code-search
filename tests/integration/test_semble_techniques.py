"""Integration tests for the adopted Semble search-quality techniques.

Runs against the real engine over the synthetic regression fixtures
(``stem_rescue``, ``boilerplate_merge``, ``path_penalty``, ``prose_symbols``).
Each behavior maps to its ``pytest -k`` gate:

- file-stem non-candidate rescue (definition in top-5, tier evidence).
- leaf-boilerplate merging (no bare fragment results).
- NL file-stem/parent-dir path boost (additive, byte-identical no-op).
- embedded-symbol detection in prose (exact-resolution gate).
- stub/barrel/example demotion via path-class penalties.

The fixtures disable the relevance gate (see ``tests/conftest.py``) so the tiny
synthetic corpora return the query-time evidence each story asserts; the gate
itself is covered by existing suites.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.engine.redactor import air_gap_enforcement
from src.engine.reranking import Reranker


def _top_results(comps: dict[str, Any], query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return the real search results for *query* over an indexed fixture."""
    envelope = comps["search"].search(query, limit=limit)
    return list(envelope["results"])


def _reranked(comps: dict[str, Any], query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Run *query* through the real engine and the production reranker."""
    raw = comps["search"].search(query, limit=limit)["results"]
    reranker = Reranker(comps["db"], comps["session_db"], comps["settings"])
    return reranker.rerank(raw)


@pytest.mark.integration
class TestUS1StemRescue:
    """Symbol lookups surface the defining file via its file name."""

    def test_us1_definition_in_top5_with_stem_match(
        self, indexed_stem_rescue: dict[str, Any]
    ) -> None:
        results = _top_results(indexed_stem_rescue, "StateManager", limit=5)
        assert results, "query must surface results"
        state = [r for r in results if r["file_path"].endswith("state.ts")]
        assert state, "state.ts definition must be rescued into the top-5"
        assert state[0]["is_definition"] is True, "the rescued chunk must be the definition"
        assert state[0]["score_sources"]["rescue"] == {
            "tier": "stem_match",
            "boost": 1.5,
        }, state[0]["score_sources"]

    def test_us1_stem_related_tier(self, indexed_stem_rescue: dict[str, Any]) -> None:
        results = _top_results(indexed_stem_rescue, "StateManager", limit=5)
        related = [r for r in results if r["file_path"].endswith("state-machine.ts")]
        assert related, "state-machine.ts must surface via the stem_related tier"
        assert related[0]["score_sources"]["rescue"] == {
            "tier": "stem_related",
            "boost": 1.0,
        }

    def test_us1_no_rescue_for_name_sharing_non_definition(
        self, indexed_stem_rescue: dict[str, Any]
    ) -> None:
        """order.py shares the ``order`` name but defines no ``Order``.

        A plain lexical hit is fine; the rescue must never inject the file.
        """
        results = _top_results(indexed_stem_rescue, "Order", limit=5)
        order = [r for r in results if r["file_path"].endswith("order.py")]
        for r in order:
            assert r["score_sources"]["rescue"] is None, (
                "the name-sharing non-defining file must never be rescued"
            )

    def test_us1_multi_file_deterministic(self, indexed_stem_rescue: dict[str, Any]) -> None:
        first = _top_results(indexed_stem_rescue, "StateManager", limit=5)
        second = _top_results(indexed_stem_rescue, "StateManager", limit=5)
        paths = [r["file_path"] for r in first]
        assert [r["file_path"] for r in second] == paths, "ordering must be deterministic"
        assert any(p.endswith("state.ts") for p in paths)
        assert any(p.endswith("state-machine.ts") for p in paths)

    def test_us1_rescue_makes_no_outbound_calls(self, indexed_stem_rescue: dict[str, Any]) -> None:
        """The stem-rescue path issues zero outbound network calls."""
        with air_gap_enforcement():
            results = _top_results(indexed_stem_rescue, "StateManager", limit=5)
        assert any(r["file_path"].endswith("state.ts") for r in results)


@pytest.mark.integration
class TestUS2BoilerplateMerge:
    """Leaf boilerplate merges into whole regions; no bare fragments."""

    def test_us2_no_fragment_in_top5_for_code_logic_query(
        self, indexed_boilerplate_merge: dict[str, Any]
    ) -> None:
        results = _top_results(indexed_boilerplate_merge, "user id field", limit=5)
        assert results, "code-logic query must surface the merged regions"
        fragment_types = {
            "field_declaration",
            "import_statement",
            "comment",
            "type_alias",
            "module_expression",
            "expression_statement",
            "variable_declaration",
        }
        for r in results:
            assert r["chunk_node_type"] not in fragment_types, (
                f"bare fragment surfaced: {r['chunk_node_type']} in {r['file_path']}"
            )

    def test_us2_definition_remains_resolvable(
        self, indexed_boilerplate_merge: dict[str, Any]
    ) -> None:
        results = _top_results(indexed_boilerplate_merge, "UserProfile", limit=5)
        assert results, "definition query must surface results"
        assert any(r["is_definition"] and r["fqn"].endswith("UserProfile") for r in results), (
            "the UserProfile definition anchor must remain its own is_definition chunk"
        )

    def test_us3_no_expression_fragments_in_results(
        self, indexed_boilerplate_merge: dict[str, Any]
    ) -> None:
        results = _top_results(indexed_boilerplate_merge, "refresh cache build", limit=10)
        assert results, "expression query must surface results"
        for r in results:
            assert r["chunk_node_type"] not in {"expression_statement", "variable_declaration"}, (
                f"bare expression fragment surfaced: {r['chunk_node_type']} in {r['file_path']}"
            )

    def test_us3_expression_method_stays_definition_anchor(
        self, indexed_boilerplate_merge: dict[str, Any]
    ) -> None:
        results = _top_results(indexed_boilerplate_merge, "refresh cache build", limit=10)
        assert any(r["is_definition"] and r["fqn"].endswith("refresh") for r in results), (
            "the refresh() method must surface as its own is_definition anchor"
        )

    def test_us3_notes_txt_indexes_as_whole_region(
        self, indexed_boilerplate_merge: dict[str, Any]
    ) -> None:
        results = indexed_boilerplate_merge["search"].search(
            "user profile domain model", limit=10, content="all"
        )["results"]
        assert results, "grammar-less query must surface results"
        notes = [r for r in results if r["file_path"].endswith("notes.txt")]
        assert notes, "notes.txt must be indexed as a whole-region chunk"
        assert notes[0]["chunk_node_type"] == "module", notes[0]
        assert notes[0]["is_definition"] is False


@pytest.mark.integration
class TestUS4PathBoost:
    """Topic queries surface files whose names match the topic."""

    def test_us4_path_matching_file_in_top5_with_boost(
        self, indexed_path_penalty: dict[str, Any]
    ) -> None:
        results = _top_results(indexed_path_penalty, "how is authentication handled", limit=5)
        assert results, "query must surface results"
        boosted = [r for r in results if r["score_sources"]["path_boost"] is not None]
        assert boosted, "at least one path-matching file must be boosted"
        assert any(
            r["file_path"].endswith("auth_service.py")
            or r["file_path"].endswith("auth_middleware.py")
            for r in results
        ), "an auth file must appear in the top-5"

    def test_us4_no_match_ordering_unchanged(self, indexed_path_penalty: dict[str, Any]) -> None:
        """A query with no path-matching keyword is byte-identical."""
        results = _top_results(indexed_path_penalty, "session timeout handling", limit=5)
        assert results, "query must surface results"
        for r in results:
            assert r["score_sources"]["path_boost"] is None, (
                "no keyword match means a zero boost on every chunk"
            )
        second = _top_results(indexed_path_penalty, "session timeout handling", limit=5)
        assert [r["file_path"] for r in second] == [r["file_path"] for r in results]


@pytest.mark.integration
class TestUS5EmbeddedSymbol:
    """Prose that names a symbol still finds its definition."""

    def test_us5_embedded_definition_surfaces(self, indexed_prose_symbols: dict[str, Any]) -> None:
        results = _top_results(
            indexed_prose_symbols,
            "where is the StateManager defined and how do I use it",
            limit=5,
        )
        assert results, "prose query must surface results"
        state = [r for r in results if r["file_path"].endswith("state.ts")]
        assert state, "the prose-named definition must surface via its file name"
        score_sources = state[0]["score_sources"]
        assert score_sources["embedded_symbol"] is not None, score_sources
        assert score_sources["embedded_symbol"]["symbol"] == "StateManager"
        assert score_sources["rescue"] == {"tier": "stem_match", "boost": 1.5}, score_sources

    def test_us5_prefix_similar_prose_does_not_fire(
        self, indexed_prose_symbols: dict[str, Any]
    ) -> None:
        """'statemanager' (lowercase, no exact symbol) must not fire."""
        results = _top_results(indexed_prose_symbols, "how do I use statemanager here", limit=5)
        assert results, "prefix-similar prose still returns ordinary results"
        for r in results:
            assert r["score_sources"]["embedded_symbol"] is None, r["score_sources"]
            assert r["score_sources"]["rescue"] is None, r["score_sources"]


@pytest.mark.integration
class TestUS6PathPenalties:
    """Stubs, barrels, and examples rank below real implementations."""

    def test_us6_real_impl_outranks_stub_barrel_example(
        self, indexed_path_penalty: dict[str, Any]
    ) -> None:
        reranked = _reranked(indexed_path_penalty, "how is the authentication filter implemented")
        assert reranked, "query must surface results"
        real = [
            r
            for r in reranked
            if r["file_path"].endswith(("auth_service.py", "auth_middleware.py"))
        ]
        assert real, "real implementations must be present"
        demoted = [
            r
            for r in reranked
            if r["file_path"].endswith(("foo.d.ts", "__init__.py", "package-info.java"))
            or "/examples/" in r["file_path"]
            or "/legacy/" in r["file_path"]
            or "/compat/" in r["file_path"]
        ]
        assert demoted, "the stub/barrel/example corpus must be indexed"
        top_real = max(r["score"] for r in real)
        for r in demoted:
            assert r["score"] < top_real, (
                f"{r['file_path']} must rank below the real implementations"
            )

    def test_us6_export_intent_reaches_barrel(self, indexed_path_penalty: dict[str, Any]) -> None:
        """Demotion is a preference, never an exclusion."""
        reranked = _reranked(indexed_path_penalty, "what does this module export")
        assert reranked, "export-intent query must surface the barrel"
        assert any(
            r["file_path"].endswith(("__init__.py", "package-info.java")) for r in reranked
        ), "the re-export barrel must remain reachable"

    def test_us6_dts_stub_stays_reachable(self, indexed_path_penalty: dict[str, Any]) -> None:
        reranked = _reranked(indexed_path_penalty, "foo config")
        assert reranked, "query must surface the stub"
        dts = [r for r in reranked if r["file_path"].endswith("foo.d.ts")]
        assert dts, "the .d.ts stub must stay reachable (preference, not exclusion)"
        assert dts[0]["score_sources"]["path_class"] == "dts", dts[0]["score_sources"]
