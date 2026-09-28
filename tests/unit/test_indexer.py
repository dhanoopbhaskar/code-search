import hashlib
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

from src.engine.indexer import _fallback_chunk_file, _process_file_worker


def _build_components(repo: Path) -> dict[str, Any]:
    """Wire an orchestrator over *repo* the same way the CLI does."""
    from src.context import ContextManager
    from src.engine.audit import AuditDatabase
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.graph import GraphDatabase, IndexMetadataStore
    from src.engine.indexer import IndexOrchestrator
    from src.engine.parser import ASTParser
    from src.engine.session import SessionDatabase
    from src.engine.symbols import SymbolExtractor, SymbolStore

    context_dir = repo / ".context"
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
    return {
        "db": db,
        "orchestrator": orchestrator,
        "vector_index": vector_index,
        "embedding_gen": embedding_gen,
    }


def test_batch_embed_parity_with_per_item_encode(tmp_path: Path) -> None:
    from src.engine.config import Settings
    from src.engine.embeddings import EMBEDDING_DIM, EmbeddingGenerator

    generator = EmbeddingGenerator(Settings(context_dir=tmp_path))
    texts = ["def foo(): pass", "class Bar:\n    pass", "x = 1\n", ""]
    batched = generator.encode_batch(texts)
    single = [generator.encode(t) for t in texts]
    assert len(batched) == len(texts)
    for batch_vec, single_vec in zip(batched, single, strict=True):
        if single_vec is None:
            assert batch_vec is None
        else:
            assert batch_vec is not None
            assert batch_vec.shape == single_vec.shape == (EMBEDDING_DIM,)
            assert np.allclose(batch_vec, single_vec, atol=1e-5)


def test_process_file_worker_returns_valid_data(tmp_path: Path) -> None:
    py_file = tmp_path / "test.py"
    py_file.write_text("def greet(name: str) -> str:\n    return f'Hello, {name}'\n")
    source = py_file.read_bytes()
    result = _process_file_worker((py_file, source, "python", None))
    assert "file_path" in result
    assert "symbols" in result
    assert "edges" in result
    assert "chunks" in result
    assert "content_hash" in result
    assert result["content_hash"] == hashlib.sha256(source).hexdigest()


def test_process_file_worker_empty_file(tmp_path: Path) -> None:
    py_file = tmp_path / "empty.py"
    py_file.write_text("")
    source = py_file.read_bytes()
    result = _process_file_worker((py_file, source, "python", None))
    assert result["symbols"] == []
    assert result["content_hash"] == hashlib.sha256(source).hexdigest()


def test_raw_text_chunk_indexing() -> None:
    file_path = Path("broken.py")
    source = b"def broken(\n    x = 1\n\n"
    chunks = _fallback_chunk_file(file_path, source, "python")
    assert len(chunks) == 1
    assert chunks[0]["chunk_type"] == "raw_text"
    assert chunks[0]["chunk_node_type"] == "raw_text"
    assert chunks[0]["is_definition"] is False


def test_worker_marks_unparseable_code_but_not_resource_files(tmp_path: Path) -> None:
    """A code file the AST parser cannot structure is flagged
    parse_failed, while a resource-extension file is never flagged (it is a
    data/config file, not unparseable code)."""
    code = tmp_path / "broken.py"
    code.write_text("def broken(\n    x = 1\n\n")
    result = _process_file_worker((code, code.read_bytes(), "python", None))
    assert result["parse_failed"] is True

    res = tmp_path / "config" / "app.yaml"
    res.parent.mkdir()
    res.write_text("server:\n  host: localhost\n")
    result = _process_file_worker(
        (res, res.read_bytes(), "yaml", (".xml", ".sql", ".yml", ".yaml", ".json", ".toml"))
    )
    assert result["parse_failed"] is False


def test_fallback_whole_region_for_single_line_nonempty() -> None:
    file_path = Path("solo.txt")
    source = b"hello world\n"
    chunks = _fallback_chunk_file(file_path, source, "txt")
    assert len(chunks) == 1
    assert chunks[0]["chunk_type"] == "raw_text"
    assert chunks[0]["chunk_node_type"] == "raw_text"
    assert chunks[0]["is_definition"] is False
    assert "hello world" in chunks[0]["content"]


