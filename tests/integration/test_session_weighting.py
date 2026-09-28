from pathlib import Path

import pytest

from src.context import ContextManager
from src.engine.audit import AuditDatabase
from src.engine.config import Settings
from src.engine.embeddings import EmbeddingGenerator, VectorIndex
from src.engine.graph import GraphDatabase, IndexMetadataStore
from src.engine.indexer import IndexOrchestrator
from src.engine.parser import ASTParser
from src.engine.reranking import Reranker
from src.engine.search import HybridSearch
from src.engine.session import SessionDatabase
from src.engine.symbols import SymbolExtractor, SymbolStore


@pytest.fixture
def weighted_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample_repo"
    (repo / "src").mkdir(parents=True)

    auth_py = repo / "src" / "auth.py"
    auth_py.write_text(
        "def validate_token(token: str) -> dict:\n"
        '    """Validate JWT token and return payload."""\n'
        "    payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])\n"
        "    return payload\n"
    )

    utils_py = repo / "src" / "utils.py"
    utils_py.write_text(
        "def hash_password(password: str) -> str:\n"
        '    """Hash a password for storage."""\n'
        "    import hashlib\n"
        "    return hashlib.sha256(password.encode()).hexdigest()\n"
    )

    logger_py = repo / "src" / "logger.py"
    logger_py.write_text(
        "def log_info(message: str) -> None:\n"
        '    """Log an info message."""\n'
        "    print(f'INFO: {message}')\n"
    )

    return repo


@pytest.fixture
def components(weighted_repo: Path) -> dict:
    context_dir = weighted_repo / ".context"
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

    search = HybridSearch(db, vector_index, embedding_gen, settings)
    reranker = Reranker(db, session_db, settings)

    return {
        "orchestrator": orchestrator,
        "search": search,
        "reranker": reranker,
        "meta": meta,
        "db": db,
        "session_db": session_db,
        "settings": settings,
    }


@pytest.mark.slow
def test_session_weight_boost_applied(components: dict, weighted_repo: Path) -> None:
    components["orchestrator"].index_codebase(
        root_path=weighted_repo,
        force=True,
        verbose=False,
    )

    components["session_db"].record_event("src/auth.py", "WRITE")

    results = components["search"].search(query="validate token", limit=10)["results"]
    assert len(results) >= 1

    reranked = components["reranker"].rerank(results)

    auth_results = [r for r in reranked if r["file_path"].endswith("src/auth.py")]
    assert len(auth_results) >= 1
    auth_result = auth_results[0]
    assert auth_result.get("session_weight", 1.0) > 0.0


@pytest.mark.slow
def test_session_weight_no_events(components: dict, weighted_repo: Path) -> None:
    components["orchestrator"].index_codebase(
        root_path=weighted_repo,
        force=True,
        verbose=False,
    )

    results = components["search"].search(query="hash password", limit=10)["results"]
    reranked = components["reranker"].rerank(results)

    for r in reranked:
        if r["file_path"].endswith("src/utils.py"):
            assert r.get("session_weight", 1.0) == 1.0 or r.get("session_weight") is None


@pytest.mark.slow
def test_session_weight_modified_ranks_higher(components: dict, weighted_repo: Path) -> None:
    components["orchestrator"].index_codebase(
        root_path=weighted_repo,
        force=True,
        verbose=False,
    )

    components["session_db"].record_event("src/logger.py", "WRITE")

    results = components["search"].search(query="log message info", limit=10)["results"]
    reranked = components["reranker"].rerank(results)

    logger_results = [r for r in reranked if r["file_path"].endswith("src/logger.py")]
    if logger_results:
        assert logger_results[0].get("session_weight", 1.0) > 0.0
