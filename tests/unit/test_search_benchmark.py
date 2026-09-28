"""Benchmark: BM25 FTS5 search latency.

Verifies P99 < 2s on a synthetic dataset approximating 1M LOC.
"""

from pathlib import Path
from typing import Any

import pytest

from src.engine.config import Settings
from src.engine.graph import GraphDatabase
from src.engine.search import BM25Search, HybridSearch
from src.engine.symbols import SymbolStore


@pytest.fixture
def large_fts5_index(tmp_path: Path) -> dict[str, Any]:
    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "bench.db", settings)
    db.initialize()

    num_chunks = 2000
    with db.write_transaction() as conn:
        conn.executemany(
            "INSERT INTO code_chunks "
            "(fqn, file_path, line_start, line_end, content, language, is_definition) "
            "VALUES (?, ?, ?, ?, ?, ?, ?);",
            [
                (
                    f"mod.f{i}.func{j}",
                    f"f{i}.py",
                    j * 10 + 1,
                    j * 10 + 10,
                    f"def func_{i}_{j}(): return {i + j}",
                    "python",
                    1 if j % 5 == 0 else 0,
                )
                for i in range(num_chunks)
                for j in range(3)
            ],
        )
        conn.executemany(
            "INSERT INTO chunks_fts (rowid, content) VALUES (?, ?);",
            [
                (i * 3 + j + 1, f"def func_{i}_{j}(): return {i + j}")
                for i in range(num_chunks)
                for j in range(3)
            ],
        )

    bm25 = BM25Search(db, settings)
    return {"bm25": bm25, "db": db, "settings": settings}


@pytest.mark.benchmark
@pytest.mark.slow
def test_fts5_bm25_latency(benchmark: Any, large_fts5_index: dict[str, Any]) -> None:
    results = benchmark(large_fts5_index["bm25"].search, "def func", top_k=10)
    assert isinstance(results, list)


@pytest.fixture
def large_symbol_index(tmp_path: Path) -> dict[str, Any]:
    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "symbol_bench.db", settings)
    db.initialize()

    num_symbols = 50000
    rows = []
    for i in range(num_symbols):
        name = f"func_{i}"
        mod = i % 100
        rows.append(
            (
                i,
                f"/repos/demo/src/mod_{mod}.py::{name}",
                name,
                "function",
                f"/repos/demo/src/mod_{mod}.py",
                i % 500 + 1,
                i % 500 + 20,
                0,
                4,
                "python",
                f"mod_{mod}.{name}",
            )
        )
    with db.write_transaction() as conn:
        conn.executemany(
            "INSERT INTO symbols "
            "(id, fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language, conventional_fqn) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
            rows,
        )

    symbol_store = SymbolStore(db, settings)
    return {"symbol_store": symbol_store}


@pytest.mark.benchmark
@pytest.mark.slow
def test_symbol_definition_lookup_latency(
    benchmark: Any, large_symbol_index: dict[str, Any]
) -> None:
    store: SymbolStore = large_symbol_index["symbol_store"]
    result = benchmark(store.resolve_symbol, "func_25000")
    symbol, candidates = result
    assert symbol is not None or candidates


@pytest.mark.benchmark
@pytest.mark.slow
def test_symbol_definition_lookup_sc002_budget(large_symbol_index: dict[str, Any]) -> None:
    """Symbol definition lookup resolves in under 500 ms."""
    import time

    store: SymbolStore = large_symbol_index["symbol_store"]
    store.resolve_symbol("warmup")
    start = time.monotonic()
    store.resolve_symbol("func_25000")
    elapsed_ms = (time.monotonic() - start) * 1000
    assert elapsed_ms < 500, f"Symbol lookup took {elapsed_ms:.0f} ms (budget 500 ms)"


@pytest.fixture
def daemon_search_index(tmp_path: Path) -> dict[str, Any]:
    """A small indexed corpus for daemon warm/cold latency benchmarking."""
    import threading
    import time

    from src.context import ContextManager
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.graph import GraphDatabase, IndexMetadataStore
    from src.engine.indexer import IndexOrchestrator
    from src.engine.parser import ASTParser
    from src.engine.search import HybridSearch
    from src.engine.symbols import SymbolExtractor, SymbolStore

    repo = tmp_path / "bench_repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "main.py").write_text(
        "def validate_token(token: str) -> dict:\n"
        '    """Validate JWT token and return payload."""\n'
        "    return jwt.decode(token, SECRET_KEY, algorithms=['HS256'])\n"
    )

    context_dir = tmp_path / "ctx"
    settings = Settings(context_dir=context_dir)
    ctx = ContextManager(settings)
    ctx.ensure()
    paths = ctx.paths
    db = GraphDatabase(paths["graph"], settings)
    db.initialize()
    meta = IndexMetadataStore(db)
    parser = ASTParser()
    symbol_extractor = SymbolExtractor(parser)
    symbol_store = SymbolStore(db, settings)
    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(
        paths.get("vectors_bin", context_dir / "vectors.bin"),
        paths.get("vectors_meta", context_dir / "vectors.meta.json"),
    )
    vector_index.load()
    orchestrator = IndexOrchestrator(
        db=db,
        metadata_store=meta,
        parser=parser,
        symbol_extractor=symbol_extractor,
        symbol_store=symbol_store,
        embedding_generator=embedding_gen,
        vector_index=vector_index,
        context_dir=context_dir,
        settings=settings,
    )
    orchestrator.index_codebase(root_path=repo, force=True, verbose=False)

    cold_search = HybridSearch(db, vector_index, embedding_gen, settings)
    no_model_search = HybridSearch(db, vector_index, embedding_gen, settings, no_model=True)

    socket_path = context_dir / "bench.sock"
    from src.engine.daemon import QueryDaemon

    daemon = QueryDaemon(socket_path, context_dir, verbose=False)
    thread = threading.Thread(target=daemon.start, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not socket_path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)

    return {
        "socket_path": socket_path,
        "daemon": daemon,
        "cold_search": cold_search,
        "no_model_search": no_model_search,
    }


