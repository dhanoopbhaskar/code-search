from pathlib import Path

import pytest

from src.context import ContextManager
from src.engine.config import Settings
from src.engine.embeddings import EmbeddingGenerator, VectorIndex
from src.engine.graph import GraphDatabase, IndexMetadataStore
from src.engine.indexer import IndexOrchestrator
from src.engine.parser import ASTParser
from src.engine.symbols import SymbolExtractor, SymbolStore


@pytest.fixture
def java_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "java_repo"
    (repo / "src").mkdir(parents=True)
    java_file = repo / "src" / "TestClass.java"
    java_file.write_text(
        "public class TestClass {\n"
        "    private String name;\n"
        "    public TestClass(String name) {\n"
        "        this.name = name;\n"
        "    }\n"
        "    public void handle(int value) { }\n"
        "    public void handle(String text) { }\n"
        "}\n"
    )
    return repo


@pytest.fixture
def components(java_repo: Path) -> dict:
    context_dir = java_repo / ".context"
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
    return {
        "db": db,
        "meta": meta,
        "symbol_store": symbol_store,
        "orchestrator": orchestrator,
    }


@pytest.mark.integration
def test_java_index_all_symbol_kinds(java_repo: Path, components: dict) -> None:
    result = components["orchestrator"].index_codebase(
        root_path=java_repo,
        force=True,
        incremental=False,
        verbose=False,
    )
    assert result["total_files"] >= 1
    symbols = components["symbol_store"].lookup_by_file(str(java_repo / "src" / "TestClass.java"))
    kinds = {s["kind"] for s in symbols}
    assert "class" in kinds, f"Expected class kind, got {kinds}"
    assert "constructor" in kinds, f"Expected constructor kind, got {kinds}"
    assert "field" in kinds, f"Expected field kind, got {kinds}"
    assert "method" in kinds, f"Expected method kind, got {kinds}"


@pytest.mark.integration
def test_java_overloaded_methods_have_unique_fqns(
    java_repo: Path,
    components: dict,
) -> None:
    components["orchestrator"].index_codebase(
        root_path=java_repo,
        force=True,
        incremental=False,
        verbose=False,
    )
    symbols = components["symbol_store"].lookup_by_file(str(java_repo / "src" / "TestClass.java"))
    fqns = [s["fqn"] for s in symbols if s["kind"] == "method"]
    assert len(fqns) == len(set(fqns)), f"Duplicate FQNs found: {fqns}"


@pytest.mark.integration
def test_java_conventional_fqn_lookup(java_repo: Path, components: dict) -> None:
    repo_file = java_repo / "src" / "TestClass.java"
    repo_file.write_text(
        "package com.example;\npublic class TestClass {\n    public void handle(int value) { }\n}\n"
    )
    components["orchestrator"].index_codebase(
        root_path=java_repo,
        force=True,
        incremental=False,
        verbose=False,
    )
    result_conventional = components["symbol_store"].lookup_by_fqn(
        "com.example.TestClass.handle(int)"
    )
    assert result_conventional is not None, "Conventional FQN lookup should find the symbol"

    result_filepath = components["symbol_store"].lookup_by_fqn(
        f"{repo_file}::TestClass.handle(int)"
    )
    assert result_filepath is not None, "File-path FQN lookup should still work (backward compat)"


