"""Integration tests for DDL and migration-intent
queries ranking the schema/migration resources.

Runs against the ``relevance`` fixture's Flyway migrations
(``V1__create_articles_table.sql``/``V2__add_published_column.sql``), now
classified ``content_type: config``. A DDL-scent query ("database schema",
"create table") ranks the ``.sql`` chunk in the top 10, a migration-intent
query ("add a column") returns the migration chunk, and no irrelevant build
noise outranks them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.engine.reranking import Reranker

DDL_SCENT_QUERY = "database schema"
MIGRATION_QUERY = "add a column to the articles table"
GT_SCHEMA = "V1__create_articles_table.sql"
GT_MIGRATION = "V2__add_published_column.sql"


def _reranked(search: Any, query: str, limit: int = 10) -> list[dict[str, Any]]:
    envelope = search.search(query, limit=limit)
    reranker = Reranker(search._db, settings=search._settings)  # type: ignore[arg-type]
    return reranker.rerank(envelope["results"], query=query)


class TestDDLScentRanking:
    def test_ddl_scent_ranks_sql_chunk_in_top10(self, indexed_relevance: dict[str, Any]) -> None:
        """A DDL-scent query ranks the relevant ``.sql``/schema chunk
        in the top 10."""
        ranked = _reranked(indexed_relevance["search"], DDL_SCENT_QUERY)
        top10 = [Path(r["file_path"]).name for r in ranked[:10]]
        assert GT_SCHEMA in top10, f"DDL-scent query missed the schema chunk: {top10}"

    def test_create_table_query_ranks_schema_above_build_noise(
        self, indexed_relevance: dict[str, Any]
    ) -> None:
        """A "create table" query ranks the schema chunk with
        no irrelevant ``pom.xml``/``package-lock.json`` outranking it."""
        ranked = _reranked(indexed_relevance["search"], "create table for the articles")
        top10 = [Path(r["file_path"]).name for r in ranked[:10]]
        schema_rank = top10.index(GT_SCHEMA) if GT_SCHEMA in top10 else None
        assert schema_rank is not None, f"schema chunk missing: {top10}"
        for noise in ("pom.xml", "package-lock.json"):
            noise_rank = next((i for i, n in enumerate(top10) if n == noise), None)
            if noise_rank is not None:
                assert schema_rank < noise_rank, f"build noise outranks the schema: {top10}"


class TestMigrationIntentRanking:
    def test_migration_intent_returns_migration_chunk(
        self, indexed_relevance: dict[str, Any]
    ) -> None:
        """A migration-intent query ("add a column to the articles
        table") returns the relevant migration chunk."""
        ranked = _reranked(indexed_relevance["search"], MIGRATION_QUERY)
        top10 = [Path(r["file_path"]).name for r in ranked[:10]]
        assert GT_MIGRATION in top10, f"migration-intent query missed the migration: {top10}"

    def test_sql_chunk_reports_config_content_type(self, indexed_relevance: dict[str, Any]) -> None:
        """The reclassified ``.sql`` chunk reports ``content_type: config`` so
        it routes through the config content filter and config-scent boosts."""
        ranked = _reranked(indexed_relevance["search"], MIGRATION_QUERY)
        migration = next((r for r in ranked if Path(r["file_path"]).name == GT_MIGRATION), None)
        assert migration is not None
        assert migration["content_type"] == "config", migration["content_type"]
