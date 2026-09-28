"""Integration tests for paraphrase precision.

Pins the definition-over-reference and scaffolding-demotion fixes.
Written to fail until the reranker's owner boost is generalized and the
lexical-echo demotion lands.

Runs against the ``robustness`` fixture (model/DTO/assembler/exception
plumbing around real ``ArticleService`` behavior) for the on-topic scaffold
guards, and the ``transparency`` fixture for the in-repo paraphrase battery
that enforces the precision floors (top-10 >= 70%, top-1 >= 60%).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.engine.reranking import Reranker

P1 = "what happens when an article is saved"
P2 = "how is the article stored"
GT = {"ArticleService.java"}


def _reranked(search: Any, query: str, limit: int = 10) -> list[dict[str, Any]]:
    envelope = search.search(query, limit=limit, content="all")
    reranker = Reranker(search._db, settings=search._settings)  # type: ignore[arg-type]
    return reranker.rerank(envelope["results"], query_terms=None, query=query)


class TestDefinitionOverReference:
    def test_owner_definition_outranks_reference_only_chunks(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """The queried symbol's definition chunk outranks chunks that
        only reference it, for a behavior/paraphrase query with no explicit
        definition-intent word."""
        ranked = _reranked(indexed_transparency["search"], P1)
        assert len(ranked) >= 2, "expected multiple candidate chunks"
        top = ranked[0]
        assert Path(top["file_path"]).name in GT
        assert top["is_definition"], "top result should be the definition chunk"

    def test_definition_boost_fires_without_definition_intent_word(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """A definition chunk whose FQN/subwords overlap the query
        subwords outranks a reference-only chunk at equal raw score even with
        no ``definition``/``owner`` token in the query."""
        ranked = _reranked(indexed_transparency["search"], P2)
        assert len(ranked) >= 2
        top = ranked[0]
        assert top["is_definition"], "definition should outrank references"
        assert Path(top["file_path"]).name in GT


class TestScaffoldingDemotion:
    def test_lexical_echo_scaffolding_demoted_below_on_topic(
        self, indexed_robustness: dict[str, Any]
    ) -> None:
        """Model/DTO/assembler/exception plumbing (lexical echo) is
        demoted below on-topic results for a behavior-intent paraphrase query."""
        ranked = _reranked(indexed_robustness["search"], "how is an article created")
        assert len(ranked) >= 2
        top = ranked[0]
        top_path = Path(top["file_path"]).name
        assert top_path in ("ArticleService.java",), (
            f"behavior query surfaced scaffolding first: {top_path}"
        )

    def test_on_topic_scaffold_query_still_returns_scaffolding(
        self, indexed_robustness: dict[str, Any]
    ) -> None:
        """A query naming the generic construct itself
        (``exception``) lifts the demotion so on-topic scaffolding ranks."""
        ranked = _reranked(indexed_robustness["search"], "what exceptions does the API throw")
        assert len(ranked) >= 1
        names = {Path(r["file_path"]).name for r in ranked}
        assert any("Exception" in name for name in names), (
            "on-topic exception query returned no exception scaffold"
        )


class TestSc005ParaphraseBattery:
    def test_in_repo_paraphrase_battery_meets_sc005_floors(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """The in-repo paraphrase battery (P1/P2) meets top-10 >= 70%
        and top-1 >= 60%, enforced in CI without the external corpus."""
        precisions: list[float] = []
        top1_hits = 0
        for query in (P1, P2):
            ranked = _reranked(indexed_transparency["search"], query, limit=10)
            top10_names = {Path(r["file_path"]).name for r in ranked[:10]}
            precision = len(top10_names & GT) / min(10, len(GT))
            precisions.append(precision)
            if ranked and Path(ranked[0]["file_path"]).name in GT:
                top1_hits += 1
        mean_p10 = sum(precisions) / len(precisions)
        top1_rate = top1_hits / len((P1, P2))
        assert mean_p10 >= 0.70, f"SC-005 top-10 precision {mean_p10:.2f} < 0.70"
        assert top1_rate >= 0.60, f"SC-005 top-1 rate {top1_rate:.2f} < 0.60"


# The probe battery: the authorization-restriction
# and table/schema/DDL/migration failure classes added to the existing P1/P2
# in-repo probes. Each probe is (query, ground-truth answer files).
SPEC019_PROBES: list[tuple[str, set[str]]] = [
    ("restrict which users can modify a resource", {"ArticleService.java"}),
    ("who is allowed to delete an article", {"ArticleService.java"}),
    ("create the database schema for the articles table", {"V1__create_articles_table.sql"}),
    ("what tables exist in the database", {"V1__create_articles_table.sql"}),
    ("add a column to the articles table", {"V2__add_published_column.sql"}),
    ("which schema migration adds a column", {"V2__add_published_column.sql"}),
    ("where is the server port configured", {"application.properties"}),
    ("what is the mysql connection url", {"application.properties"}),
    ("how is an article saved", {"ArticleRepository.java"}),
    ("what happens when an article is saved", {"ArticleService.java"}),
    ("how do comments get created", {"ArticleService.java", "CommentService.java"}),
    ("what exceptions does the api throw", {"ArticleNotFoundException.java"}),
    ("how is article creation secured", {"SecurityConfig.java"}),
    ("which file defines the articles schema", {"V1__create_articles_table.sql"}),
]


class TestAuthorizationProbe:
    def test_authorization_paraphrase_surfaces_guarded_definition(
        self, indexed_relevance: dict[str, Any]
    ) -> None:
        """An authorization-restriction paraphrase surfaces
        the authorization-guarded definition/annotation chunk in the top 10."""
        ranked = _reranked(indexed_relevance["search"], SPEC019_PROBES[0][0], limit=10)
        top10 = {Path(r["file_path"]).name for r in ranked[:10]}
        assert "ArticleService.java" in top10, (
            f"authorization paraphrase missed the guarded definition: {top10}"
        )


class TestDDLProbe:
    def test_ddl_paraphrase_surfaces_schema_chunk(self, indexed_relevance: dict[str, Any]) -> None:
        """A table/schema DDL-intent query surfaces
        the schema/migration chunk in the top 10."""
        ranked = _reranked(indexed_relevance["search"], SPEC019_PROBES[2][0], limit=10)
        top10 = {Path(r["file_path"]).name for r in ranked[:10]}
        assert "V1__create_articles_table.sql" in top10, f"DDL query missed the schema: {top10}"


class TestSpec019ProbeBattery:
    def test_in_repo_probe_battery_meets_sc003_floors(
        self, indexed_relevance: dict[str, Any]
    ) -> None:
        """The widened in-repo probe battery (authorization + DDL +
        migration classes) meets mean top-10 precision >= 0.70 and answer
        present in >= 12/14 probes, offline and deterministic."""
        precisions: list[float] = []
        present = 0
        for query, gt in SPEC019_PROBES:
            ranked = _reranked(indexed_relevance["search"], query, limit=10)
            top10 = {Path(r["file_path"]).name for r in ranked[:10]}
            precision = len(top10 & gt) / min(10, len(gt))
            precisions.append(precision)
            if top10 & gt:
                present += 1
        mean_p10 = sum(precisions) / len(precisions)
        assert mean_p10 >= 0.70, f"SC-003 mean top-10 precision {mean_p10:.2f} < 0.70"
        assert present >= 12, f"SC-003 answer present in {present}/14 probes (< 12)"
