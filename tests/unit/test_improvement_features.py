"""Regression tests for the code-search improvement workstreams.

Covers the storage/runtime contract, persisted corpus statistics, compact
output shape, config-scent boundaries, documentation/config tiers, and cache
layout separation.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from code_search.engine.classification import config_tier, documentation_tier
from code_search.engine.intent_detection import ContentIntent, classify_content_intent
from code_search.engine.response_service import compact_result
from tests.conftest import FIXTURES_DIR, _indexed_components


def _fixture(name: str, tmp_path: Path, **settings: Any) -> dict[str, Any]:
    """Index a fixture into a fresh context directory."""
    repo = tmp_path / f"{name}_repo"
    shutil.copytree(FIXTURES_DIR / name, repo)
    kwargs = {"index_prose": True, **settings}
    return _indexed_components(repo, repo / ".context", settings_kwargs=kwargs)


def test_config_scent_does_not_hijack_code_queries() -> None:
    """A code query mentioning ``key``/``secret`` is not a config query."""
    assert (
        classify_content_intent("create and verify a signed JSON web token with an HMAC secret key")
        is not ContentIntent.CONFIG
    )
    assert (
        classify_content_intent("combine multiple maps keeping the last value for duplicate keys")
        is not ContentIntent.CONFIG
    )
    assert classify_content_intent("Kafka bootstrap servers configuration") is ContentIntent.CONFIG


def test_documentation_and_config_tiers() -> None:
    """Canonical project docs/config outrank vendored and test variants."""
    assert documentation_tier("README.md") == "project"
    assert documentation_tier("docs/guide.md") == "project"
    assert documentation_tier("module/src/main/README.md") == "nested"
    assert documentation_tier("third_party/vendor/README.md") == "third_party"
    assert config_tier("spring-kafka/src/main/resources/application.properties") == "primary"
    assert config_tier("module/src/test/resources/application.properties") == "test"
    assert config_tier("samples/demo/application.yml") == "sample"
    assert config_tier("target/classes/application.properties") == "generated"


def test_persisted_corpus_statistics_and_test_flag(tmp_path: Path) -> None:
    """Indexing persists token statistics and an indexed test-file flag."""
    comps = _fixture("relevance", tmp_path)
    with comps["db"].connect() as conn:
        chunks = conn.execute("SELECT COUNT(*) AS n FROM code_chunks;").fetchone()["n"]
        statistics = conn.execute("SELECT COUNT(*) AS n FROM subword_stats;").fetchone()["n"]
        prefixes = conn.execute("SELECT COUNT(*) AS n FROM prefix_stats;").fetchone()["n"]
        meta = conn.execute(
            "SELECT value FROM index_metadata WHERE key = 'corpus_chunk_count';"
        ).fetchone()["value"]
    assert chunks > 0
    assert statistics > 0
    assert prefixes > 0
    assert int(meta) == chunks
    with comps["db"].connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(code_chunks);")}
    assert "is_test" in columns


def test_compact_result_paths_only_and_zero_snippet() -> None:
    """``paths_only`` drops content; ``max_snippet_lines=0`` omits content too."""
    result = {
        "file_path": "src/Service.java",
        "line_start": 10,
        "line_end": 20,
        "fqn": "src/Service.java::Service.run",
        "content": "line one\nline two",
        "confidence_band": "high",
        "is_definition": True,
        "is_test_file": False,
        "empty_field": "",
        "null_field": None,
    }
    paths = compact_result(result, paths_only=True)
    assert paths["symbol"] == "run"
    assert "content" not in paths
    assert "null_field" not in paths
    no_content = compact_result(result, max_snippet_lines=0)
    assert "content" not in no_content
    assert no_content["line_start"] == 10
    snippet = compact_result(result, max_snippet_lines=1)
    assert snippet["content"] == "line one"
    assert snippet["content_truncated"] is True


def test_compact_layout_uses_v2_files_and_same_ranking(tmp_path: Path) -> None:
    """The compact layout writes v2 vector files and ranks like legacy."""
    legacy = _fixture("relevance", tmp_path / "legacy", index_layout="legacy")
    compact = _fixture("relevance", tmp_path / "compact", index_layout="compact")
    legacy_context = tmp_path / "legacy" / "relevance_repo/.context"
    compact_context = tmp_path / "compact" / "relevance_repo/.context"
    legacy_files = {path.name for path in legacy_context.iterdir()}
    compact_files = {path.name for path in compact_context.iterdir()}
    assert "vectors.bin" in legacy_files
    assert "vectors.v2.bin" in compact_files
    assert "vectors.bin" not in compact_files
    legacy_paths = [
        r["file_path"].split("relevance_repo", 1)[-1]
        for r in legacy["search"].search("article comment service", limit=5)["results"]
    ]
    compact_paths = [
        r["file_path"].split("relevance_repo", 1)[-1]
        for r in compact["search"].search("article comment service", limit=5)["results"]
    ]
    assert legacy_paths == compact_paths


def test_output_bytes_are_compact(tmp_path: Path) -> None:
    """Ten compact results stay under the agent output budget."""
    from code_search.engine.response_service import compact_results, relativize_results

    comps = _fixture("relevance", tmp_path)
    results = comps["search"].search("article comment service", limit=10)["results"]
    # Agents receive repo-relative paths (the MCP/CLI envelope relativizes
    # them), so measure that shape rather than the absolute indexed spelling.
    compact = compact_results(relativize_results(results, comps["repo"]))
    assert len(json.dumps(compact, separators=(",", ":")).encode()) <= 6500
