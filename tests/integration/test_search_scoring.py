from pathlib import Path

import pytest

from src.context import ContextManager
from src.engine.config import Settings
from src.engine.embeddings import EmbeddingGenerator, VectorIndex
from src.engine.graph import GraphDatabase, IndexMetadataStore
from src.engine.indexer import IndexOrchestrator
from src.engine.parser import ASTParser
from src.engine.search import HybridSearch
from src.engine.symbols import SymbolExtractor, SymbolStore


@pytest.fixture
def dual_file_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "dual_repo"
    (repo / "src").mkdir(parents=True)
    file_a = repo / "src" / "finance.py"
    file_a.write_text("def calculate_interest(principal, rate):\n    return principal * rate\n")
    file_b = repo / "src" / "logging.py"
    file_b.write_text(
        "def setup_logging():\n    import logging\n    logging.basicConfig(level=logging.INFO)\n"
    )
    return repo


@pytest.fixture
def search_components(dual_file_repo: Path) -> dict:
    context_dir = dual_file_repo / ".context"
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
    hybrid_search = HybridSearch(db, vector_index, embedding_gen, settings)
    return {
        "db": db,
        "meta": meta,
        "orchestrator": orchestrator,
        "search": hybrid_search,
        "settings": settings,
    }


@pytest.mark.integration
@pytest.mark.integration
def test_threshold_nonsense_query_returns_empty(
    dual_file_repo: Path, search_components: dict
) -> None:
    search_components["orchestrator"].index_codebase(
        root_path=dual_file_repo,
        force=True,
        incremental=False,
        verbose=False,
    )
    results = search_components["search"].search("zzzznotexists", limit=10)["results"]
    assert len(results) == 0, "Nonsense query should return no results"


@pytest.mark.integration
def test_threshold_legitimate_query_returns_results(
    dual_file_repo: Path, search_components: dict
) -> None:
    search_components["orchestrator"].index_codebase(
        root_path=dual_file_repo,
        force=True,
        incremental=False,
        verbose=False,
    )
    results = search_components["search"].search("calculate_interest", limit=10)["results"]
    assert len(results) > 0, "Legitimate query should return results"
    for r in results:
        assert r["score"] >= 0.0


@pytest.mark.integration
def test_relevance_scoring_content_weighted(dual_file_repo: Path, search_components: dict) -> None:
    search_components["orchestrator"].index_codebase(
        root_path=dual_file_repo,
        force=True,
        incremental=False,
        verbose=False,
    )
    results = search_components["search"].search("calculate_interest", limit=10)["results"]
    assert len(results) > 0, "Expected at least one result for 'calculate_interest'"
    top_score = results[0]["score"]
    assert top_score > 0.01, f"Top score {top_score} should be > 0.01"
    scores = sorted([r["score"] for r in results], reverse=True)
    rest = scores[1:]
    median_score = rest[len(rest) // 2] if len(rest) > 1 else rest[0] if rest else 0
    if median_score > 0:
        assert top_score >= 2 * median_score, (
            f"Top score {top_score} should be >= 2x median {median_score}"
        )


@pytest.fixture
def defref_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "defref_repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "def.py").write_text(
        "def is_token_valid(token, secret):\n    return token.startswith('eyJ')\n"
    )
    (repo / "src" / "ref.py").write_text(
        "def check(request):\n    return is_token_valid(request.token, request.secret)\n"
    )
    return repo


@pytest.fixture
def defref_components(defref_repo: Path) -> dict:
    context_dir = defref_repo / ".context"
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
    hybrid_search = HybridSearch(db, vector_index, embedding_gen, settings)
    return {
        "db": db,
        "meta": meta,
        "orchestrator": orchestrator,
        "search": hybrid_search,
        "settings": settings,
    }


@pytest.mark.integration
def test_definition_above_reference(defref_repo: Path, defref_components: dict) -> None:
    """The defining chunk of the queried symbol outranks reference chunks."""
    defref_components["orchestrator"].index_codebase(
        root_path=defref_repo,
        force=True,
        incremental=False,
        verbose=False,
    )
    results = defref_components["search"].search("is_token_valid", limit=10)["results"]
    assert len(results) > 0
    top = results[0]
    assert "def.py" in top["file_path"], f"Defining chunk should rank first, got {top['file_path']}"
    assert top["is_definition"] is True