def test_fallback_whole_region_when_blocks_are_small() -> None:
    file_path = Path("small.py")
    source = b"a = 1\n\nb = 2\n"
    chunks = _fallback_chunk_file(file_path, source, "python")
    assert len(chunks) == 1
    assert chunks[0]["chunk_node_type"] == "raw_text"
    assert "a = 1" in chunks[0]["content"]
    assert "b = 2" in chunks[0]["content"]


def test_fallback_max_line_limit() -> None:
    file_path = Path("large.py")
    lines = [f"line_{i}" for i in range(250)]
    source = "\n".join(lines).encode()
    chunks = _fallback_chunk_file(file_path, source, "python")
    assert len(chunks) >= 2
    for c in chunks:
        chunk_lines = c["line_end"] - c["line_start"] + 1
        assert chunk_lines <= 100


def test_chunk_type_metadata() -> None:
    file_path = Path("test.py")
    source = b"def foo():\n    pass\n\n"
    chunks = _fallback_chunk_file(file_path, source, "python")
    for c in chunks:
        assert "chunk_type" in c
        assert "chunk_node_type" in c


def test_content_hash_diffing_skips_unchanged_files(tmp_path: Path) -> None:
    import hashlib

    from src.context import ContextManager
    from src.engine.audit import AuditDatabase
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.graph import GraphDatabase, IndexMetadataStore
    from src.engine.indexer import IndexOrchestrator
    from src.engine.parser import ASTParser
    from src.engine.search import HybridSearch  # noqa: F401
    from src.engine.session import SessionDatabase
    from src.engine.symbols import SymbolExtractor, SymbolStore

    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "mod.py").write_text("def foo(): return 1\n")
    (repo / "src" / "bar.py").write_text("def bar(): return 2\n")

    context_dir = repo / ".context"
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

    # Full index
    result = orchestrator.index_codebase(root_path=repo, force=True, verbose=False)
    assert result["total_files"] == 2

    with db.connect() as conn:
        checksums = {
            r["file_path"]: r["checksum"]
            for r in conn.execute("SELECT file_path, checksum FROM file_checksums;").fetchall()
        }
    assert len(checksums) == 2

    # Incremental with no changes — all files should be skipped
    result = orchestrator.index_codebase(root_path=repo, incremental=True, verbose=False)
    assert result["total_files"] == 0

    # Modify one file
    (repo / "src" / "mod.py").write_text("def foo(): return 999\n")
    result = orchestrator.index_codebase(root_path=repo, incremental=True, verbose=False)
    assert result["total_files"] == 1

    # Verify checksums updated
    new_hash = hashlib.sha256(b"def foo(): return 999\n").hexdigest()
    with db.connect() as conn:
        stored = conn.execute(
            "SELECT checksum FROM file_checksums WHERE file_path = ?;",
            (str(repo / "src" / "mod.py"),),
        ).fetchone()
    assert stored is not None
    assert stored["checksum"] == new_hash


def test_content_hash_diffing_detects_orphans(tmp_path: Path) -> None:
    from src.context import ContextManager
    from src.engine.audit import AuditDatabase
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.graph import GraphDatabase, IndexMetadataStore
    from src.engine.indexer import IndexOrchestrator
    from src.engine.parser import ASTParser
    from src.engine.search import HybridSearch  # noqa: F401
    from src.engine.session import SessionDatabase
    from src.engine.symbols import SymbolExtractor, SymbolStore

    repo = tmp_path / "orphan_test"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "keep.py").write_text("def keep(): return 1\n")
    (repo / "src" / "delete_me.py").write_text("def delete(): return 2\n")

    context_dir = repo / ".context"
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

    orchestrator.index_codebase(root_path=repo, force=True, verbose=False)

    with db.connect() as conn:
        symbols_before = conn.execute("SELECT count(*) as cnt FROM symbols;").fetchone()["cnt"]
    assert symbols_before > 0

    (repo / "src" / "delete_me.py").unlink()

    result = orchestrator.index_codebase(root_path=repo, incremental=True, verbose=False)
    assert result["total_files"] == 0

    with db.connect() as conn:
        symbols_after = conn.execute("SELECT count(*) as cnt FROM symbols;").fetchone()["cnt"]
        remaining_paths = {
            r["file_path"]
            for r in conn.execute("SELECT DISTINCT file_path FROM symbols;").fetchall()
        }
    assert symbols_after < symbols_before
    assert str(repo / "src" / "delete_me.py") not in remaining_paths


