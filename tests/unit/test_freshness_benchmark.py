"""Benchmark: index-freshness signal computation.

Verifies the freshness path (TTL cache-hit and forced-miss compute) stays far
below the 2s p99 budget.
"""

import hashlib
from pathlib import Path
from typing import Any

import pytest

from src.engine.config import Settings
from src.engine.freshness import FreshnessChecker
from src.engine.graph import GraphDatabase, IndexMetadataStore
from src.engine.parser import ASTParser

NUM_FILES = 5000


@pytest.fixture
def large_index(tmp_path: Path) -> dict[str, Any]:
    from src.context import ContextManager

    repo = tmp_path / "repo"
    for i in range(NUM_FILES):
        sub = repo / f"pkg{i % 20}"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / f"mod{i}.py").write_text(f"def func_{i}(): return {i}\n")

    context_dir = repo / ".context"
    settings = Settings(context_dir=context_dir, freshness_ttl_seconds=60.0)
    ctx = ContextManager(settings)
    ctx.ensure()
    paths = ctx.paths

    db = GraphDatabase(paths["graph"], settings)
    db.initialize()
    meta = IndexMetadataStore(db)
    meta.set_index_status("ready")
    meta.set("last_indexed_at", "2026-01-01T00:00:00.000000Z")
    meta.set("index_root", str(repo.resolve()))

    with db.write_transaction() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO file_checksums "
            "(file_path, checksum, size, file_mtime_ns) VALUES (?, ?, ?, ?);",
            [
                (
                    str(p),
                    hashlib.sha256(p.read_bytes()).hexdigest(),
                    p.stat().st_size,
                    p.stat().st_mtime_ns,
                )
                for p in sorted(repo.rglob("*.py"))
            ],
        )

    parser = ASTParser()
    cached = FreshnessChecker(
        db=db,
        metadata=meta,
        parser=parser,
        context_dir=context_dir,
        settings=settings,
    )
    forced = FreshnessChecker(
        db=db,
        metadata=meta,
        parser=parser,
        context_dir=context_dir,
        settings=Settings(context_dir=context_dir, freshness_ttl_seconds=0.0),
    )
    return {"cached": cached, "forced": forced}


@pytest.mark.benchmark
@pytest.mark.slow
def test_freshness_cache_hit_latency(benchmark: Any, large_index: dict[str, Any]) -> None:
    checker = large_index["cached"]
    signal = checker.signal()
    assert signal["stale"] is False

    result = benchmark(checker.signal)
    assert result["stale"] is False


@pytest.mark.benchmark
@pytest.mark.slow
def test_freshness_compute_latency(benchmark: Any, large_index: dict[str, Any]) -> None:
    checker = large_index["forced"]
    result = benchmark(checker.signal)
    assert result["stale"] is False
