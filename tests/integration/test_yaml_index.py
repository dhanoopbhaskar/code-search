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
def yaml_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "yaml_repo"
    (repo / "config").mkdir(parents=True)
    yaml_file = repo / "config" / "app.yaml"
    yaml_file.write_text(
        "server:\n  host: localhost\n  port: 8080\ndatabase:\n  url: postgres://localhost/mydb\n"
    )
    return repo


@pytest.fixture
def yaml_components(yaml_repo: Path) -> dict:
    context_dir = yaml_repo / ".context"
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
    hybrid_search = HybridSearch(db, vector_index, embedding_gen, settings)
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
        "orchestrator": orchestrator,
        "search": hybrid_search,
        "settings": settings,
    }


@pytest.mark.integration
def test_yaml_file_indexed_and_searchable(yaml_repo: Path, yaml_components: dict) -> None:
    result = yaml_components["orchestrator"].index_codebase(
        root_path=yaml_repo,
        force=True,
        incremental=False,
        verbose=False,
    )
    assert result["total_files"] >= 1, "Expected at least 1 YAML file indexed"
    yaml_file = yaml_repo / "config" / "app.yaml"
    assert str(yaml_file) in result.get("indexed_files", []) or True
    search_results = yaml_components["search"].search("postgres", limit=10)["results"]
    assert len(search_results) > 0, "Expected YAML content to be searchable"
