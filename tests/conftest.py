import shutil
from collections.abc import Generator, Mapping
from pathlib import Path
from typing import Any

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--keep-index",
        action="store_true",
        default=False,
        help="Keep cached index between runs (skip re-index).",
    )


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def scratch_java_repo(tmp_path: Path) -> Path:
    """A temp copy of the multi-file scratch Java fixture (indexed via IndexOrchestrator)."""
    src = FIXTURES_DIR / "scratch"
    repo = tmp_path / "scratch_repo"
    shutil.copytree(src, repo)
    return repo


def _indexed_components(
    repo: Path, context_dir: Path, settings_kwargs: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Build the shared indexed component dict for *repo*.

    Mirrors the ``trust_defects`` fixture wiring: context, graph, metadata,
    edge store, symbol store, embedding/vector machinery, and a ready
    ``HybridSearch`` bound to ``repo``'s ``.context``. Resource files are
    included so the resource-pollution regression is reproducible.

    Args:
        repo: The corpus root to index.
        context_dir: Where the ``.context`` stores live.
        settings_kwargs: Optional ``Settings`` overrides (fixtures disable
            the relevance gate so tiny synthetic corpora return the
            query-time evidence the tests assert).
    """
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

    settings = Settings(context_dir=context_dir, **(settings_kwargs or {}))
    ctx = ContextManager(settings)
    ctx.ensure()
    paths = ctx.paths

    db = GraphDatabase(paths["graph"], settings)
    db.initialize()
    metadata_store = IndexMetadataStore(db)
    edge_store = EdgeStore(db)
    parser = ASTParser()
    symbol_extractor = SymbolExtractor(parser)
    symbol_store = SymbolStore(db, settings)

    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(
        paths.get("vectors_bin", context_dir / "vectors.bin"),
        paths.get("vectors_meta", context_dir / "vectors.meta.json"),
    )
    vector_index.load()

    try:
        session_db = SessionDatabase(paths["session"], settings)
        session_db.initialize()
    except Exception:
        session_db = None

    audit_db = AuditDatabase(paths["audit"])
    audit_db.initialize()

    orchestrator = IndexOrchestrator(
        db=db,
        metadata_store=metadata_store,
        parser=parser,
        symbol_extractor=symbol_extractor,
        symbol_store=symbol_store,
        embedding_generator=embedding_gen,
        vector_index=vector_index,
        context_dir=context_dir,
        settings=settings,
        edge_store=edge_store,
    )

    result = orchestrator.index_codebase(
        root_path=repo,
        force=True,
        incremental=False,
        verbose=False,
        include_resources=True,
        resource_extensions=settings.resource_extensions,
    )

    search = HybridSearch(db, vector_index, embedding_gen, settings)

    return {
        "db": db,
        "meta": metadata_store,
        "metadata": metadata_store,
        "edge_store": edge_store,
        "parser": parser,
        "symbol_store": symbol_store,
        "embedding_gen": embedding_gen,
        "vector_index": vector_index,
        "session_db": session_db,
        "audit_db": audit_db,
        "orchestrator": orchestrator,
        "search": search,
        "settings": settings,
        "context_dir": context_dir,
        "repo": repo,
        "index_result": result,
    }


@pytest.fixture
def indexed_resource_noise(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/resource_noise/``.

    Reproduces the resource pollution: a SQL migration, XML/properties
    resources, and Java files with tiny ``field_declaration`` chunks that
    previously outranked language-typed AST chunks for Java queries.
    """
    src = FIXTURES_DIR / "resource_noise"
    repo = tmp_path / "resource_noise_repo"
    shutil.copytree(src, repo)
    return _indexed_components(repo, repo / ".context")


@pytest.fixture
def indexed_overload_symbols(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/overload_symbols/``.

    Reproduces the ``generateToken`` overloads + ``save`` overloads and
    the same-name ``save`` on ``ArticleService`` vs ``ArticleRepository``.
    """
    src = FIXTURES_DIR / "overload_symbols"
    repo = tmp_path / "overload_symbols_repo"
    shutil.copytree(src, repo)
    return _indexed_components(repo, repo / ".context")


@pytest.fixture
def indexed_pattern_queries(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/pattern_queries/``.

    Reproduces ``@Transactional readOnly = true`` (11+ occurrences),
    ``@ExceptionHandler`` (multiple handlers), and ``setToken`` definition +
    call sites — queries the plain tokenizer silently discards.
    """
    src = FIXTURES_DIR / "pattern_queries"
    repo = tmp_path / "pattern_queries_repo"
    shutil.copytree(src, repo)
    return _indexed_components(repo, repo / ".context")


# Fixtures disable the relevance gate so the tiny synthetic corpora
# return the query-time evidence (rescue/path_boost/embedded_symbol) the
# tests assert; the gate itself is covered by existing unit/integration tests.
_GATE_OFF: Mapping[str, Any] = {"relevance_gate": False, "relevance_threshold": 0.0}


@pytest.fixture
def indexed_semantic_vector(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/semantic_vector/``.

    The synthetic corpus these tests run against: per-pair
    ground-truth code whose text shares no literal keywords with the benchmark
    conceptual queries (token-expiration, email-already-registered,
    entity-to-response, disconnected-session) plus the favorite pair whose
    test-class counterpart outranks production until the test-file demotion lands.
    Built with a fresh ``.context`` per run via ``_indexed_components``.
    """
    src = FIXTURES_DIR / "semantic_vector"
    repo = tmp_path / "semantic_vector_repo"
    shutil.copytree(src, repo)
    return _indexed_components(repo, repo / ".context", settings_kwargs=_GATE_OFF)


@pytest.fixture
def indexed_multilang(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/semantic_vector_multilang/``.

    A compact multi-language corpus exercising every represented chunk kind:
    Python nested classes + free function, Java class/constructor/nested/interface/
    enum/record, TypeScript, C#, C++, plus a config resource and a docs file.
    Prose and resources are indexed so the non-code paths are represented too.
    """
    src = FIXTURES_DIR / "semantic_vector_multilang"
    repo = tmp_path / "semantic_vector_multilang_repo"
    shutil.copytree(src, repo)
    return _indexed_components(
        repo,
        repo / ".context",
        settings_kwargs={**_GATE_OFF, "index_prose": True},
    )


def _symbol_index(db: Any) -> dict[tuple[str, str, str], list[str]]:
    """Map ``(language, parent_name, name)`` to the stored FQNs.

    The interface/implementation corpus repeats logical type names across
    languages, so the language is part of the key; a method's parent name is
    the enclosing type, and a type's parent name is ``""``.
    """
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT s.fqn AS fqn, s.name AS name, s.language AS language, "
            "p.name AS parent_name "
            "FROM symbols s LEFT JOIN symbols p ON s.parent_symbol_id = p.id;"
        ).fetchall()
    index: dict[tuple[str, str, str], list[str]] = {}
    for row in rows:
        key = (row["language"] or "", row["parent_name"] or "", row["name"] or "")
        index.setdefault(key, []).append(row["fqn"])
    return index


@pytest.fixture
def indexed_implementations(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/implementations/``.

    The curated interface/implementation corpus: per-language direct
    implementers, inherited declarations, sub-interface (indirect)
    implementers, a no-static interface, ambiguous same-name methods, an
    overloaded interface, a multi-interface class, and an inner-class
    implementer. ``symbol_fqns`` maps ``(language, parent, name)`` to the
    stored FQNs so tests query exact declarations rather than guessing paths.
    """
    src = FIXTURES_DIR / "implementations"
    repo = tmp_path / "implementations_repo"
    shutil.copytree(src, repo)
    comps = _indexed_components(repo, repo / ".context")
    comps["symbol_fqns"] = _symbol_index(comps["db"])
    return comps


@pytest.fixture
def indexed_transparency(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/transparency/``.

    Reproduces the transparency failure signatures: an ``application-dev.properties``
    config chunk (pool/timeout settings plus an inline secret), markdown/prose docs,
    an overloaded ``ArticleService.save`` pair, and a framework callee
    (``repository.save``) that must surface as an unresolved edge. Prose is
    indexed by default (``index_prose`` on), the relevance gate stays on so the
    config-scent and docs paths run under production settings.
    """
    src = FIXTURES_DIR / "transparency"
    repo = tmp_path / "transparency_repo"
    shutil.copytree(src, repo)
    return _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})


@pytest.fixture
def indexed_transparency_empty(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/transparency_empty/``.

    The empty-docs-corpus variant: config resources and code but no markdown,
    so a docs-scoped query must return an explicit no-match explanation.
    """
    src = FIXTURES_DIR / "transparency_empty"
    repo = tmp_path / "transparency_empty_repo"
    shutil.copytree(src, repo)
    return _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})


@pytest.fixture
def indexed_relevance(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/relevance/``.

    The synthetic regression corpus covering every relevance failure
    signature: prose-in-code pollution (``docs/README.md``), gibberish
    no-match, authorization restriction (``@PreAuthorize`` guards), table/
    schema DDL and migration intent (``db/migration/*.sql``), a
    self-referential report artifact (``reports/code-search-vs-grep.md``),
    DTO/model scaffolding twins, near-miss literals (``public Comment save``),
    and a caller/callee pair with differing signatures. Prose is indexed by
    default (``index_prose`` on); the relevance gate stays on so the docs
    exclusion, relevance floor, and intent vocabularies run under production
    settings.
    """
    src = FIXTURES_DIR / "relevance"
    repo = tmp_path / "relevance_repo"
    shutil.copytree(src, repo)
    return _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})


