#!/usr/bin/env python3
"""Record graph-query baselines for a repository index.

The script builds (or reuses) an index in a scratch context directory and
measures the graph surfaces the improvement plan treats as its baseline:
``query`` at depths 2/3, ``path``, ``impact``, caller traversal, architecture,
and the index build itself. Times are wall-clock milliseconds; the JSON output
is deterministic apart from timings and paths, so two runs can be compared.

Usage:
    .venv/bin/python scripts/benchmark_graph.py --repo test-repo
    .venv/bin/python scripts/benchmark_graph.py --repo test-repo --context .bench --reuse
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
from code_search.engine.embeddings import EmbeddingGenerator, VectorIndex
from code_search.engine.graph import EdgeStore, GraphDatabase, IndexMetadataStore
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


def main() -> int:
    """Run the baseline battery and print a JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("test-repo"))
    parser.add_argument("--context", type=Path, default=None)
    parser.add_argument("--reuse", action="store_true", help="Skip indexing an existing context.")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    context_dir = args.context or Path(tempfile.mkdtemp(prefix="graph-bench-"))
    components = _build_components(args.repo.resolve(), context_dir, index=not args.reuse)
    db = components["db"]
    seed, edge, path_source, changed_file = _pick_benchmark_symbols(db)
    service = GraphQueryService(
        db,
        SymbolStore(db, components["settings"]),
        EdgeStore(db),
        components["search"],
        components["settings"],
    )
    seed_fqn = str(seed["fqn"])
    with db.connect() as conn:
        seed_id = int(
            conn.execute("SELECT id FROM symbols WHERE fqn = ?;", (seed_fqn,)).fetchone()["id"]
        )

    report: dict[str, Any] = {
        "repo": str(args.repo.resolve()),
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
            "impact_depth_3": _measure(
                lambda: service.impact([changed_file], depth=3), args.repeats
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
        },
    }
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
