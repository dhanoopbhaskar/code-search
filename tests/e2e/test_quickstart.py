"""End-to-end validation of the documented user workflows.

Each test exercises the full index-search-graph pipeline against
temporary file trees.
"""

from pathlib import Path
from typing import Any

import pytest

from src.context import ContextManager
from src.engine.audit import AuditDatabase
from src.engine.config import Settings
from src.engine.embeddings import EmbeddingGenerator, VectorIndex
from src.engine.graph import EdgeStore, GraphDatabase, IndexMetadataStore
from src.engine.indexer import IndexOrchestrator
from src.engine.parser import ASTParser
from src.engine.search import HybridSearch
from src.engine.session import SessionDatabase
from src.engine.symbols import SymbolExtractor, SymbolStore


@pytest.fixture
def e2e_components(tmp_path: Path) -> dict[str, Any]:
    repo = tmp_path / "test_repo"
    (repo / "src").mkdir(parents=True)
    calc = repo / "src" / "calc.py"
    calc.write_text(
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n"
        "\n"
        "def multiply(a: int, b: int) -> int:\n"
        "    total = 0\n"
        "    for _ in range(b):\n"
        "        total = add(total, a)\n"
        "    return total\n"
    )

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

    edge_store = EdgeStore(db)

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
        edge_store=edge_store,
    )

    search = HybridSearch(db, vector_index, embedding_gen, settings)

    return {
        "orchestrator": orchestrator,
        "search": search,
        "meta": meta,
        "db": db,
        "edge_store": edge_store,
        "repo": repo,
        "audit_db": audit_db,
    }


@pytest.mark.slow
def test_scenario_1_call_graph_returns_edges(e2e_components: dict[str, Any]) -> None:
    components = e2e_components
    components["orchestrator"].index_codebase(root_path=components["repo"], force=True)

    calc_path = f"{components['repo']}/src/calc.py"
    multiply_fqn = f"{calc_path}::multiply"
    sym = components["edge_store"].get_symbol_definition(multiply_fqn)
    assert sym is not None, f"Symbol {multiply_fqn} not found"

    graph = components["edge_store"].get_call_graph(sym["id"], direction="callees", max_depth=1)
    assert len(graph["callees"]) >= 1
    callee_fqns = [c["fqn"] for c in graph["callees"]]
    assert any("add" in fqn for fqn in callee_fqns)


@pytest.mark.slow
def test_scenario_3_audit_log_shows_duration(e2e_components: dict[str, Any]) -> None:
    components = e2e_components
    components["orchestrator"].index_codebase(root_path=components["repo"], force=True)

    audit = components["audit_db"]
    aid = audit.write_entry(
        query_type="search",
        query_summary="add",
        result_count=5,
        duration_ms=42,
    )
    assert aid > 0
    entries = audit.get_entries(limit=10)
    assert len(entries) >= 1
    assert entries[0]["duration_ms"] == 42


@pytest.mark.slow
def test_scenario_7_docstrings_multi_language(tmp_path: Path) -> None:
    repo = tmp_path / "multi_lang"
    repo.mkdir(parents=True)

    (repo / "Example.java").write_text(
        "/**\n"
        " * Adds two numbers together.\n"
        " * @param a first number\n"
        " * @param b second number\n"
        " * @return sum of a and b\n"
        " */\n"
        "public int add(int a, int b) { return a + b; }\n"
    )
    (repo / "example.js").write_text(
        "/**\n"
        " * Calculates the total from a list of numbers.\n"
        " * @param {number[]} items - the numbers to sum\n"
        " * @returns {number} the total sum\n"
        " */\n"
        "function calculateTotal(items) { return items.reduce((a, b) => a + b, 0); }\n"
    )
    (repo / "example.rs").write_text(
        "/// Returns the length of the provided string.\n"
        "fn string_length(s: &str) -> usize { s.len() }\n"
    )
    (repo / "example.cs").write_text(
        "/// <summary>Adds two integers.</summary>\n"
        '/// <param name="a">First value</param>\n'
        '/// <param name="b">Second value</param>\n'
        "/// <returns>The sum</returns>\n"
        "int Add(int a, int b) { return a + b; }\n"
    )

    context_dir = repo / ".context"
    settings = Settings(context_dir=context_dir)
    cm = ContextManager(settings)
    cm.ensure()
    paths = cm.paths

    db = GraphDatabase(paths["graph"], settings)
    db.initialize()
    meta = IndexMetadataStore(db)
    parser = ASTParser()
    extractor = SymbolExtractor(parser)
    store = SymbolStore(db, settings)
    eg = EmbeddingGenerator(settings)
    vi = VectorIndex(
        paths.get("vectors_bin", context_dir / "vectors.bin"),
        paths.get("vectors_meta", context_dir / "vectors.meta.json"),
    )
    vi.load()
    edge_store = EdgeStore(db)
    orchestrator = IndexOrchestrator(
        db=db,
        metadata_store=meta,
        parser=parser,
        symbol_extractor=extractor,
        symbol_store=store,
        embedding_generator=eg,
        vector_index=vi,
        context_dir=context_dir,
        settings=settings,
        edge_store=edge_store,
    )
    orchestrator.index_codebase(root_path=repo, force=True)

    search = HybridSearch(db, vi, eg, settings)
    for query in (
        "adds two numbers",
        "calculates the total",
        "length of the provided string",
    ):
        results = search.search(query, limit=5)["results"]
        assert len(results) >= 1, f"No results for query: {query}"


@pytest.mark.slow
def test_scenario_10_exact_fqn_lookup(tmp_path: Path) -> None:
    repo = tmp_path / "fqn_test"
    repo.mkdir(parents=True)
    (repo / "module_a.py").write_text("class Logger:\n    def log(self, msg): pass\n")
    (repo / "module_b.py").write_text("class Logger:\n    def log(self, msg): pass\n")

    context_dir = repo / ".context"
    settings = Settings(context_dir=context_dir)
    cm = ContextManager(settings)
    cm.ensure()
    paths = cm.paths

    db = GraphDatabase(paths["graph"], settings)
    db.initialize()
    meta = IndexMetadataStore(db)
    parser = ASTParser()
    extractor = SymbolExtractor(parser)
    store = SymbolStore(db, settings)
    eg = EmbeddingGenerator(settings)
    vi = VectorIndex(
        paths.get("vectors_bin", context_dir / "vectors.bin"),
        paths.get("vectors_meta", context_dir / "vectors.meta.json"),
    )
    vi.load()
    edge_store = EdgeStore(db)
    orchestrator = IndexOrchestrator(
        db=db,
        metadata_store=meta,
        parser=parser,
        symbol_extractor=extractor,
        symbol_store=store,
        embedding_generator=eg,
        vector_index=vi,
        context_dir=context_dir,
        settings=settings,
        edge_store=edge_store,
    )
    orchestrator.index_codebase(root_path=repo, force=True)

    a_fqn = f"{repo}/module_a.py::Logger"
    b_fqn = f"{repo}/module_b.py::Logger"
    sym_a = edge_store.get_symbol_definition(a_fqn)
    sym_b = edge_store.get_symbol_definition(b_fqn)
    assert sym_a is not None, f"Symbol {a_fqn} not found"
    assert sym_b is not None, f"Symbol {b_fqn} not found"
    assert sym_a["id"] != sym_b["id"]
    assert sym_a["file_path"] == f"{repo}/module_a.py"
    assert sym_b["file_path"] == f"{repo}/module_b.py"