def test_stale_sweep_removes_all_rows_for_deleted_file(
    scratch_index_components: dict,
) -> None:
    repo: Path = scratch_index_components["repo"]
    orchestrator = scratch_index_components["orchestrator"]
    db = scratch_index_components["db"]

    orchestrator.index_codebase(root_path=repo, force=True, verbose=False)

    deleted_file = repo / "src/main/java/com/example/realworld/model/Article.java"
    assert deleted_file.exists()

    with db.connect() as conn:
        deleted_sym_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM symbols WHERE file_path = ?;", (str(deleted_file),)
            ).fetchall()
        ]
        edges_before = conn.execute("SELECT COUNT(*) AS n FROM graph_edges;").fetchone()["n"]
    assert deleted_sym_ids

    deleted_file.unlink()

    summary = orchestrator.prune_stale_files(root_path=repo)
    assert summary["pruned_files"] >= 1

    with db.connect() as conn:
        chunk_rows = conn.execute(
            "SELECT COUNT(*) AS n FROM code_chunks WHERE file_path = ?;",
            (str(deleted_file),),
        ).fetchone()["n"]
        fts_rows = conn.execute(
            "SELECT COUNT(*) AS n FROM chunks_fts WHERE file_path = ?;",
            (str(deleted_file),),
        ).fetchone()["n"]
        sym_rows = conn.execute(
            "SELECT COUNT(*) AS n FROM symbols WHERE file_path = ?;",
            (str(deleted_file),),
        ).fetchone()["n"]
        checksum_rows = conn.execute(
            "SELECT COUNT(*) AS n FROM file_checksums WHERE file_path = ?;",
            (str(deleted_file),),
        ).fetchone()["n"]
        ph = ",".join("?" for _ in deleted_sym_ids)
        edge_rows = conn.execute(
            f"SELECT COUNT(*) AS n FROM graph_edges "
            f"WHERE source_symbol_id IN ({ph}) OR target_symbol_id IN ({ph});",
            deleted_sym_ids + deleted_sym_ids,
        ).fetchone()["n"]

    assert chunk_rows == 0
    assert fts_rows == 0
    assert sym_rows == 0
    assert checksum_rows == 0
    assert edge_rows == 0
    assert edges_before > 0


def test_incremental_stat_gate_hashes_only_changed_stat_tuples(tmp_path: Path) -> None:
    repo = tmp_path / "stat_repo"
    (repo / "src").mkdir(parents=True)
    f = repo / "src" / "mod.py"
    f.write_text("def foo(): return 1\n")
    comps = _build_components(repo)
    orch = comps["orchestrator"]
    orch.index_codebase(root_path=repo, force=True, verbose=False)

    st = f.stat()
    f.write_text("def foo(): return 2\n")
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
    result = orch.index_codebase(root_path=repo, incremental=True, verbose=False)
    assert result["total_files"] == 0

    f.write_text("def foo(): return 2\n")
    result = orch.index_codebase(root_path=repo, incremental=True, verbose=False)
    assert result["total_files"] == 1


def test_incremental_fts_parity_check_not_full_rebuild(tmp_path: Path) -> None:
    repo = tmp_path / "fts_repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "mod.py").write_text("def foo(): return 1\n")
    comps = _build_components(repo)
    orch = comps["orchestrator"]
    db = comps["db"]
    orch.index_codebase(root_path=repo, force=True, verbose=False)

    with patch.object(db, "rebuild_fts", wraps=db.rebuild_fts) as rebuild:
        (repo / "src" / "mod.py").write_text("def foo(): return 999\n")
        orch.index_codebase(root_path=repo, incremental=True, verbose=False)
    assert rebuild.call_count == 0

    with db.connect() as conn:
        code_count = conn.execute("SELECT COUNT(*) AS n FROM code_chunks;").fetchone()["n"]
        fts_count = conn.execute("SELECT COUNT(*) AS n FROM chunks_fts;").fetchone()["n"]
    assert code_count == fts_count