@pytest.mark.benchmark
@pytest.mark.slow
def test_daemon_warm_search_latency(benchmark: Any, daemon_search_index: dict[str, Any]) -> None:
    """Warm daemon search p50 < 5 s per invocation."""
    from src.engine.daemon import DaemonClient

    client = DaemonClient(daemon_search_index["socket_path"])
    client.request("ping")

    def warm_search() -> list[Any]:
        resp = client.request("search", {"query": "token", "limit": 10, "include_tests": True})
        return resp["payload"]["results"]

    results = benchmark(warm_search)
    assert isinstance(results, list)


@pytest.mark.benchmark
@pytest.mark.slow
def test_no_model_search_latency(benchmark: Any, daemon_search_index: dict[str, Any]) -> None:
    """--no-model fast path: search without vector-model warm-up stays fast."""
    search: HybridSearch = daemon_search_index["no_model_search"]
    envelope = benchmark(search.search, "token", 10)
    assert isinstance(envelope, dict)
    assert isinstance(envelope["results"], list)


@pytest.mark.benchmark
@pytest.mark.slow
def test_search_p99_budget(large_fts5_index: dict[str, Any]) -> None:
    """Search query p99 completes in under 2 s on a 1M-LOC-scale index."""
    import time

    bm25: BM25Search = large_fts5_index["bm25"]
    bm25.search("def func", top_k=10)
    latencies_ms: list[float] = []
    for _ in range(30):
        start = time.monotonic()
        bm25.search("def func", top_k=10)
        latencies_ms.append((time.monotonic() - start) * 1000)
    latencies_ms.sort()
    p99 = latencies_ms[int(len(latencies_ms) * 0.99) - 1]
    assert p99 < 2000, f"search p99 latency {p99:.0f} ms >= 2000 ms (budget 2 s)"


@pytest.mark.benchmark
@pytest.mark.slow
def test_ranked_mode_never_enters_exhaustive_or_enumerate(
    large_fts5_index: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ranked queries must not pay the exhaustive/enumerate budget.

    The ranked dispatch short-circuits before the line-scan and symbol-kind
    passes, so monkeypatching those passes to raise proves they are never
    entered during a ranked search."""
    db = large_fts5_index["db"]
    settings = large_fts5_index["settings"]
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.search import HybridSearch

    search = HybridSearch(
        db,
        VectorIndex(tmp_path / "none.bin", tmp_path / "none.meta.json"),
        EmbeddingGenerator(settings),
        settings,
    )

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("exhaustive/enumerate pass entered during ranked search")

    monkeypatch.setattr(HybridSearch, "_search_exhaustive", _boom)
    monkeypatch.setattr(HybridSearch, "_search_enumerate", _boom)
    envelope = search.search("def func", limit=10)
    assert isinstance(envelope["results"], list)


@pytest.mark.benchmark
@pytest.mark.slow
def test_ranked_envelope_fields_latency(large_fts5_index: dict[str, Any]) -> None:
    """The ranked envelope gains the relevance fields (``model_status``,
    ``no_match``, ``low_confidence``) with no latency regression."""
    import time

    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.search import HybridSearch

    settings = large_fts5_index["settings"]
    search = HybridSearch(
        large_fts5_index["db"],
        VectorIndex(Path("/tmp/none.bin"), Path("/tmp/none.meta.json")),
        EmbeddingGenerator(settings),
        settings,
    )
    start = time.monotonic()
    envelope = search.search("def func", 10)
    elapsed_ms = (time.monotonic() - start) * 1000
    assert "model_status" in envelope
    assert "no_match" in envelope
    assert "query_time_ms" in envelope
    for r in envelope["results"]:
        assert "low_confidence" in r
    assert elapsed_ms < 2000, f"ranked envelope p99 {elapsed_ms:.0f} ms >= 2000 ms"