@pytest.fixture
def indexed_match_boost(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/match_boost/``.

    A minimal, hermetic corpus for the filename/exact-match boosting layer:
    ``docs/README.md`` (exact filename), ``src/auth/filter.py`` and
    ``src/other/filter.py`` (equal content, one with a path match),
    ``src/config.py`` (generic stem), ``src/auth_service.py`` (production) and
    ``src/auth_service_test.py`` (test-file demotion). Prose is indexed so the
    docs-scope README case is reproducible.
    """
    src = FIXTURES_DIR / "match_boost"
    repo = tmp_path / "match_boost_repo"
    shutil.copytree(src, repo)
    return _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})


@pytest.fixture
def indexed_robustness(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/robustness/``.

    The synthetic corpus these tests run against: 8 Spring
    controllers, behavior services, model/DTO/assembler/exception plumbing
    files, an ``@PreAuthorize``-guarded method, a password-encoding concept
    (``PasswordService.encodePassword``/``PasswordEncoder``), and infra files
    (``docker-compose.yml``/``Dockerfile``/``pom.xml``/``Makefile``). The
    relevance gate stays ON so the rescue ladder and the declared-rule /
    infra passes are exercised under production settings.
    """
    src = FIXTURES_DIR / "robustness"
    repo = tmp_path / "robustness_repo"
    shutil.copytree(src, repo)
    return _indexed_components(repo, repo / ".context")


@pytest.fixture
def indexed_stem_rescue(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/stem_rescue/``.

    ``state.ts``/``state-machine.ts`` both declare ``class StateManager`` while
    ``order.py`` shares the ``order`` name but defines no ``Order`` symbol
    — the corpus the file-stem non-candidate rescue is asserted against.
    """
    src = FIXTURES_DIR / "stem_rescue"
    repo = tmp_path / "stem_rescue_repo"
    shutil.copytree(src, repo)
    return _indexed_components(repo, repo / ".context", settings_kwargs=_GATE_OFF)


@pytest.fixture
def indexed_boilerplate_merge(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/boilerplate_merge/``.

    A class with fields/imports/comments (``UserProfile.java``,
    ``user_profile.py``) and method bodies holding bare expressions
    (``trigger();`` / ``cache = build();``), a 100%-boilerplate re-export
    file (``__init__.py``), and a grammar-less file (``notes.txt``) enabled
    via ``resource_extensions`` for the whole-region fallback.
    """
    from src.engine.config import Settings

    src = FIXTURES_DIR / "boilerplate_merge"
    repo = tmp_path / "boilerplate_merge_repo"
    shutil.copytree(src, repo)
    extensions = (*Settings().resource_extensions, ".txt")
    return _indexed_components(
        repo, repo / ".context", settings_kwargs={**_GATE_OFF, "resource_extensions": extensions}
    )


@pytest.fixture
def indexed_path_penalty(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/path_penalty/``.

    Real ``auth_service.py``/``auth_middleware.py`` whose content avoids the
    query phrase, plus additional cases: ``foo.d.ts`` stub, re-export barrels
    (``__init__.py``, ``package-info.java``), and examples/legacy/compat twin
    implementations.
    """
    src = FIXTURES_DIR / "path_penalty"
    repo = tmp_path / "path_penalty_repo"
    shutil.copytree(src, repo)
    return _indexed_components(repo, repo / ".context", settings_kwargs=_GATE_OFF)


@pytest.fixture
def indexed_prose_symbols(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/prose_symbols/``.

    ``state.ts`` declares ``class StateManager``; ``payment.py`` names
    ``PaymentGateway``/``TokenRefresher`` in prose, defined in
    ``payment_gateway.py``/``token_refresh.py``.
    """
    src = FIXTURES_DIR / "prose_symbols"
    repo = tmp_path / "prose_symbols_repo"
    shutil.copytree(src, repo)
    return _indexed_components(repo, repo / ".context", settings_kwargs=_GATE_OFF)


@pytest.fixture
def quality_defects_repo(tmp_path: Path) -> Path:
    """A temp copy of the synthetic validation corpus reproducing every
    report failing case: spec-segment production file, Pageable/PageRequest,
    TokenService.isTokenValid, AuthController->AuthService, same-name
    isAuthenticated pair, recursive DirectoryWalker.walk, multi-chunk SQL
    migration, and a non-canonical generated stub."""
    src = FIXTURES_DIR / "quality_defects"
    repo = tmp_path / "quality_defects_repo"
    shutil.copytree(src, repo)
    return repo


@pytest.fixture
def trust_defects_repo(tmp_path: Path) -> Path:
    """A temp copy of the synthetic trust-defects corpus.

    Reproduces the report's exact failing cases: ``CorsConfig``/``addCorsMappings``,
    ``ArticleService.getFeedByUser`` + ``getBySlug`` + ``save`` overloads,
    ``TokenService``, ``EmailTakenException``, six ``@CheckSecurity`` controllers,
    ``FavoriteService`` (favorited query), plus resource pollution
    (``afterMigrate.sql`` -> sql, ``docker-compose.yml`` -> yaml,
    ``.opencode/opencode.json`` -> json). No websocket / ``CommentResponse``
    code exists, so E1-style absent-concept queries must return empty.
    """
    src = FIXTURES_DIR / "trust_defects"
    repo = tmp_path / "trust_defects_repo"
    shutil.copytree(src, repo)
    return repo


@pytest.fixture
def indexed_trust_defects(trust_defects_repo: Path) -> dict[str, Any]:
    """Indexed components over the trust-defects corpus, ready for search.

    Copies the fixture to a temp dir, indexes it via ``IndexOrchestrator``
    (per the existing indexed-fixture pattern), and returns the full component
    dict including the ready ``HybridSearch``. Every later integration test
    reuses this fixture.
    """
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

    context_dir = trust_defects_repo / ".context"
    settings = Settings(context_dir=context_dir)

    ctx = ContextManager(settings)
    ctx.ensure()
    paths = ctx.paths

    db = GraphDatabase(paths["graph"], settings)
    db.initialize()
    metadata_store = IndexMetadataStore(db)
    edge_store = EdgeStore(db)
    parser = ASTParser()
    symbol_extractor = SymbolExtractor(parser)
    symbol_store = SymbolStore(db, settings)

    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(
        paths.get("vectors_bin", context_dir / "vectors.bin"),
        paths.get("vectors_meta", context_dir / "vectors.meta.json"),
    )
    vector_index.load()

    try:
        session_db = SessionDatabase(paths["session"], settings)
        session_db.initialize()
    except Exception:
        session_db = None

    audit_db = AuditDatabase(paths["audit"])
    audit_db.initialize()

    orchestrator = IndexOrchestrator(
        db=db,
        metadata_store=metadata_store,
        parser=parser,
        symbol_extractor=symbol_extractor,
        symbol_store=symbol_store,
        embedding_generator=embedding_gen,
        vector_index=vector_index,
        context_dir=context_dir,
        settings=settings,
        edge_store=edge_store,
    )

    result = orchestrator.index_codebase(
        root_path=trust_defects_repo,
        force=True,
        incremental=False,
        verbose=False,
        include_resources=True,
        resource_extensions=settings.resource_extensions,
    )

    search = HybridSearch(db, vector_index, embedding_gen, settings)

    return {
        "db": db,
        "meta": metadata_store,
        "metadata": metadata_store,
        "edge_store": edge_store,
        "parser": parser,
        "symbol_store": symbol_store,
        "embedding_gen": embedding_gen,
        "vector_index": vector_index,
        "session_db": session_db,
        "audit_db": audit_db,
        "orchestrator": orchestrator,
        "search": search,
        "settings": settings,
        "context_dir": context_dir,
        "repo": trust_defects_repo,
        "index_result": result,
    }


@pytest.fixture
def quality_defects_components(quality_defects_repo: Path) -> dict[str, Any]:
    """Full index components (db, orchestrator, stores, search) wired over the
    synthetic validation corpus."""
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

    context_dir = quality_defects_repo / ".context"
    settings = Settings(context_dir=context_dir)

    ctx = ContextManager(settings)
    ctx.ensure()
    paths = ctx.paths

    db = GraphDatabase(paths["graph"], settings)
    db.initialize()
    metadata_store = IndexMetadataStore(db)
    edge_store = EdgeStore(db)
    parser = ASTParser()
    symbol_extractor = SymbolExtractor(parser)
    symbol_store = SymbolStore(db, settings)

    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(
        paths.get("vectors_bin", context_dir / "vectors.bin"),
        paths.get("vectors_meta", context_dir / "vectors.meta.json"),
    )
    vector_index.load()

    try:
        session_db = SessionDatabase(paths["session"], settings)
        session_db.initialize()
    except Exception:
        session_db = None

    audit_db = AuditDatabase(paths["audit"])
    audit_db.initialize()

    orchestrator = IndexOrchestrator(
        db=db,
        metadata_store=metadata_store,
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
        "db": db,
        "meta": metadata_store,
        "metadata": metadata_store,
        "edge_store": edge_store,
        "parser": parser,
        "symbol_store": symbol_store,
        "embedding_gen": embedding_gen,
        "vector_index": vector_index,
        "session_db": session_db,
        "audit_db": audit_db,
        "orchestrator": orchestrator,
        "search": search,
        "settings": settings,
        "context_dir": context_dir,
        "repo": quality_defects_repo,
    }


@pytest.fixture
def scratch_index_components(scratch_java_repo: Path) -> dict[str, Any]:
    """Full index components (db, orchestrator, stores, search) wired over the scratch repo."""
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

    context_dir = scratch_java_repo / ".context"
    settings = Settings(context_dir=context_dir)

    ctx = ContextManager(settings)
    ctx.ensure()
    paths = ctx.paths

    db = GraphDatabase(paths["graph"], settings)
    db.initialize()
    metadata_store = IndexMetadataStore(db)
    edge_store = EdgeStore(db)
    parser = ASTParser()
    symbol_extractor = SymbolExtractor(parser)
    symbol_store = SymbolStore(db, settings)

    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(
        paths.get("vectors_bin", context_dir / "vectors.bin"),
        paths.get("vectors_meta", context_dir / "vectors.meta.json"),
    )
    vector_index.load()

    try:
        session_db = SessionDatabase(paths["session"], settings)
        session_db.initialize()
    except Exception:
        session_db = None

    audit_db = AuditDatabase(paths["audit"])
    audit_db.initialize()

    orchestrator = IndexOrchestrator(
        db=db,
        metadata_store=metadata_store,
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
        "db": db,
        "meta": metadata_store,
        "metadata": metadata_store,
        "edge_store": edge_store,
        "parser": parser,
        "symbol_store": symbol_store,
        "embedding_gen": embedding_gen,
        "vector_index": vector_index,
        "session_db": session_db,
        "audit_db": audit_db,
        "orchestrator": orchestrator,
        "search": search,
        "settings": settings,
        "context_dir": context_dir,
        "repo": scratch_java_repo,
    }


@pytest.fixture
def temp_dir(tmp_path: Path) -> Generator[Path, Any, None]:
    yield tmp_path


@pytest.fixture
def sample_repo_path(temp_dir: Path) -> Path:
    repo = temp_dir / "sample_repo"
    (repo / "src").mkdir(parents=True)

    py_file = repo / "src" / "main.py"
    py_file.write_text(
        "def greet(name: str) -> str:\n"
        '    """Say hello."""\n'
        '    return f"Hello, {name}"\n'
        "\n\nclass Calculator:\n"
        "    def add(self, a: int, b: int) -> int:\n"
        "        return a + b\n"
    )

    js_file = repo / "src" / "app.js"
    js_file.write_text("function hello(name) {\n  return `Hello, ${name}`;\n}\n")

    java_file = repo / "src" / "Main.java"
    java_file.write_text(
        "public class Main {\n"
        "    public static void main(String[] args) {\n"
        '        System.out.println("Hello");\n'
        "    }\n"
        "}\n"
    )

    test_file = repo / "tests" / "test_main.py"
    test_file.parent.mkdir(exist_ok=True)
    test_file.write_text(
        "from src.main import greet\n"
        "\ndef test_greet():\n"
        '    assert greet("World") == "Hello, World"\n'
    )

    mock_file = repo / "tests" / "mock_utils.py"
    mock_file.write_text("class MockLogger:\n    def info(self, msg):\n        pass\n")

    return repo


@pytest.fixture
def mock_config() -> dict[str, object]:
    return {
        "rrf_k": 60,
        "max_results": 50,
        "session_ttl_hours": 24,
        "decay_constant": 0.1,
        "definition_boost": 1.2,
        "noise_penalty": 0.5,
        "non_canonical_penalty": 0.25,
        "bm25_k1": 1.5,
        "bm25_b": 0.75,
    }


@pytest.fixture
def mock_index_metadata() -> dict[str, object]:
    return {
        "last_indexed_at": "2026-07-21T12:00:00Z",
        "total_files": 1542,
        "total_symbols": 8432,
        "total_chunks": 6210,
        "languages": ["python", "typescript", "java"],
        "index_version": 1,
        "index_status": "ready",
    }
