"""Comprehensive acceptance test suite for code-search.

Run against any git repository:
    pytest tests/acceptance/ -v --repo-path /path/to/repo

Or against the built-in sample repo (default):
    pytest tests/acceptance/ -v

Features tested:
  - CLI: index, search, symbol, graph, metrics, list-languages
  - MCP tools: search, get_symbol_definition, get_call_neighbors, find_related
  - Cross-cutting: audit log, session tracking, redaction, air-gap enforcement
  - Resource file indexing, incremental indexing, exclusion patterns
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.acceptance.conftest import _DEV_EXCLUDE, _run_cs, _setup_sample_repo


def _context_dir(repo_path: Path) -> Path:
    return repo_path / ".context"


def _ctx_flag(repo_path: Path) -> list[str]:
    return ["--context-dir", str(_context_dir(repo_path))]


def _db_connect(repo_path: Path) -> sqlite3.Connection:
    db_path = _context_dir(repo_path) / "graph.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _audit_connect(repo_path: Path) -> sqlite3.Connection:
    db_path = _context_dir(repo_path) / "audit.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _discover_symbols(repo_path: Path) -> list[dict[str, Any]]:
    conn = _db_connect(repo_path)
    try:
        rows = conn.execute(
            "SELECT id, fqn, name, kind, file_path, line_start, line_end, "
            "language FROM symbols ORDER BY id LIMIT 50"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _discover_chunks(repo_path: Path) -> list[dict[str, Any]]:
    conn = _db_connect(repo_path)
    try:
        rows = conn.execute(
            "SELECT id, fqn, file_path, line_start, line_end, content, language "
            "FROM code_chunks ORDER BY id LIMIT 50"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Helpers for running the CLI pointed at the right context
# ---------------------------------------------------------------------------


def _search(
    repo_path: Path, query: str, extra: list[str] | None = None
) -> subprocess.CompletedProcess[str]:
    return _run_cs(
        ["search", query, *_ctx_flag(repo_path), *(extra or [])],
        timeout=60,
    )


def _symbol(
    repo_path: Path, fqn: str, extra: list[str] | None = None
) -> subprocess.CompletedProcess[str]:
    return _run_cs(
        ["symbol", fqn, *_ctx_flag(repo_path), *(extra or [])],
        timeout=30,
    )


def _graph(
    repo_path: Path, fqn: str, extra: list[str] | None = None
) -> subprocess.CompletedProcess[str]:
    return _run_cs(
        ["graph", fqn, *_ctx_flag(repo_path), *(extra or [])],
        timeout=30,
    )


def _metrics(repo_path: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    return _run_cs(
        ["metrics", *_ctx_flag(repo_path), *(extra or [])],
        timeout=30,
    )


# ---------------------------------------------------------------------------
# CLI: index
# ---------------------------------------------------------------------------


class TestCliIndex:
    """Full + incremental indexing, resource inclusion, exclusions."""

    def test_index_produces_graph_db_and_audit_db(self, repo_path: Path, indexed: dict) -> None:
        ctx = _context_dir(repo_path)
        assert ctx.exists()
        assert (ctx / "graph.db").exists()
        assert (ctx / "audit.db").exists()

    def test_index_populates_symbols(self, repo_path: Path, indexed: dict) -> None:
        conn = _db_connect(repo_path)
        try:
            count = conn.execute("SELECT COUNT(*) AS cnt FROM symbols").fetchone()["cnt"]
            assert count > 0, "No symbols found in index"
        finally:
            conn.close()

    def test_index_populates_code_chunks(self, repo_path: Path, indexed: dict) -> None:
        conn = _db_connect(repo_path)
        try:
            count = conn.execute("SELECT COUNT(*) AS cnt FROM code_chunks").fetchone()["cnt"]
            assert count > 0, "No code chunks found in index"
        finally:
            conn.close()

    def test_index_populates_chunks_fts(self, repo_path: Path, indexed: dict) -> None:
        conn = _db_connect(repo_path)
        try:
            count = conn.execute("SELECT COUNT(*) AS cnt FROM chunks_fts").fetchone()["cnt"]
            assert count > 0, "No FTS entries found"
        finally:
            conn.close()

    def test_index_metadata_ready(self, repo_path: Path, indexed: dict) -> None:
        conn = _db_connect(repo_path)
        try:
            row = conn.execute(
                "SELECT value FROM index_metadata WHERE key = 'index_status'"
            ).fetchone()
            assert row is not None, "Missing index_status metadata"
            assert row["value"] == "ready"
        finally:
            conn.close()

    @pytest.mark.slow
    def test_reindex_idempotent(self, repo_path: Path, indexed: dict) -> None:
        result = _run_cs(
            ["index", "--path", str(repo_path), "--force", "--exclude", _DEV_EXCLUDE],
            timeout=900,
            extra_env={"CODE_SEARCH_CONTEXT_DIR": str(_context_dir(repo_path))},
        )
        assert result.returncode == 0, f"Re-index failed: {result.stderr}"

    @pytest.mark.slow
    def test_incremental_index_no_changes(self, repo_path: Path, indexed: dict) -> None:
        result = _run_cs(
            ["index", "--path", str(repo_path), "--incremental", "--exclude", _DEV_EXCLUDE],
            timeout=120,
            extra_env={"CODE_SEARCH_CONTEXT_DIR": str(_context_dir(repo_path))},
        )
        assert result.returncode == 0, f"Incremental index failed: {result.stderr}"

    @pytest.mark.slow
    def test_indexed_index_again(self, repo_path: Path, indexed: dict) -> None:
        conn_before = _db_connect(repo_path)
        try:
            before = conn_before.execute("SELECT COUNT(*) AS cnt FROM symbols").fetchone()["cnt"]
        finally:
            conn_before.close()

        result = _run_cs(
            ["index", "--path", str(repo_path), "--force", "--exclude", _DEV_EXCLUDE],
            timeout=900,
            extra_env={"CODE_SEARCH_CONTEXT_DIR": str(_context_dir(repo_path))},
        )
        assert result.returncode == 0

        conn_after = _db_connect(repo_path)
        try:
            after = conn_after.execute("SELECT COUNT(*) AS cnt FROM symbols").fetchone()["cnt"]
        finally:
            conn_after.close()

        assert after >= before, f"Re-index should not reduce symbols ({before} -> {after})"

    def test_exclude_patterns(self, repo_path: Path, tmp_path: Path) -> None:
        test_repo = tmp_path / "exclude_repo"
        test_repo.mkdir()
        (test_repo / "node_modules").mkdir()
        (test_repo / ".git").mkdir()
        (test_repo / "src").mkdir()
        (test_repo / "node_modules" / "dep.js").write_text("module.exports = {};\n")
        (test_repo / "src" / "main.py").write_text("def main(): return 1\n")
        (test_repo / ".git" / "config").write_text("[core]\n")

        ctx_dir = test_repo / ".context"
        result = _run_cs(
            [
                "index",
                "--path",
                str(test_repo),
                "--force",
                "--exclude",
                "node_modules,.git,.context",
            ],
            timeout=120,
            extra_env={"CODE_SEARCH_CONTEXT_DIR": str(ctx_dir)},
        )
        assert result.returncode == 0, f"Index with exclusions failed: {result.stderr}"

        conn = sqlite3.connect(str(ctx_dir / "graph.db"))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT file_path FROM symbols").fetchall()
            paths = {r["file_path"] for r in rows}
            assert str(test_repo / "src" / "main.py") in paths
            assert str(test_repo / "node_modules" / "dep.js") not in paths
        finally:
            conn.close()

    def test_index_exclude_tests(self, repo_path: Path, tmp_path: Path) -> None:
        test_repo = tmp_path / "notest_repo"
        test_repo.mkdir()
        (test_repo / "src").mkdir()
        (test_repo / "test").mkdir()
        (test_repo / "src" / "lib.py").write_text("def lib_fn(): pass\n")
        (test_repo / "test" / "test_lib.py").write_text("from src.lib import lib_fn\n")

        ctx_dir = test_repo / ".context"
        result = _run_cs(
            ["index", "--path", str(test_repo), "--force", "--no-include-tests"],
            timeout=120,
            extra_env={"CODE_SEARCH_CONTEXT_DIR": str(ctx_dir)},
        )
        assert result.returncode == 0

        conn = sqlite3.connect(str(ctx_dir / "graph.db"))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT file_path FROM symbols").fetchall()
            paths = {r["file_path"] for r in rows}
            assert str(test_repo / "src" / "lib.py") in paths, "Source file should be indexed"
            expected = str(test_repo / "test" / "test_lib.py")
            assert expected not in paths, "Test file should be excluded"
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# CLI: search
# ---------------------------------------------------------------------------


class TestCliSearch:
    """Natural-language code search via CLI."""

    def test_search_returns_results(self, repo_path: Path, indexed: dict) -> None:
        result = _search(repo_path, "UserService")
        assert result.returncode == 0
        assert result.stdout.strip(), "Search should return results"

    def test_search_json_output(self, repo_path: Path, indexed: dict) -> None:
        result = _search(repo_path, "UserService", extra=["--json", "--limit", "5"])
        assert result.returncode == 0
        raw = result.stdout.strip()
        if raw == "No results found.":
            pytest.skip("Search returned no results for test query")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON output:\n{result.stdout}")
        data = _unwrap_search(data)
        if data:
            r = data[0]
            for key in ("chunk_id", "file_path", "score", "content"):
                assert key in r, f"Missing key '{key}' in search result"

    def test_search_language_filter_python(self, repo_path: Path, indexed: dict) -> None:
        result = _search(
            repo_path, "def", extra=["--language", "python", "--json", "--limit", "10"]
        )
        assert result.returncode == 0
        raw = result.stdout.strip()
        if raw == "No results found.":
            pytest.skip("No results for filtered query")
        data = json.loads(raw)
        data = _unwrap_search(data)
        for r in data:
            assert r.get("language") == "python", f"Expected python, got {r.get('language')}"

    def test_search_with_limit(self, repo_path: Path, indexed: dict) -> None:
        result = _search(repo_path, "def", extra=["--json", "--limit", "3"])
        assert result.returncode == 0
        raw = result.stdout.strip()
        if raw == "No results found.":
            pytest.skip("No results for query")
        data = json.loads(raw)
        data = _unwrap_search(data)
        assert len(data) <= 3, f"Limit 3 but got {len(data)} results"

    def test_search_test_files_excluded(self, repo_path: Path, indexed: dict) -> None:
        result = _search(
            repo_path,
            "test_authenticate",
            extra=["--json", "--no-include-tests", "--limit", "10"],
        )
        assert result.returncode == 0
        raw = result.stdout.strip()
        if raw == "No results found.":
            pytest.skip("No results for query")
        data = json.loads(raw)
        data = _unwrap_search(data)
        for r in data:
            assert not r.get("is_test_file"), (
                f"Test file included despite --no-include-tests: {r.get('file_path')}"
            )

    def test_search_test_files_included(self, repo_path: Path, indexed: dict) -> None:
        result = _search(
            repo_path,
            "def test_authenticate",
            extra=["--json", "--include-tests", "--limit", "10"],
        )
        assert result.returncode == 0
        raw = result.stdout.strip()
        if raw == "No results found.":
            pytest.skip("No results for query")
        data = json.loads(raw)
        data = _unwrap_search(data)
        has_tests = any(r.get("is_test_file") for r in data)
        assert has_tests, "Test files should appear when include-tests is True"

    def test_search_no_results(self, repo_path: Path, indexed: dict) -> None:
        result = _search(repo_path, "xyznonexistent12345abcdef", extra=["--json"])
        assert result.returncode == 0

    def test_search_score_range(self, repo_path: Path, indexed: dict) -> None:
        result = _search(repo_path, "UserService", extra=["--json", "--limit", "10"])
        assert result.returncode == 0
        raw = result.stdout.strip()
        if raw == "No results found.":
            pytest.skip("No results for query")
        data = json.loads(raw)
        data = _unwrap_search(data)
        for r in data:
            s = r["score"]
            assert 0.0 <= s <= 1.0, f"Score {s} out of range [0,1]"

    def test_search_below_threshold_flag(self, repo_path: Path, indexed: dict) -> None:
        result = _search(repo_path, "UserService", extra=["--json", "--limit", "10"])
        assert result.returncode == 0
        raw = result.stdout.strip()
        if raw == "No results found.":
            pytest.skip("No results for query")
        data = json.loads(raw)
        data = _unwrap_search(data)
        for r in data:
            assert "below_threshold" in r
            assert "relevance_threshold_applied" in r

    def test_search_xml_resource(self, repo_path: Path, indexed: dict) -> None:
        resources = repo_path / "resources"
        if not resources.exists():
            pytest.skip("No resources/ directory")
        result = _search(repo_path, "configuration", extra=["--json", "--limit", "10"])
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# CLI: symbol
# ---------------------------------------------------------------------------


class TestCliSymbol:
    """Fully-qualified name symbol lookup via CLI."""

    @pytest.fixture(scope="class")
    @classmethod
    def symbols(cls, repo_path: Path, indexed: dict) -> list[dict[str, Any]]:
        return _discover_symbols(repo_path)

    def test_symbol_lookup_by_fqn(self, repo_path: Path, indexed: dict, symbols: list) -> None:
        if not symbols:
            pytest.skip("No symbols available in index")
        sym = symbols[0]
        result = _symbol(repo_path, sym["fqn"])
        assert result.returncode == 0
        assert sym["name"] in result.stdout, f"Expected name '{sym['name']}' in output"

    def test_symbol_not_found(self, repo_path: Path, indexed: dict) -> None:
        result = _symbol(repo_path, "nonexistent.module::doesnotexist")
        assert "not found" in (result.stdout + result.stderr).lower() or result.returncode == 0

    def test_symbol_json_output(self, repo_path: Path, indexed: dict, symbols: list) -> None:
        if not symbols:
            pytest.skip("No symbols available in index")
        sym = symbols[0]
        result = _symbol(repo_path, sym["fqn"], extra=["--json"])
        assert result.returncode == 0
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON: {result.stdout}")
        assert data.get("found") is True
        for key in ("fqn", "name", "kind", "file_path", "line_start", "line_end"):
            assert key in data["symbol"], f"Missing key '{key}' in symbol output"

    def test_symbol_kind_present(self, repo_path: Path, indexed: dict, symbols: list) -> None:
        if not symbols:
            pytest.skip("No symbols available in index")
        valid = {
            "function",
            "class",
            "method",
            "module",
            "variable",
            "interface",
            "constructor",
            "struct",
            "trait",
            "enum",
            "enum_member",
            "type_alias",
            "constant",
            "import",
            "field",
        }
        for sym in symbols:
            assert sym["kind"] in valid, f"Unknown symbol kind: {sym['kind']}"


# ---------------------------------------------------------------------------
# CLI: graph
# ---------------------------------------------------------------------------


class TestCliGraph:
    """Call-graph traversal via CLI."""

    @pytest.fixture(scope="class")
    @classmethod
    def symbols(cls, repo_path: Path, indexed: dict) -> list[dict[str, Any]]:
        return _discover_symbols(repo_path)

    def test_graph_displays_callers_callees(
        self, repo_path: Path, indexed: dict, symbols: list
    ) -> None:
        if not symbols:
            pytest.skip("No symbols available in index")
        sym = symbols[0]
        result = _graph(repo_path, sym["fqn"])
        assert result.returncode == 0

    def test_graph_json_output(self, repo_path: Path, indexed: dict, symbols: list) -> None:
        if not symbols:
            pytest.skip("No symbols available in index")
        sym = symbols[0]
        result = _graph(repo_path, sym["fqn"], extra=["--json"])
        assert result.returncode == 0
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON: {result.stdout}")
        assert "symbol" in data
        assert "callers" in data
        assert "callees" in data
        assert "fqn" in data["symbol"]

    def test_graph_not_found(self, repo_path: Path, indexed: dict) -> None:
        result = _graph(repo_path, "nonexistent::ghost")
        assert "not found" in (result.stdout + result.stderr).lower() or result.returncode == 0

    def test_graph_direction_callees(self, repo_path: Path, indexed: dict, symbols: list) -> None:
        if not symbols:
            pytest.skip("No symbols available in index")
        sym = symbols[0]
        result = _graph(repo_path, sym["fqn"], extra=["--direction", "callees", "--json"])
        assert result.returncode == 0
        json.loads(result.stdout)

    def test_graph_direction_callers(self, repo_path: Path, indexed: dict, symbols: list) -> None:
        if not symbols:
            pytest.skip("No symbols available in index")
        sym = symbols[0]
        result = _graph(repo_path, sym["fqn"], extra=["--direction", "callers", "--json"])
        assert result.returncode == 0
        json.loads(result.stdout)

    def test_graph_depth(self, repo_path: Path, indexed: dict, symbols: list) -> None:
        if not symbols:
            pytest.skip("No symbols available in index")
        sym = symbols[0]
        result = _graph(repo_path, sym["fqn"], extra=["--depth", "2", "--transitive", "--json"])
        assert result.returncode == 0
        json.loads(result.stdout)


def _indexed_freshness_repo(tmp_path: Path) -> Path:
    repo = _setup_sample_repo(tmp_path)
    idx = _run_cs(
        [
            "index",
            "--path",
            str(repo),
            "--force",
            "--include-tests",
            "--exclude",
            _DEV_EXCLUDE,
        ],
        timeout=900,
        extra_env={
            "CODE_SEARCH_CONTEXT_DIR": str(_context_dir(repo)),
            "CODE_SEARCH_FRESHNESS_TTL_SECONDS": "0",
        },
    )
    assert idx.returncode == 0, (
        f"Index failed (rc={idx.returncode}):\nSTDOUT:\n{idx.stdout}\nSTDERR:\n{idx.stderr}"
    )
    return repo


def _search_fresh(repo_path: Path, query: str, extra: list[str] | None = None) -> Any:
    return _run_cs(
        ["search", query, *_ctx_flag(repo_path), *(extra or [])],
        timeout=60,
        extra_env={"CODE_SEARCH_FRESHNESS_TTL_SECONDS": "0"},
    )


def _unwrap_search(data: Any) -> list[Any]:
    assert isinstance(data, dict), "search --json should emit the additive envelope"
    assert "results" in data, "search --json envelope missing 'results'"
    assert "freshness" in data, "search --json envelope missing 'freshness'"
    return data["results"]


class TestFreshnessStaleness:
    """Staleness battery: an edit flips the
    signal stale, a clean index shows no false warning, and a deleted file is
    counted without crashing."""

    def test_edit_after_index_reports_stale(self, tmp_path: Path) -> None:
        repo = _indexed_freshness_repo(tmp_path)
        target = repo / "src" / "main.py"
        target.write_text(target.read_text() + "\n# edited after index\n")

        result = _search_fresh(repo, "UserService", extra=["--json", "--limit", "3"])
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["freshness"]["stale"] is True
        assert data["freshness"]["modified_files"] >= 1
        assert data["freshness"]["stale_change_count"] >= 1

    def test_clean_index_has_no_false_warning(self, tmp_path: Path) -> None:
        repo = _indexed_freshness_repo(tmp_path)

        result = _search_fresh(repo, "UserService", extra=["--json", "--limit", "3"])
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["freshness"]["stale"] is False
        assert data["freshness"]["stale_change_count"] == 0

        human = _search_fresh(repo, "UserService", extra=["--limit", "3"])
        assert "stale index" not in human.stderr
        assert "stale index" not in human.stdout

    def test_deleted_file_counts_and_does_not_crash(self, tmp_path: Path) -> None:
        repo = _indexed_freshness_repo(tmp_path)
        (repo / "src" / "models.py").unlink()

        result = _search_fresh(repo, "UserService", extra=["--json", "--limit", "3"])
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["freshness"]["stale"] is True
        assert data["freshness"]["deleted_files"] >= 1


# ---------------------------------------------------------------------------
# CLI: metrics + list-languages
# ---------------------------------------------------------------------------


class TestCliMetrics:
    """Metrics and health reporting."""

    def test_metrics_human_format(self, repo_path: Path, indexed: dict) -> None:
        result = _metrics(repo_path)
        assert result.returncode == 0
        assert "Index Health" in result.stdout or result.stdout.strip()

    def test_metrics_json_format(self, repo_path: Path, indexed: dict) -> None:
        result = _metrics(repo_path, extra=["--format", "json"])
        assert result.returncode == 0
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON: {result.stdout}")
        for key in ("index_status", "total_files", "total_symbols", "total_chunks"):
            assert key in data, f"Missing key '{key}' in metrics JSON"

    def test_metrics_prometheus_format(self, repo_path: Path, indexed: dict) -> None:
        result = _metrics(repo_path, extra=["--format", "prometheus"])
        assert result.returncode == 0
        assert "code_search_index_status" in result.stdout

    def test_metrics_contains_audit_entries(self, repo_path: Path, indexed: dict) -> None:
        result = _metrics(repo_path, extra=["--format", "json"])
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "metrics" in data
        assert "audit_entries" in data["metrics"]


class TestCliListLanguages:
    def test_list_languages(self, repo_path: Path, indexed: dict) -> None:
        result = _run_cs(["list-languages"], timeout=30)
        assert result.returncode == 0
        assert "Supported languages" in result.stdout


# ---------------------------------------------------------------------------
# MCP tools (tested via direct module import)
# ---------------------------------------------------------------------------


def _close_comps_connections(db: Any, session_db: Any, audit_db: Any) -> None:
    """Close database connections held by the comps fixture so subprocesses
    don't hang on stale WAL locks."""
    for obj in (db, session_db, audit_db):
        try:
            if hasattr(obj, "_local") and hasattr(obj._local, "conn"):
                conn = obj._local.conn
                if conn is not None:
                    conn.close()
                obj._local.conn = None
        except Exception:
            pass


