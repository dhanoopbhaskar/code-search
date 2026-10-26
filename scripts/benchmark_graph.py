#!/usr/bin/env python3
"""Record graph-query performance baselines for a repository or a synthetic graph.

The script builds (or reuses) an index in a scratch context directory and
measures the graph surfaces used as latency baselines: ``query`` at depths 2/3,
``path``, ``impact``, caller traversal, architecture, Cypher, and the index
build itself. Times are wall-clock milliseconds; the JSON output is
deterministic apart from timings, cache counters, and paths, so two runs can be
compared.

Use ``--synthetic-symbols`` to measure the adjacency cache on a generated
graph instead of a real repository. Pass ``--repeats`` to control the sample
count; the first call of a cache-backed surface is a warm-up, so cold build
cost is reported separately by the cache stats.

Usage:
    .venv/bin/python scripts/benchmark_graph.py --repo test-repo
    .venv/bin/python scripts/benchmark_graph.py --repo test-repo --context .bench --reuse
    .venv/bin/python scripts/benchmark_graph.py --synthetic-symbols 100000
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from code_search.context import ContextManager
from code_search.engine.config import Settings
from code_search.engine.cypher import DEAD_CODE_CYPHER, execute_cypher
from code_search.engine.embeddings import EmbeddingGenerator, VectorIndex
from code_search.engine.graph import EdgeStore, GraphDatabase, IndexMetadataStore
from code_search.engine.graph_cache import adjacency_cache_stats, clear_adjacency_cache
from code_search.engine.graph_metrics import collect_graph_metrics
from code_search.engine.graph_query import GraphQueryService
from code_search.engine.indexer import IndexOrchestrator
from code_search.engine.parser import ASTParser
from code_search.engine.search import HybridSearch
from code_search.engine.symbols import SymbolExtractor, SymbolStore


def _measure(fn: Callable[[], Any], repeats: int) -> dict[str, float]:
    """Run *fn* *repeats* times and return p50/p95/min/max milliseconds."""
    timings: list[float] = []
    for _ in range(max(1, repeats)):
        started = time.perf_counter()
        fn()
        timings.append((time.perf_counter() - started) * 1000)
    ordered = sorted(timings)
    return {
        "p50_ms": round(statistics.median(ordered), 2),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 2),
        "min_ms": round(ordered[0], 2),
        "max_ms": round(ordered[-1], 2),
    }


def _build_components(repo: Path, context_dir: Path, index: bool) -> dict[str, Any]:
    """Build the engine components and optionally index *repo*."""
    settings = Settings(context_dir=context_dir)
    ctx = ContextManager(settings)
    ctx.ensure()
    paths = ctx.paths

    db = GraphDatabase(paths["graph"], settings)
    db.initialize()
    metadata = IndexMetadataStore(db)
    parser = ASTParser()
    extractor = SymbolExtractor(parser)
    symbol_store = SymbolStore(db, settings)
    embedding = EmbeddingGenerator(settings)
    vectors = VectorIndex(
        paths.get("vectors_bin", context_dir / "vectors.bin"),
        paths.get("vectors_meta", context_dir / "vectors.meta.json"),
    )
    vectors.load()
    orchestrator = IndexOrchestrator(
        db=db,
        metadata_store=metadata,
        parser=parser,
        symbol_extractor=extractor,
        symbol_store=symbol_store,
        embedding_generator=embedding,
        vector_index=vectors,
        context_dir=context_dir,
        settings=settings,
    )
    index_result: dict[str, Any] | None = None
    if index:
        started = time.perf_counter()
        index_result = orchestrator.index_codebase(
            root_path=repo,
            force=True,
            incremental=False,
            verbose=False,
            include_resources=True,
            resource_extensions=settings.resource_extensions,
        )
        index_result["wall_time_s"] = round(time.perf_counter() - started, 1)
    vectors.load()
    search = HybridSearch(db, vectors, embedding, settings)
    return {
        "db": db,
        "metadata": metadata,
        "settings": settings,
        "search": search,
        "index_result": index_result,
    }


def _build_synthetic_components(symbols: int, context_dir: Path, fanout: int = 4) -> dict[str, Any]:
    """Create a deterministic graph for adjacency-cache measurements.

    Every symbol is a function that calls up to *fanout* predecessors, so a
    six-hop path spans the whole graph and impact analysis reaches a wide
    caller set. Files hold 100 symbols and a matching ``code_chunks`` row so
    impact analysis can resolve the changed path.
    """
    settings = Settings(context_dir=context_dir)
    ctx = ContextManager(settings)
    ctx.ensure()
    paths = ctx.paths
    db = GraphDatabase(paths["graph"], settings)
    db.initialize()
    root = context_dir / "synthetic-repo"
    started = time.perf_counter()
    with db.write_transaction() as conn:
        conn.executemany(
            "INSERT INTO symbols "
            "(fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language, is_test) "
            "VALUES (?, ?, 'function', ?, ?, ?, 0, 0, 'python', 0);",
            (
                (
                    f"{root}/f{index // 100}.py::f{index}",
                    f"f{index}",
                    f"{root}/f{index // 100}.py",
                    index,
                    index + 1,
                )
                for index in range(symbols)
            ),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO graph_edges "
            "(source_symbol_id, target_symbol_id, edge_type, resolved, resolution_tier) "
            "VALUES (?, ?, 'CALLS', 1, 'exact');",
            ((index, index - 1) for index in range(2, symbols + 1)),
        )
        # Deterministic pseudo-random calls make each BFS layer wide and add
        # cycles, so a bounded path explores many nodes instead of walking a
        # narrow predecessor chain.
        conn.executemany(
            "INSERT OR IGNORE INTO graph_edges "
            "(source_symbol_id, target_symbol_id, edge_type, resolved, resolution_tier) "
            "VALUES (?, ?, 'CALLS', 1, 'exact');",
            (
                (((target * 7919 + step * 104729) % symbols) + 1, target + 1)
                for target in range(symbols)
                for step in range(1, fanout + 1)
                if ((target * 7919 + step * 104729) % symbols) != target
            ),
        )
        conn.executemany(
            "INSERT INTO code_chunks "
            "(file_path, line_start, line_end, content, language, content_type) "
            "VALUES (?, 0, 1, 'pass', 'python', 'code');",
            ((f"{root}/f{index}.py",) for index in range((symbols + 99) // 100)),
        )
        conn.execute(
            "INSERT INTO index_metadata(key, value) VALUES ('index_generation', ?);",
            (f"synthetic-{symbols}",),
        )
        conn.execute(
            "INSERT INTO index_metadata(key, value) VALUES ('index_root', ?);",
            (str(root),),
        )
        conn.execute("ANALYZE;")
    return {
        "db": db,
        "metadata": IndexMetadataStore(db),
        "settings": settings,
        "search": None,
        "index_result": {
            "synthetic_symbols": symbols,
            "wall_time_s": round(time.perf_counter() - started, 2),
        },
        "root": root,
    }


def _pick_benchmark_symbols(db: GraphDatabase) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    """Return a high-degree seed, a connected edge, and an indexed file."""
    with db.connect() as conn:
        seed = conn.execute(
            "SELECT * FROM symbols WHERE kind IN ('function','method','class') ORDER BY id LIMIT 1;"
        ).fetchone()
        edge = conn.execute(
            "SELECT s1.fqn AS source, s2.fqn AS target FROM graph_edges e "
            "JOIN symbols s1 ON s1.id = e.source_symbol_id "
            "JOIN symbols s2 ON s2.id = e.target_symbol_id "
            "WHERE e.resolved = 1 AND e.target_symbol_id IS NOT NULL "
            "ORDER BY e.id LIMIT 1;"
        ).fetchone()
        file_row = conn.execute(
            "SELECT file_path FROM code_chunks WHERE content_type = 'code' ORDER BY id LIMIT 1;"
        ).fetchone()
    if seed is None or edge is None or file_row is None:
        raise SystemExit("benchmark requires at least one symbol, resolved edge, and code chunk")
    return dict(seed), dict(edge), str(edge["source"]), str(file_row["file_path"])


def _synthetic_fqn(root: Path, index: int) -> str:
    """Return the FQN of the synthetic symbol at *index*."""
    return f"{root}/f{index // 100}.py::f{index}"


def _pick_synthetic_symbols(
    db: GraphDatabase, root: Path, symbols: int
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    """Return a connected source/target pair and the first file.

    The source is the last symbol and the target is a few predecessors back,
    so the path traverses several BFS layers and pays the per-node cost.
    """
    source_fqn = _synthetic_fqn(root, symbols - 1)
    target_fqn = _synthetic_fqn(root, max(0, symbols - 10))
    with db.connect() as conn:
        seed = conn.execute(
            "SELECT * FROM symbols ORDER BY ABS(id - ?) LIMIT 1;", (symbols // 2,)
        ).fetchone()
        edge = conn.execute("SELECT ? AS source, ? AS target;", (source_fqn, target_fqn)).fetchone()
    if seed is None or edge is None:
        raise SystemExit("synthetic graph is empty")
    return dict(seed), dict(edge), source_fqn, str(root / "f0.py")


def main() -> int:
    """Run the baseline battery and print a JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("test-repo"))
    parser.add_argument("--context", type=Path, default=None)
    parser.add_argument("--reuse", action="store_true", help="Skip indexing an existing context.")
    parser.add_argument(
        "--synthetic-symbols",
        type=int,
        default=0,
        help="Measure a generated graph of this many symbols instead of a repo.",
    )
    parser.add_argument(
        "--synthetic-fanout",
        type=int,
        default=4,
        help="Callers per synthetic symbol (default 4).",
    )
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    clear_adjacency_cache()
    context_dir = args.context or Path(tempfile.mkdtemp(prefix="graph-bench-"))
    if args.synthetic_symbols:
        components = _build_synthetic_components(
            args.synthetic_symbols, context_dir, fanout=max(1, args.synthetic_fanout)
        )
        seed, edge, path_source, changed_file = _pick_synthetic_symbols(
            components["db"], components["root"], args.synthetic_symbols
        )
    else:
        components = _build_components(args.repo.resolve(), context_dir, index=not args.reuse)
        seed, edge, path_source, changed_file = _pick_benchmark_symbols(components["db"])
    db = components["db"]
    settings = components["settings"]
    service = GraphQueryService(
        db,
        SymbolStore(db, settings),
        EdgeStore(db),
        components["search"],
        settings,
    )
    sql_only_settings = Settings(context_dir=settings.context_dir, graph_cache_enabled=False)
    sql_only_service = GraphQueryService(
        db,
        SymbolStore(db, sql_only_settings),
        EdgeStore(db),
        components["search"],
        sql_only_settings,
    )
    seed_fqn = str(seed["fqn"])
    node_label = "Function" if args.synthetic_symbols else "Method"
    anchor_name = str(seed["name"]).replace("'", "''")
    with db.connect() as conn:
        seed_id = int(
            conn.execute("SELECT id FROM symbols WHERE fqn = ?;", (seed_fqn,)).fetchone()["id"]
        )

    # Warm the snapshot and the SQL statement caches before measuring, so the
    # cold build is visible in the cache stats rather than in one outlier.
    service.shortest_path(path_source, str(edge["target"]), max_hops=6)
    service.impact([changed_file], depth=3)
    sql_only_service.shortest_path(path_source, str(edge["target"]), max_hops=6)
    sql_only_service.impact([changed_file], depth=3)

    report: dict[str, Any] = {
        "repo": str(args.repo.resolve()) if not args.synthetic_symbols else "synthetic",
        "synthetic_symbols": args.synthetic_symbols or None,
        "context_dir": str(context_dir),
        "index": components["index_result"],
        "graph": collect_graph_metrics(db),
        "benchmarks": {
            "query_depth_2": _measure(
                lambda: service.query(seed_fqn, depth=2, seeds=[seed_fqn]), args.repeats
            ),
            "query_depth_3": _measure(
                lambda: service.query(seed_fqn, depth=3, seeds=[seed_fqn]), args.repeats
            ),
            "path_6_hops": _measure(
                lambda: service.shortest_path(path_source, str(edge["target"]), max_hops=6),
                args.repeats,
            ),
            "path_6_hops_sql": _measure(
                lambda: sql_only_service.shortest_path(
                    path_source, str(edge["target"]), max_hops=6
                ),
                args.repeats,
            ),
            "impact_depth_3": _measure(
                lambda: service.impact([changed_file], depth=3), args.repeats
            ),
            "impact_depth_3_sql": _measure(
                lambda: sql_only_service.impact([changed_file], depth=3), args.repeats
            ),
            "callers_depth_1": _measure(
                lambda: EdgeStore(db).get_call_graph(seed_id, direction="callers", max_depth=1),
                args.repeats,
            ),
            "callers_depth_3": _measure(
                lambda: EdgeStore(db).get_call_graph(seed_id, direction="callers", max_depth=3),
                args.repeats,
            ),
            "architecture": _measure(lambda: service.architecture_report(top_n=15), args.repeats),
            "cypher_count": _measure(
                lambda: execute_cypher(db, "MATCH (f) RETURN count(*) AS n"),
                args.repeats,
            ),
            "cypher_one_hop": _measure(
                lambda: execute_cypher(
                    db,
                    f"MATCH (a:{node_label})-[:CALLS]->(b:{node_label}) RETURN count(*) AS n",
                ),
                args.repeats,
            ),
            "cypher_two_hops": _measure(
                lambda: execute_cypher(
                    db,
                    f"MATCH (a:{node_label})-[:CALLS*1..2]->(b:{node_label}) RETURN count(*) AS n",
                ),
                args.repeats,
            ),
            "cypher_anchored_two_hops": _measure(
                lambda: execute_cypher(
                    db,
                    f"MATCH (a:{node_label} {{name: '{anchor_name}'}})"
                    "-[:CALLS*1..2]->(b) RETURN count(*) AS n",
                ),
                args.repeats,
            ),
            "cypher_dead_code": _measure(
                lambda: execute_cypher(db, DEAD_CODE_CYPHER), args.repeats
            ),
        },
        "adjacency_cache": adjacency_cache_stats(),
    }
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