@pytest.mark.integration
def test_scratch_fixture_no_build_output_chunks(
    scratch_index_components: dict,
) -> None:
    repo: Path = scratch_index_components["repo"]
    db = scratch_index_components["db"]
    orchestrator = scratch_index_components["orchestrator"]

    assert (repo / "target" / "classes" / "config.properties").exists()

    result = orchestrator.index_codebase(root_path=repo, force=True, verbose=False)
    assert result["total_files"] >= 4

    with db.connect() as conn:
        target_chunks = conn.execute(
            "SELECT COUNT(*) AS n FROM code_chunks WHERE file_path LIKE '%/target/%';"
        ).fetchone()["n"]
        target_fts = conn.execute(
            "SELECT COUNT(*) AS n FROM chunks_fts WHERE file_path LIKE '%/target/%';"
        ).fetchone()["n"]

    assert target_chunks == 0
    assert target_fts == 0
    readme_rows = conn.execute(
        "SELECT content_type, chunk_type FROM code_chunks WHERE file_path LIKE '%/README.md';"
    ).fetchall()
    assert len(readme_rows) >= 1, "README.md should be indexed as prose (index_prose default)"
    for row in readme_rows:
        assert row["content_type"] == "docs"


@pytest.mark.integration
def test_scratch_fixture_fts_parity(scratch_index_components: dict) -> None:
    db = scratch_index_components["db"]
    orchestrator = scratch_index_components["orchestrator"]
    repo: Path = scratch_index_components["repo"]

    orchestrator.index_codebase(root_path=repo, force=True, verbose=False)
    with db.connect() as conn:
        cc = conn.execute("SELECT COUNT(*) AS n FROM code_chunks;").fetchone()["n"]
        fc = conn.execute("SELECT COUNT(*) AS n FROM chunks_fts;").fetchone()["n"]
    assert cc == fc


def test_every_source_file_contributes_ast_chunk(
    scratch_index_components: dict,
) -> None:
    """Every indexed source file contributes >= 1 `ast` chunk (no raw_text
    fallback for code files)."""
    db = scratch_index_components["db"]
    orchestrator = scratch_index_components["orchestrator"]
    repo: Path = scratch_index_components["repo"]

    annotation_file = (
        repo / "src" / "main" / "java" / "com" / "example" / "realworld" / "CheckSecurity.java"
    )
    annotation_file.write_text(
        "@Target({ElementType.METHOD})\n"
        "@Retention(RetentionPolicy.RUNTIME)\n"
        "public @interface CheckSecurity {\n"
        '    String value() default "";\n'
        "}\n"
    )

    result = orchestrator.index_codebase(root_path=repo, force=True, verbose=False)
    total_files = result["total_files"]
    with db.connect() as conn:
        ast_chunks = conn.execute(
            "SELECT COUNT(*) AS n FROM code_chunks WHERE chunk_type = 'ast';"
        ).fetchone()["n"]
        raw_chunks = conn.execute(
            "SELECT COUNT(*) AS n FROM code_chunks WHERE chunk_type = 'raw_text' "
            "AND content_type = 'code';"
        ).fetchone()["n"]
        files_with_ast = conn.execute(
            "SELECT COUNT(DISTINCT file_path) AS n FROM code_chunks WHERE chunk_type = 'ast';"
        ).fetchone()["n"]
        source_files = conn.execute(
            "SELECT COUNT(DISTINCT file_path) AS n FROM code_chunks WHERE content_type = 'code';"
        ).fetchone()["n"]
    assert ast_chunks >= total_files, f"Expected >= {total_files} ast chunks, got {ast_chunks}"
    assert files_with_ast == source_files, (
        f"Expected {source_files} source files with ast chunks, got {files_with_ast}"
    )
    assert raw_chunks == 0, f"Code files should not fall back to raw_text, got {raw_chunks}"