class TestMCPTools:
    """Test the four MCP tools by importing components directly."""

    @pytest.fixture(scope="class")
    @classmethod
    def comps(cls, repo_path: Path, indexed: dict) -> dict[str, Any]:
        from src.context import ContextManager
        from src.engine.audit import AuditDatabase
        from src.engine.config import Settings
        from src.engine.embeddings import EmbeddingGenerator, VectorIndex
        from src.engine.graph import EdgeStore, GraphDatabase
        from src.engine.metrics import MetricsCollector
        from src.engine.parser import ASTParser
        from src.engine.redactor import Redactor
        from src.engine.reranking import Reranker
        from src.engine.search import HybridSearch
        from src.engine.session import SessionDatabase
        from src.engine.symbols import SymbolExtractor, SymbolStore

        ctx_dir = _context_dir(repo_path)
        settings = Settings(context_dir=ctx_dir)
        ctx = ContextManager(settings)
        ctx.ensure()
        paths = ctx.paths

        db = GraphDatabase(paths["graph"], settings)
        db.initialize()
        edge_store = EdgeStore(db)
        parser = ASTParser()
        SymbolExtractor(parser)
        sym_store = SymbolStore(db, settings)
        embedding_gen = EmbeddingGenerator(settings)
        vector_index = VectorIndex(
            paths.get("vectors_bin", ctx_dir / "vectors.bin"),
            paths.get("vectors_meta", ctx_dir / "vectors.meta.json"),
        )
        vector_index.load()
        session_db = SessionDatabase(paths["session"], settings)
        session_db.initialize()
        audit_db = AuditDatabase(paths["audit"])
        audit_db.initialize()
        search = HybridSearch(db, vector_index, embedding_gen, settings)
        reranker = Reranker(db, session_db, settings)
        redactor = Redactor()
        mc = MetricsCollector(settings)

        yield {
            "db": db,
            "edge_store": edge_store,
            "symbol_store": sym_store,
            "embedding_gen": embedding_gen,
            "vector_index": vector_index,
            "session_db": session_db,
            "audit_db": audit_db,
            "search": search,
            "reranker": reranker,
            "redactor": redactor,
            "metrics_collector": mc,
            "settings": settings,
            "context_dir": ctx_dir,
        }

        _close_comps_connections(db, session_db, audit_db)

    def test_mcp_search_returns_results(self, comps: dict) -> None:
        raw = comps["search"].search("user", limit=5)["results"]
        reranked = comps["reranker"].rerank(raw)
        redacted = comps["redactor"].redact_results(reranked)
        assert isinstance(redacted, list)

    def test_mcp_search_json_serializable(self, comps: dict) -> None:
        raw = comps["search"].search("def", limit=3)["results"]
        reranked = comps["reranker"].rerank(raw)
        redacted = comps["redactor"].redact_results(reranked)
        parsed = json.loads(json.dumps(redacted, default=str))
        assert isinstance(parsed, list)

    def test_mcp_get_symbol_definition_found(self, comps: dict) -> None:
        syms = _discover_symbols(Path(comps["context_dir"]).parent)
        if not syms:
            pytest.skip("No symbols in index")
        fqn = syms[0]["fqn"]
        sym = comps["symbol_store"].lookup_by_fqn(fqn)
        assert sym is not None, f"Symbol '{fqn}' not found"
        assert sym["fqn"] == fqn
        for k in ("name", "kind", "file_path", "language"):
            assert k in sym, f"Missing key '{k}'"

    def test_mcp_get_symbol_definition_not_found(self, comps: dict) -> None:
        sym = comps["symbol_store"].lookup_by_fqn("does.not::Exist")
        assert sym is None

    def test_mcp_get_call_neighbors(self, comps: dict) -> None:
        syms = _discover_symbols(Path(comps["context_dir"]).parent)
        if not syms:
            pytest.skip("No symbols in index")
        sym = comps["symbol_store"].lookup_by_fqn(syms[0]["fqn"])
        assert sym is not None
        graph = comps["edge_store"].get_call_graph(sym["id"], "both", 2)
        assert "callers" in graph
        assert "callees" in graph
        assert isinstance(graph["callers"], list)
        assert isinstance(graph["callees"], list)

    def test_mcp_get_call_neighbors_not_found(self, comps: dict) -> None:
        sym = comps["symbol_store"].lookup_by_fqn("nonexistent::ghost")
        assert sym is None

    def test_mcp_find_related(self, comps: dict) -> None:
        chunks = _discover_chunks(Path(comps["context_dir"]).parent)
        if not chunks:
            pytest.skip("No chunks in index")
        chunk = chunks[0]
        query_vec = comps["embedding_gen"].encode(chunk["content"])
        if query_vec is None:
            pytest.skip("Embedding model not available")
        search_results = comps["vector_index"].search(query_vec, top_k=3)
        assert len(search_results) > 0, "Vector search returned no results"

    def test_mcp_find_related_relative_path_resolves(self, comps: dict) -> None:
        """A project-relative find_related file_path resolves to
        the same stored indexed location as the absolute form and produces the
        same non-error result set."""
        from src.engine.paths import normalize_indexed_path, resolve_stored_path

        repo_root = Path(comps["context_dir"]).parent
        chunks = _discover_chunks(repo_root)
        if not chunks:
            pytest.skip("No chunks in index")
        chunk = chunks[0]
        stored_path = chunk["file_path"]
        if not stored_path:
            pytest.skip("chunk has no stored file_path")

        relative = os.path.relpath(stored_path, repo_root)
        candidate = normalize_indexed_path(relative, repo_root)
        assert candidate is not None, f"relative path {relative!r} failed to normalize"

        conn = sqlite3.connect(str(comps["context_dir"] / "graph.db"))
        conn.row_factory = sqlite3.Row
        try:
            resolved = resolve_stored_path(candidate, conn)
        finally:
            conn.close()
        assert resolved == stored_path, (
            f"relative path resolved to {resolved!r}, expected stored {stored_path!r}"
        )

        query_vec = comps["embedding_gen"].encode(chunk["content"])
        if query_vec is None:
            pytest.skip("Embedding model not available")
        search_results = comps["vector_index"].search(query_vec, top_k=3)
        assert len(search_results) > 0, "Vector search returned no results for relative form"


