"""Unit tests for the index-freshness signal.

The freshness signal is computed from the ``file_checksums`` stat baselines
(persisted in schema v8) with a stat fast-path: files whose stored
``size``/``file_mtime_ns`` match the on-disk stat are skipped without
re-hashing.
"""

from pathlib import Path
from typing import Any

import pytest

from src.engine.config import Settings
from src.engine.freshness import FreshnessChecker


def _build_env(tmp_path: Path, ttl: float = 0.0) -> dict[str, Any]:
    from src.context import ContextManager
    from src.engine.audit import AuditDatabase
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.graph import GraphDatabase, IndexMetadataStore
    from src.engine.indexer import IndexOrchestrator
    from src.engine.parser import ASTParser
    from src.engine.session import SessionDatabase
    from src.engine.symbols import SymbolExtractor, SymbolStore

    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "mod.py").write_text("def foo(): return 1\n")
    (repo / "src" / "bar.py").write_text("def bar(): return 2\n")
    (repo / "src" / "baz.py").write_text("def baz(): return 3\n")

    context_dir = repo / ".context"
    settings = Settings(context_dir=context_dir, freshness_ttl_seconds=ttl)
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

    session_db = SessionDatabase(paths["session"], settings)
    session_db.initialize()
    audit_db = AuditDatabase(paths["audit"])
    audit_db.initialize()

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
    result = orchestrator.index_codebase(root_path=repo, force=True, verbose=False)
    assert result["total_files"] == 3

    checker = FreshnessChecker(
        db=db,
        metadata=meta,
        parser=parser,
        context_dir=context_dir,
        settings=settings,
    )
    return {
        "repo": repo,
        "db": db,
        "metadata": meta,
        "checker": checker,
        "settings": settings,
    }


def test_clean_repo_reports_fresh(tmp_path: Path) -> None:
    env = _build_env(tmp_path)
    signal = env["checker"].signal()
    assert signal["stale"] is False
    assert signal["stale_change_count"] == 0
    assert signal["modified_files"] == 0
    assert signal["deleted_files"] == 0
    assert signal["new_files"] == 0
    assert signal["index_status"] == "ready"
    assert signal["index_age_s"] is not None
    assert signal["index_root"]
    assert signal["checked_at"]


def test_modified_file_detected(tmp_path: Path) -> None:
    env = _build_env(tmp_path)
    target = env["repo"] / "src" / "mod.py"
    target.write_text("def foo(): return 999\n")

    signal = env["checker"].signal()
    assert signal["stale"] is True
    assert signal["modified_files"] >= 1
    assert signal["stale_change_count"] == signal["modified_files"]


def test_stat_fast_path_skips_rehash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _build_env(tmp_path)

    rehash_count: list[int] = [0]
    original_read = FreshnessChecker._read_bytes

    def spy_read(path: str) -> bytes | None:
        rehash_count[0] += 1
        return original_read(path)

    monkeypatch.setattr(FreshnessChecker, "_read_bytes", staticmethod(spy_read))

    signal = env["checker"].signal()
    assert signal["stale"] is False
    assert rehash_count[0] == 0


def test_mtime_only_touch_self_heals_baseline(tmp_path: Path) -> None:
    env = _build_env(tmp_path)
    target = env["repo"] / "src" / "mod.py"
    import os
    import time as _time

    st_before = target.stat()
    _time.sleep(0.01)
    os.utime(
        target,
        ns=(st_before.st_atime_ns + 1_000_000_000, st_before.st_mtime_ns + 1_000_000_000),
    )

    signal = env["checker"].signal()
    assert signal["stale"] is False
    assert signal["modified_files"] == 0

    with env["db"].connect() as conn:
        row = conn.execute(
            "SELECT size, file_mtime_ns FROM file_checksums WHERE file_path = ?;",
            (str(target),),
        ).fetchone()
    assert row is not None
    st_after = target.stat()
    assert row["size"] == st_after.st_size
    assert row["file_mtime_ns"] == st_after.st_mtime_ns


def test_deleted_file_detected(tmp_path: Path) -> None:
    env = _build_env(tmp_path)
    (env["repo"] / "src" / "bar.py").unlink()

    signal = env["checker"].signal()
    assert signal["stale"] is True
    assert signal["deleted_files"] >= 1


def test_new_file_detected(tmp_path: Path) -> None:
    env = _build_env(tmp_path)
    (env["repo"] / "src" / "qux.py").write_text("def qux(): return 4\n")

    signal = env["checker"].signal()
    assert signal["stale"] is True
    assert signal["new_files"] >= 1


def test_ttl_cache_hit_returns_cached_signal(tmp_path: Path) -> None:
    env = _build_env(tmp_path, ttl=60.0)
    first = env["checker"].signal()
    second = env["checker"].signal()
    assert first == second
    assert first["checked_at"] == second["checked_at"]


def test_ttl_zero_always_recomputes(tmp_path: Path) -> None:
    env = _build_env(tmp_path, ttl=0.0)
    first = env["checker"].signal()
    import time as _time

    _time.sleep(0.01)
    second = env["checker"].signal()
    assert first["checked_at"] != second["checked_at"]


def test_non_ready_status_reports_truthful_lifecycle(tmp_path: Path) -> None:
    env = _build_env(tmp_path, ttl=0.0)
    env["metadata"].set_index_status("indexing")

    signal = env["checker"].signal()
    assert signal["stale"] is False
    assert signal["stale_change_count"] == 0
    assert signal["index_status"] == "indexing"


def test_mark_clean_seeds_fresh_cache(tmp_path: Path) -> None:
    env = _build_env(tmp_path, ttl=60.0)
    env["checker"].mark_clean()

    signal = env["checker"].signal()
    assert signal["stale"] is False
    assert signal["stale_change_count"] == 0


def test_missing_stat_baseline_self_heals(tmp_path: Path) -> None:
    env = _build_env(tmp_path, ttl=0.0)
    with env["db"].write_transaction() as conn:
        conn.execute(
            "UPDATE file_checksums SET size = NULL, file_mtime_ns = NULL WHERE file_path = ?;",
            (str(env["repo"] / "src" / "mod.py"),),
        )

    signal = env["checker"].signal()
    assert signal["stale"] is False

    with env["db"].connect() as conn:
        row = conn.execute(
            "SELECT size, file_mtime_ns FROM file_checksums WHERE file_path = ?;",
            (str(env["repo"] / "src" / "mod.py"),),
        ).fetchone()
    st = (env["repo"] / "src" / "mod.py").stat()
    assert row["size"] == st.st_size
    assert row["file_mtime_ns"] == st.st_mtime_ns