def test_incremental_update_equivalent_to_full_reindex(tmp_path: Path) -> None:
    repo = tmp_path / "equiv_repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "mod.py").write_text("def foo(): return 1\n")
    (repo / "src" / "bar.py").write_text("def bar(): return 2\n")
    comps = _build_components(repo)
    orch = comps["orchestrator"]
    db = comps["db"]
    vector_index = comps["vector_index"]
    embedding_gen = comps["embedding_gen"]

    orch.index_codebase(root_path=repo, force=True, verbose=False)
    (repo / "src" / "mod.py").write_text("def foo(): return 999\n")
    orch.index_codebase(root_path=repo, incremental=True, verbose=False)

    def snapshot() -> dict[str, Any]:
        with db.connect() as conn:
            chunks = conn.execute(
                "SELECT fqn, file_path, line_start, line_end, content, language, "
                "is_definition, chunk_type, chunk_node_type, subwords, tokens_checksum "
                "FROM code_chunks ORDER BY file_path, line_start;"
            ).fetchall()
            checksums = conn.execute(
                "SELECT file_path, checksum, size, file_mtime_ns "
                "FROM file_checksums ORDER BY file_path;"
            ).fetchall()
            rows = conn.execute("SELECT id, content FROM code_chunks;").fetchall()
        content_by_id = {r["id"]: r["content"] for r in rows}
        searches: dict[int, tuple[tuple[str, float], ...]] = {}
        for qi, text in enumerate(["foo", "def foo", "bar return 2"]):
            query = embedding_gen.encode(text)
            if query is None:
                continue
            searches[qi] = tuple(
                sorted(
                    (content_by_id[cid], round(score, 5))
                    for cid, score in vector_index.search(query, top_k=5)
                )
            )
        return {
            "chunks": [tuple(r) for r in chunks],
            "checksums": [tuple(r) for r in checksums],
            "searches": searches,
        }

    inc = snapshot()
    orch.index_codebase(root_path=repo, force=True, verbose=False)
    full = snapshot()

    assert inc["chunks"] == full["chunks"]
    assert inc["checksums"] == full["checksums"]
    assert inc["searches"] == full["searches"]


def test_empty_change_set_incremental_is_noop(tmp_path: Path) -> None:
    repo = tmp_path / "noop_repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "mod.py").write_text("def foo(): return 1\n")
    comps = _build_components(repo)
    orch = comps["orchestrator"]
    db = comps["db"]
    vector_index = comps["vector_index"]
    orch.index_codebase(root_path=repo, force=True, verbose=False)

    with db.connect() as conn:
        checksums_before = conn.execute(
            "SELECT file_path, checksum, size, file_mtime_ns "
            "FROM file_checksums ORDER BY file_path;"
        ).fetchall()
        chunks_before = conn.execute("SELECT COUNT(*) AS n FROM code_chunks;").fetchone()["n"]

    bin_path = vector_index._bin_path
    bin_size_before = bin_path.stat().st_size
    bin_mtime_before = bin_path.stat().st_mtime_ns

    with patch.object(db, "rebuild_fts", wraps=db.rebuild_fts) as rebuild:
        result = orch.index_codebase(root_path=repo, incremental=True, verbose=False)
    assert result["total_files"] == 0
    assert rebuild.call_count == 0
    assert bin_path.stat().st_size == bin_size_before
    assert bin_path.stat().st_mtime_ns == bin_mtime_before

    with db.connect() as conn:
        checksums_after = conn.execute(
            "SELECT file_path, checksum, size, file_mtime_ns "
            "FROM file_checksums ORDER BY file_path;"
        ).fetchall()
        chunks_after = conn.execute("SELECT COUNT(*) AS n FROM code_chunks;").fetchone()["n"]
    assert [tuple(r) for r in checksums_after] == [tuple(r) for r in checksums_before]
    assert chunks_after == chunks_before


def test_indexer_writes_nonempty_file_path_and_fqn_to_vector_metadata(tmp_path: Path) -> None:
    import json

    repo = tmp_path / "meta_repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "mod.py").write_text("def foo(): return 1\n")
    (repo / "src" / "bar.py").write_text("def bar(): return 2\n")
    comps = _build_components(repo)
    orch = comps["orchestrator"]
    orch.index_codebase(root_path=repo, force=True, verbose=False)

    meta_path = repo / ".context" / "vectors.meta.json"
    assert meta_path.exists()
    entries = [json.loads(line) for line in meta_path.read_text().splitlines() if line.strip()]
    assert entries, "expected indexed vector metadata entries"
    real_paths = {str(repo / "src" / "mod.py"), str(repo / "src" / "bar.py")}
    for entry in entries:
        file_path = entry.get("file_path") or ""
        fqn = entry.get("fqn") or ""
        assert file_path.strip(), "vector metadata entry missing file_path"
        assert fqn.strip(), "vector metadata entry missing fqn"
        assert file_path in real_paths, f"file_path {file_path!r} not from indexed repo"