# ---------------------------------------------------------------------------
# Cross-cutting concerns
# ---------------------------------------------------------------------------


class TestAuditLogging:
    """Append-only audit log."""

    def test_audit_db_has_entries(self, repo_path: Path, indexed: dict) -> None:
        from src.engine.audit import AuditDatabase

        audit = AuditDatabase(_context_dir(repo_path) / "audit.db")
        audit.initialize()
        total = audit.count_entries()
        assert total >= 0, "Audit log should be queryable"

    def test_audit_entries_after_search(self, repo_path: Path, indexed: dict) -> None:
        from src.engine.audit import AuditDatabase

        audit = AuditDatabase(_context_dir(repo_path) / "audit.db")
        audit.initialize()
        before = audit.count_entries()

        _search(repo_path, "user", extra=["--json", "--limit", "3"])

        after = audit.count_entries()
        assert after > before, "Search should create an audit entry"

    def test_audit_entry_schema(self, repo_path: Path, indexed: dict) -> None:
        from src.engine.audit import AuditDatabase

        audit = AuditDatabase(_context_dir(repo_path) / "audit.db")
        audit.initialize()
        entries = audit.get_entries(limit=1)
        if not entries:
            pytest.skip("No audit entries yet")
        row = entries[0]
        cols = ("id", "timestamp", "query_type", "result_count", "duration_ms", "redacted_count")
        for col in cols:
            assert col in row.keys(), f"Missing column '{col}' in audit entry"  # noqa: SIM118  # sqlite3.Row.__contains__ checks values, not keys

    def test_audit_append_only_update_blocked(self, repo_path: Path, indexed: dict) -> None:
        from src.engine.audit import AuditDatabase

        audit = AuditDatabase(_context_dir(repo_path) / "audit.db")
        audit.initialize()
        with (
            pytest.raises((sqlite3.OperationalError, sqlite3.IntegrityError)),
            audit.write_transaction() as conn,
        ):
            conn.execute("UPDATE audit_log_entries SET result_count = 999 WHERE id = 1")

    def test_audit_append_only_delete_blocked(self, repo_path: Path, indexed: dict) -> None:
        from src.engine.audit import AuditDatabase

        audit = AuditDatabase(_context_dir(repo_path) / "audit.db")
        audit.initialize()
        with (
            pytest.raises((sqlite3.OperationalError, sqlite3.IntegrityError)),
            audit.write_transaction() as conn,
        ):
            conn.execute("DELETE FROM audit_log_entries")

    def test_audit_query_type_constraint(self, repo_path: Path, indexed: dict) -> None:
        from src.engine.audit import AuditDatabase

        audit = AuditDatabase(_context_dir(repo_path) / "audit.db")
        audit.initialize()
        with pytest.raises(ValueError, match="Invalid query_type"):
            audit.write_entry(query_type="invalid_type")

    def test_audit_filter_by_type(self, repo_path: Path, indexed: dict) -> None:
        from src.engine.audit import AuditDatabase

        audit = AuditDatabase(_context_dir(repo_path) / "audit.db")
        audit.initialize()
        entries = audit.get_entries(limit=10, query_type="search")
        assert all(e["query_type"] == "search" for e in entries)

    def test_audit_count_entries(self, repo_path: Path, indexed: dict) -> None:
        from src.engine.audit import AuditDatabase

        audit = AuditDatabase(_context_dir(repo_path) / "audit.db")
        audit.initialize()
        total = audit.count_entries()
        search_count = audit.count_entries("search")
        assert search_count <= total