@pytest.mark.integration
def test_cross_file_calls_attach_to_service_method(
    scratch_index_components: dict,
) -> None:
    """ArticleController.getBySlug must call ArticleService.getBySlug, not the
    same-named controller method (the old ORDER BY id LIMIT 1 bug)."""
    db = scratch_index_components["db"]
    orchestrator = scratch_index_components["orchestrator"]
    repo: Path = scratch_index_components["repo"]

    orchestrator.index_codebase(root_path=repo, force=True, verbose=False)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT s1.fqn AS src, s2.fqn AS tgt FROM graph_edges e "
            "JOIN symbols s1 ON e.source_symbol_id = s1.id "
            "JOIN symbols s2 ON e.target_symbol_id = s2.id "
            "WHERE e.edge_type = 'CALLS';"
        ).fetchall()

    controller_src = next(
        (r for r in rows if r["src"].endswith("::ArticleController.getBySlug(String)")),
        None,
    )
    assert controller_src is not None, "ArticleController.getBySlug should have a CALLS edge"
    assert controller_src["tgt"].endswith("::ArticleService.getBySlug(String)"), (
        f"Edge should target ArticleService.getBySlug, got {controller_src['tgt']}"
    )

    controller_as_target = [
        r for r in rows if r["tgt"].endswith("::ArticleController.getBySlug(String)")
    ]
    assert controller_as_target == [], (
        f"No CALLS edges should target ArticleController.getBySlug, got {controller_as_target}"
    )


@pytest.mark.integration
def test_field_qualified_call_edges_present(
    scratch_index_components: dict,
) -> None:
    """SecurityFilter.doFilterInternal's field-qualified tokenService call must
    attach to TokenService.isTokenValid."""
    db = scratch_index_components["db"]
    orchestrator = scratch_index_components["orchestrator"]
    repo: Path = scratch_index_components["repo"]

    orchestrator.index_codebase(root_path=repo, force=True, verbose=False)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT s1.fqn AS src, s2.fqn AS tgt FROM graph_edges e "
            "JOIN symbols s1 ON e.source_symbol_id = s1.id "
            "JOIN symbols s2 ON e.target_symbol_id = s2.id "
            "WHERE e.edge_type = 'CALLS';"
        ).fetchall()

    filter_src = next(
        (r for r in rows if r["src"].endswith("::SecurityFilter.doFilterInternal")),
        None,
    )
    assert filter_src is not None, "SecurityFilter.doFilterInternal should have a CALLS edge"
    assert filter_src["tgt"].endswith("::TokenService.isTokenValid(String,String)"), (
        f"Edge should target TokenService.isTokenValid, got {filter_src['tgt']}"
    )


@pytest.mark.slow
def test_recursive_self_edge_preserved_after_sweep(quality_defects_components: dict) -> None:
    """DirectoryWalker.walk calling itself keeps its genuine recursive
    self-edge after the post-index validation sweep, while spurious
    same-name self-edges (isAuthenticated -> isAuthenticated) are removed."""
    comp = quality_defects_components
    comp["orchestrator"].index_codebase(
        root_path=comp["repo"], force=True, verbose=False, include_tests=True
    )
    with comp["db"].connect() as conn:
        rows = conn.execute(
            "SELECT s1.fqn AS src, s2.fqn AS tgt FROM graph_edges e "
            "JOIN symbols s1 ON e.source_symbol_id = s1.id "
            "JOIN symbols s2 ON e.target_symbol_id = s2.id "
            "WHERE e.edge_type = 'CALLS';"
        ).fetchall()

    walk_edges = [r for r in rows if r["src"].endswith("::DirectoryWalker.walk(File)")]
    assert walk_edges, "DirectoryWalker.walk should have a CALLS edge"
    assert any(r["tgt"].endswith("::DirectoryWalker.walk(File)") for r in walk_edges), (
        "genuine recursive self-call must be preserved"
    )

    auth_edges = [
        r
        for r in rows
        if r["src"].endswith("isAuthenticated") and r["tgt"].endswith("isAuthenticated")
    ]
    assert auth_edges == [], f"spurious same-name self-edges must be swept, got {auth_edges}"

    with comp["db"].connect() as conn:
        self_count = conn.execute(
            "SELECT COUNT(*) AS c FROM graph_edges WHERE source_symbol_id = target_symbol_id;"
        ).fetchone()["c"]
    assert self_count == len(walk_edges), (
        f"only genuine recursive self-calls remain, got {self_count} self-edges"
    )