class TestSessionTracking:
    """Session-aware reranking events."""

    def test_session_db_present(self, repo_path: Path, indexed: dict) -> None:
        sess_path = _context_dir(repo_path) / "session.db"
        assert sess_path.exists()

    def test_session_record_read_event(self, repo_path: Path, indexed: dict) -> None:
        from src.engine.session import SessionDatabase

        sess_path = _context_dir(repo_path) / "session.db"
        if sess_path.exists():
            sess_path.unlink()
        sess = SessionDatabase(sess_path)
        sess.initialize()
        sid = sess.record_event("src/main.py", "READ")
        assert sid and isinstance(sid, str) and len(sid) > 0

    def test_session_record_write_event(self, repo_path: Path, indexed: dict) -> None:
        from src.engine.session import SessionDatabase

        sess_path = _context_dir(repo_path) / "session.db"
        if sess_path.exists():
            sess_path.unlink()
        sess = SessionDatabase(sess_path)
        sess.initialize()
        sid = sess.record_event("src/utils.py", "WRITE")
        assert sid and isinstance(sid, str)

    def test_session_invalid_event_type(self, repo_path: Path, indexed: dict) -> None:
        from src.engine.session import SessionDatabase

        sess_path = _context_dir(repo_path) / "session.db"
        if sess_path.exists():
            sess_path.unlink()
        sess = SessionDatabase(sess_path)
        sess.initialize()
        with pytest.raises(ValueError, match="event_type must be"):
            sess.record_event("file.py", "DELETE")

    def test_session_weights_decay(self, repo_path: Path, indexed: dict) -> None:
        from src.engine.config import Settings
        from src.engine.session import SessionDatabase

        sess_path = _context_dir(repo_path) / "session.db"
        if sess_path.exists():
            sess_path.unlink()
        sess = SessionDatabase(sess_path, Settings(decay_constant=0.1))
        sess.initialize()
        sess.record_event("src/main.py", "WRITE")
        weights = sess.get_weights_for_files(["src/main.py"])
        if weights:
            w = weights[0]["weight_score"]
            assert 0.0 <= w <= 1.0, f"Weight {w} out of range"

    def test_session_get_active_sessions(self, repo_path: Path, indexed: dict) -> None:
        from src.engine.session import SessionDatabase

        sess_path = _context_dir(repo_path) / "session.db"
        if sess_path.exists():
            sess_path.unlink()
        sess = SessionDatabase(sess_path)
        sess.initialize()
        sess.record_event("src/main.py", "READ")
        active = sess.get_active_sessions()
        assert isinstance(active, list)


class TestRedaction:
    """Secret/PII redaction."""

    def test_redact_api_key(self) -> None:
        from src.engine.redactor import Redactor

        r = Redactor()
        text = "API_KEY = 'sk-proj-0123456789abcdef'"
        redacted, count = r.redact(text)
        assert count >= 1
        assert "[REDACTED]" in redacted

    def test_redact_jwt_token(self) -> None:
        from src.engine.redactor import Redactor

        r = Redactor()
        text = (
            "token = eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        )
        _redacted, count = r.redact(text)
        assert count >= 1

    def test_redact_aws_key(self) -> None:
        from src.engine.redactor import Redactor

        r = Redactor()
        text = "aws_access_key = AKIAIOSFODNN7EXAMPLE"
        _redacted, count = r.redact(text)
        assert count >= 1

    def test_redact_connection_string(self) -> None:
        from src.engine.redactor import Redactor

        r = Redactor()
        text = "db_url = 'postgres://admin:secretpass@localhost:5432/db'"
        _redacted, count = r.redact(text)
        assert count >= 1

    def test_redact_password(self) -> None:
        from src.engine.redactor import Redactor

        r = Redactor()
        text = "password = 'supersecret123'"
        _redacted, count = r.redact(text)
        assert count >= 1

    def test_redact_no_secrets(self) -> None:
        from src.engine.redactor import Redactor

        r = Redactor()
        text = "def hello_world(): print('hello')"
        redacted, count = r.redact(text)
        assert count == 0
        assert redacted == text

    def test_redact_results_applies_to_all(self) -> None:
        from src.engine.redactor import Redactor

        r = Redactor()
        results = [
            {"content": "API_KEY = 'sk-abc123def456'", "chunk_id": 1},
            {"content": "password = 'hunter2'", "chunk_id": 2},
        ]
        redacted = r.redact_results(results)
        assert all("redacted_count" in item for item in redacted)
        assert redacted[0]["redacted_count"] >= 1
        assert redacted[1]["redacted_count"] >= 1


class TestAirGapEnforcement:
    """Air-gapped operation compliance."""

    def test_air_gap_blocks_socket_connect(self) -> None:
        from src.engine.redactor import air_gap_enforcement

        with pytest.raises(RuntimeError, match="Air-gap violation"), air_gap_enforcement():
            import socket

            socket.socket().connect(("127.0.0.1", 1))

    def test_air_gap_blocks_socket_connect_ex(self) -> None:
        from src.engine.redactor import air_gap_enforcement

        with pytest.raises(RuntimeError, match="Air-gap violation"), air_gap_enforcement():
            import socket

            socket.socket().connect_ex(("8.8.8.8", 53))

    def test_air_gap_verify_returns_true(self) -> None:
        from src.engine.redactor import verify_air_gap

        assert verify_air_gap() is True

    def test_allow_downloads_exempts_socket(self) -> None:
        from src.engine.redactor import air_gap_enforcement, allow_downloads

        with air_gap_enforcement():
            with pytest.raises(RuntimeError):
                import socket

                socket.socket().connect(("127.0.0.1", 1))

            with allow_downloads():
                import socket

                s = socket.socket()
                try:
                    s.connect(("127.0.0.1", 1))
                except (ConnectionRefusedError, OSError):
                    pass
                finally:
                    s.close()

    def test_air_gap_restores_socket_after_context(self) -> None:
        import socket as sock_mod

        from src.engine.redactor import air_gap_enforcement

        original = sock_mod.socket
        with air_gap_enforcement():
            assert sock_mod.socket is not original
        assert sock_mod.socket is original


class TestConfigSettings:
    """Configuration and settings behaviour."""

    def test_settings_defaults(self) -> None:
        from src.engine.config import Settings

        s = Settings()
        assert s.rrf_k == 60
        assert s.max_results == 50
        assert s.session_ttl_hours == 24
        assert s.decay_constant == 0.1
        assert s.definition_boost == 1.2
        assert s.noise_penalty == 0.5
        assert s.relevance_threshold == 0.05

    def test_settings_env_override(self) -> None:

        from src.engine.config import Settings

        os.environ["CODE_SEARCH_RRF_K"] = "42"
        os.environ["CODE_SEARCH_MAX_RESULTS"] = "30"
        try:
            s = Settings()
            assert s.rrf_k == 42
            assert s.max_results == 30
        finally:
            del os.environ["CODE_SEARCH_RRF_K"]
            del os.environ["CODE_SEARCH_MAX_RESULTS"]

    def test_relevance_threshold_clamping(self) -> None:
        from src.engine.config import Settings

        s_high = Settings(relevance_threshold=1.5)
        assert s_high.relevance_threshold == 1.0
        s_low = Settings(relevance_threshold=-0.5)
        assert s_low.relevance_threshold == 0.0

    def test_is_test_file_detection(self) -> None:
        from src.engine.config import _is_non_canonical, _is_test_file

        assert _is_test_file("tests/test_auth.py") is True
        assert _is_test_file("src/test_utils.py") is True
        assert _is_test_file("src/helper_test.py") is True
        assert _is_test_file("spec/feature_spec.rb") is True
        assert _is_test_file("src/main/java/com/example/UserServiceTest.java") is True
        assert (
            _is_test_file(
                "src/main/java/com/example/qualitydefects/infra/spec/ArticleSpecification.java"
            )
            is False
        )
        assert _is_test_file("src/utils.py") is False
        assert _is_test_file("src/main.py") is False
        assert _is_non_canonical("src/mock_database.py") is True
        assert _is_non_canonical("src/fake_api.py") is True
        assert _is_non_canonical("src/utils.py") is False


class TestMetricsCollector:
    """In-memory metrics collector."""

    def test_record_and_read_latency(self) -> None:
        from src.engine.metrics import MetricsCollector

        m = MetricsCollector()
        m.record_query(10)
        m.record_query(20)
        m.record_query(30)
        stats = m.get_latency_stats()
        assert stats["p50"] > 0
        assert stats["p95"] > stats["p50"]
        assert m.get_total_queries() == 3

    def test_no_latency_returns_zero(self) -> None:
        from src.engine.metrics import MetricsCollector

        m = MetricsCollector()
        stats = m.get_latency_stats()
        assert stats["p50"] == 0.0
        assert stats["p95"] == 0.0
        assert stats["p99"] == 0.0

    def test_redaction_counting(self) -> None:
        from src.engine.metrics import MetricsCollector

        m = MetricsCollector()
        m.record_redaction(5)
        m.record_redaction(3)
        assert m.get_total_redactions() == 8

    def test_snapshot_includes_all(self) -> None:
        from src.engine.metrics import MetricsCollector

        m = MetricsCollector()
        m.record_query(15)
        snap = m.get_metrics_snapshot()
        assert "latency_ms" in snap
        assert "total_queries" in snap
        assert "total_redactions" in snap

    def test_reset_clears_all(self) -> None:
        from src.engine.metrics import MetricsCollector

        m = MetricsCollector()
        m.record_query(10)
        m.record_redaction(1)
        m.reset()
        assert m.get_total_queries() == 0
        assert m.get_total_redactions() == 0


class TestLanguageConfig:
    """Custom language configuration."""

    def test_load_defaults(self) -> None:
        from src.engine.parser import LANGUAGE_GRAMMAR_MAP, LANGUAGE_MAP

        assert len(LANGUAGE_MAP) > 0
        assert len(LANGUAGE_GRAMMAR_MAP) > 0
        assert "python" in LANGUAGE_GRAMMAR_MAP
        assert ".py" in LANGUAGE_MAP

    def test_language_config_merge(self) -> None:
        from src.engine.config import LanguageConfig

        lc = LanguageConfig(config_path=Path("/nonexistent/config.json"))
        merged = lc.merge_with_defaults({"python": {"extensions": [".py"]}})
        assert "python" in merged
        assert ".py" in merged["python"]["extensions"]

    def test_language_config_extensions_map(self) -> None:
        from src.engine.config import LanguageConfig

        lc = LanguageConfig(config_path=Path("/nonexistent/config.json"))
        lc.merge_with_defaults({"python": {"extensions": [".py"]}})
        ext_map = lc.get_extensions_map()
        assert ext_map[".py"] == "python"


# ---------------------------------------------------------------------------
# CLI edge cases
# ---------------------------------------------------------------------------


class TestCliEdgeCases:
    """Edge cases and error handling in CLI."""

    def test_index_nonexistent_path(self) -> None:
        result = _run_cs(
            ["index", "--path", "/nonexistent/path/xyz"],
            timeout=10,
            extra_env={"CODE_SEARCH_CONTEXT_DIR": "/tmp/nonexistent/.context"},
        )
        assert result.returncode != 0

    def test_search_before_index(self, tmp_path: Path) -> None:
        ctx_dir = tmp_path / ".ctx"
        result = _run_cs(
            ["search", "hello", "--context-dir", str(ctx_dir)],
            timeout=10,
        )
        assert result.returncode != 0

    def test_search_no_args_shows_usage(self) -> None:
        result = _run_cs([], timeout=5)
        assert result.returncode != 0

    def test_graph_invalid_direction(self) -> None:
        result = _run_cs(
            ["graph", "some.fqn", "--direction", "sideways"],
            timeout=5,
        )
        assert result.returncode != 0


class TestVectorIndex:
    """Vector index creation and search."""

    def test_vector_index_flat_file_format(self, repo_path: Path, indexed: dict) -> None:
        ctx = _context_dir(repo_path)
        meta_file = ctx / "vectors.meta.json"
        bin_file = ctx / "vectors.bin"
        assert meta_file.exists(), f"vectors.meta.json missing in {ctx}"
        assert bin_file.exists(), f"vectors.bin missing in {ctx}"

    def test_vector_index_metadata(self, repo_path: Path, indexed: dict) -> None:
        ctx = _context_dir(repo_path)
        meta_file = ctx / "vectors.meta.json"
        if not meta_file.exists():
            pytest.skip("No vector metadata file")
        meta = [json.loads(line) for line in meta_file.read_text().splitlines() if line.strip()]
        assert isinstance(meta, list)
        assert len(meta) > 0
        entry = meta[0]
        for key in ("vec_index", "chunk_id", "file_path", "fqn"):
            assert key in entry, f"Missing key '{key}' in vector metadata entry"


class TestCliImplementations:
    """End-to-end interface implementation lookup: index → lookup → site."""

    def test_implementations_end_to_end(self, tmp_path: Path) -> None:
        repo = tmp_path / "impl_repo"
        (repo / "src").mkdir(parents=True)
        (repo / "src" / "repository.py").write_text(
            "from abc import ABC, abstractmethod\n\n\n"
            "class Repository(ABC):\n"
            "    @abstractmethod\n"
            "    def find(self, key: str) -> str:\n"
            "        ...\n\n\n"
            "class SqlRepository(Repository):\n"
            "    def find(self, key: str) -> str:\n"
            "        return key\n"
        )

        context_dir = _context_dir(repo)
        idx = _run_cs(
            [
                "index",
                "--path",
                str(repo),
                "--force",
                "--exclude",
                _DEV_EXCLUDE,
            ],
            timeout=900,
            extra_env={"CODE_SEARCH_CONTEXT_DIR": str(context_dir)},
        )
        assert idx.returncode == 0, f"Index failed:\n{idx.stderr}"

        result = _run_cs(
            ["implementations", "Repository.find", "--context-dir", str(context_dir)],
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "SqlRepository" in result.stdout

        as_json = _run_cs(
            [
                "implementations",
                "Repository.find",
                "--json",
                "--context-dir",
                str(context_dir),
            ],
            timeout=30,
        )
        assert as_json.returncode == 0, as_json.stderr
        envelope = json.loads(as_json.stdout)
        assert envelope["outcome"] == "resolved"
        assert envelope["implementations"][0]["site"]["file_path"].endswith("repository.py")


class TestDatabaseIntegrity:
    """SQLite database integrity checks."""

    def test_graph_db_wal_mode(self, repo_path: Path, indexed: dict) -> None:
        conn = _db_connect(repo_path)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.lower() == "wal"
        finally:
            conn.close()

    def test_foreign_keys_enabled(self, repo_path: Path, indexed: dict) -> None:
        conn = _db_connect(repo_path)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            assert fk == 1
        finally:
            conn.close()

    def test_no_orphaned_chunks(self, repo_path: Path, indexed: dict) -> None:
        conn = _db_connect(repo_path)
        try:
            orphaned = conn.execute(
                "SELECT COUNT(*) AS cnt FROM code_chunks c "
                "WHERE NOT EXISTS (SELECT 1 FROM chunks_fts f WHERE f.rowid = c.id)"
            ).fetchone()["cnt"]
            assert orphaned == 0, f"Found {orphaned} chunks without FTS entries"
        finally:
            conn.close()

    def test_schema_has_all_tables(self, repo_path: Path, indexed: dict) -> None:
        conn = _db_connect(repo_path)
        try:
            tables = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            for t in ("symbols", "graph_edges", "code_chunks", "chunks_fts"):
                assert t in tables, f"Missing table '{t}'"
        finally:
            conn.close()
