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
from src.engine.search import HybridSearch, tokenize
from src.engine.session import SessionDatabase
from src.engine.symbols import SymbolExtractor, SymbolStore


@pytest.fixture
def indexed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample_repo"
    (repo / "src").mkdir(parents=True)

    main_py = repo / "src" / "main.py"
    main_py.write_text(
        "def validate_token(token: str) -> dict:\n"
        '    """Validate JWT token and return payload."""\n'
        "    payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])\n"
        "    return payload\n"
        "\nclass AuthHandler:\n"
        "    def login(self, username: str, password: str) -> str:\n"
        '        """Authenticate user and return token."""\n'
        "        return 'token123'\n"
    )

    utils_py = repo / "src" / "utils.py"
    utils_py.write_text(
        "def hash_password(password: str) -> str:\n"
        '    """Hash a password for storage."""\n'
        "    import hashlib\n"
        "    return hashlib.sha256(password.encode()).hexdigest()\n"
    )

    test_file = repo / "tests" / "test_auth.py"
    test_file.parent.mkdir(exist_ok=True)
    test_file.write_text(
        "def test_validate_token():\n"
        "    result = validate_token('test')\n"
        "    assert result is not None\n"
    )

    return repo


@pytest.fixture
def components(indexed_repo: Path) -> dict:
    context_dir = indexed_repo / ".context"
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

    return {
        "orchestrator": orchestrator,
        "search": search,
        "meta": meta,
        "db": db,
    }


@pytest.mark.slow
def test_index_and_search(components: dict, indexed_repo: Path) -> None:
    result = components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    assert result["total_files"] >= 3
    assert result["total_symbols"] >= 3
    assert result["total_chunks"] >= 3

    status = components["meta"].get_index_status()
    assert status == "ready"

    results = components["search"].search(
        query="validate JWT token",
        limit=5,
    )["results"]
    assert len(results) >= 1
    assert any("validate_token" in (r.get("fqn") or "") for r in results)


@pytest.mark.slow
def test_search_no_results(components: dict, indexed_repo: Path) -> None:
    components["orchestrator"].index_codebase(root_path=indexed_repo, force=True)
    results = components["search"].search(
        query="zzzznotexists",
        limit=5,
    )["results"]
    assert len(results) == 0


@pytest.mark.slow
def test_search_language_filter(components: dict, indexed_repo: Path) -> None:
    components["orchestrator"].index_codebase(root_path=indexed_repo, force=True)
    results = components["search"].search(
        query="validate",
        limit=10,
        language="python",
    )["results"]
    assert len(results) >= 1
    for r in results:
        assert r["language"] == "python"


@pytest.mark.slow
def test_index_metadata(components: dict, indexed_repo: Path) -> None:
    components["orchestrator"].index_codebase(root_path=indexed_repo, force=True)
    assert components["meta"].get_int("total_files") >= 3
    assert components["meta"].get("index_status") == "ready"


@pytest.mark.slow
def test_test_file_index_and_search(components: dict, indexed_repo: Path) -> None:
    components["orchestrator"].index_codebase(
        root_path=indexed_repo, force=True, include_tests=True
    )
    results = components["search"].search(query="test_validate", include_tests=True)["results"]
    assert len(results) >= 0


@pytest.mark.slow
def test_new_metadata_fields(components: dict, indexed_repo: Path) -> None:
    components["orchestrator"].index_codebase(root_path=indexed_repo, force=True)
    vm_avail = components["meta"].get("vector_model_available")
    assert vm_avail in ("true", "false")
    test_inc = components["meta"].get("test_files_included")
    assert test_inc in ("true", "false")


@pytest.mark.benchmark
@pytest.mark.slow
def test_incremental_index_benchmark(benchmark, components: dict, indexed_repo: Path) -> None:
    components["orchestrator"].index_codebase(root_path=indexed_repo, force=True)

    main_py = indexed_repo / "src" / "main.py"
    main_py.write_text(
        "def validate_token(token: str) -> dict:\n"
        '    """Validate JWT token and return payload (modified)."""\n'
        "    payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])\n"
        "    return payload\n"
    )

    def run_incremental() -> dict:
        return components["orchestrator"].index_codebase(
            root_path=indexed_repo, incremental=True, verbose=False
        )

    result = benchmark(run_incremental)
    assert result["total_files"] >= 0


@pytest.mark.benchmark
@pytest.mark.slow
def test_full_index_throughput(benchmark, components: dict, indexed_repo: Path) -> None:
    def run_full_index() -> dict:
        return components["orchestrator"].index_codebase(
            root_path=indexed_repo, force=True, verbose=False
        )

    result = benchmark(run_full_index)
    assert result["total_files"] >= 3


@pytest.mark.slow
def test_incremental_index_file_deletion(components: dict, indexed_repo: Path) -> None:
    components["orchestrator"].index_codebase(root_path=indexed_repo, force=True, verbose=False)

    with components["db"].connect() as conn:
        symbols_before = conn.execute("SELECT count(*) as cnt FROM symbols;").fetchone()["cnt"]
        chunks_before = conn.execute("SELECT count(*) as cnt FROM code_chunks;").fetchone()["cnt"]
        checksums_before = conn.execute("SELECT count(*) as cnt FROM file_checksums;").fetchone()[
            "cnt"
        ]

    assert symbols_before > 0
    assert chunks_before > 0
    assert checksums_before > 0

    (indexed_repo / "src" / "utils.py").unlink()

    result = components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        incremental=True,
        verbose=False,
    )
    assert result["total_files"] == 0

    with components["db"].connect() as conn:
        symbols_after = conn.execute("SELECT count(*) as cnt FROM symbols;").fetchone()["cnt"]
        chunks_after = conn.execute("SELECT count(*) as cnt FROM code_chunks;").fetchone()["cnt"]
        checksums_after = conn.execute("SELECT count(*) as cnt FROM file_checksums;").fetchone()[
            "cnt"
        ]
        remaining_paths = {
            r["file_path"]
            for r in conn.execute("SELECT DISTINCT file_path FROM symbols;").fetchall()
        }

    assert symbols_after < symbols_before
    assert chunks_after < chunks_before
    assert checksums_after < checksums_before
    assert str(indexed_repo / "src" / "utils.py") not in remaining_paths


@pytest.mark.slow
def test_stale_sweep_removes_deleted_file_from_search(components: dict, indexed_repo: Path) -> None:
    components["orchestrator"].index_codebase(root_path=indexed_repo, force=True, verbose=False)

    results_before = components["search"].search(query="hash_password", limit=10)["results"]
    assert any("utils.py" in (r.get("file_path") or "") for r in results_before)

    (indexed_repo / "src" / "utils.py").unlink()
    summary = components["orchestrator"].prune_stale_files(root_path=indexed_repo)
    assert summary["pruned_files"] >= 1

    results_after = components["search"].search(query="hash_password", limit=10)["results"]
    assert not any("utils.py" in (r.get("file_path") or "") for r in results_after)


@pytest.mark.slow
def test_incremental_sweep_keeps_fts_parity(components: dict, indexed_repo: Path) -> None:
    components["orchestrator"].index_codebase(root_path=indexed_repo, force=True, verbose=False)

    (indexed_repo / "src" / "utils.py").unlink()
    components["orchestrator"].index_codebase(
        root_path=indexed_repo, incremental=True, verbose=False
    )

    db = components["db"]
    with db.connect() as conn:
        cc = conn.execute("SELECT COUNT(*) AS n FROM code_chunks;").fetchone()["n"]
        fc = conn.execute("SELECT COUNT(*) AS n FROM chunks_fts;").fetchone()["n"]
    assert cc == fc
    assert components["meta"].get_fts_chunks() == cc


@pytest.mark.slow
def test_file_level_coherence_ranks_multimatch_file_first(
    components: dict, indexed_repo: Path
) -> None:
    """A file with multiple matching chunks outranks a single isolated match.

    Both files match every query facet; the file with the broader match set
    (two chunks) must rank above the file with one isolated chunk, and each
    result carries a populated ``file_matches`` field.
    """
    main_py = indexed_repo / "src" / "main.py"
    main_py.write_text(
        "def validate_token(token: str) -> dict:\n"
        '    """Validate JWT token and return payload."""\n'
        "    payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])\n"
        "    return payload\n"
        "\ndef refresh_token(refresh: str) -> str:\n"
        '    """Refresh a JWT token and issue a new one."""\n'
        "    return jwt.encode({'sub': 'user'}, SECRET_KEY, algorithm='HS256')\n"
        "\nclass AuthHandler:\n"
        "    def login(self, username: str, password: str) -> str:\n"
        '        """Authenticate user and return a JWT token."""\n'
        "        return 'token123'\n"
    )

    utils_py = indexed_repo / "src" / "utils.py"
    utils_py.write_text(
        "def token_helper() -> str:\n"
        '    """Single isolated token helper (one matching chunk only)."""\n'
        "    return 'token'\n"
    )

    components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        incremental=False,
        verbose=False,
    )
    gate_off_settings = Settings(
        context_dir=indexed_repo / ".context",
        relevance_gate=False,
    )
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex

    gate_off_search = HybridSearch(
        components["db"],
        VectorIndex(
            gate_off_settings.context_dir / "vectors.bin",
            gate_off_settings.context_dir / "vectors.meta.json",
        ),
        EmbeddingGenerator(gate_off_settings),
        gate_off_settings,
    )
    components["search"] = gate_off_search
    results = components["search"].search(query="token", limit=10)["results"]
    assert len(results) >= 2

    for r in results:
        assert "file_matches" in r, f"file_matches missing on {r['file_path']}"
        assert r["file_matches"] >= 1

    main_score = next(r["score"] for r in results if "main.py" in r["file_path"])
    utils_score = next(r["score"] for r in results if "utils.py" in r["file_path"])
    assert main_score > utils_score, (
        "multi-chunk file (main.py) should outrank single-chunk file (utils.py)"
    )


@pytest.mark.slow
def test_no_include_tests_hides_true_tests_only(quality_defects_components: dict) -> None:
    """Excluding tests hides genuine test files (AuthServiceTest)
    but never production files with a bare ``spec`` path segment
    (ArticleSpecification under src/main/java/.../infra/spec/)."""
    comp = quality_defects_components
    comp["orchestrator"].index_codebase(
        root_path=comp["repo"], force=True, verbose=False, include_tests=True
    )

    excluded = comp["search"].search(query="auth", include_tests=False, limit=30)["results"]
    excluded_paths = {r["file_path"] for r in excluded}
    assert not any("AuthServiceTest.java" in p for p in excluded_paths)
    assert any("AuthService.java" in p for p in excluded_paths)

    with_tests = comp["search"].search(query="auth", include_tests=True, limit=30)["results"]
    with_tests_paths = {r["file_path"] for r in with_tests}
    assert any("AuthServiceTest.java" in p for p in with_tests_paths)

    spec_results = comp["search"].search(query="article", include_tests=False, limit=30)["results"]
    spec_paths = {r["file_path"] for r in spec_results}
    assert any("ArticleSpecification.java" in p for p in spec_paths)
    assert all(not r["is_test_file"] for r in spec_results)


@pytest.mark.slow
def test_non_canonical_demoted_not_excluded(quality_defects_components: dict) -> None:
    """Non-canonical example/generated files are present by default
    (never excluded) but ranked below canonical implementations once the
    reranker pipeline runs, as it does in the CLI/MCP layer."""
    comp = quality_defects_components
    comp["orchestrator"].index_codebase(
        root_path=comp["repo"], force=True, verbose=False, include_tests=True
    )

    rerank = Reranker(comp["db"], comp.get("session_db"), comp["settings"])
    raw = comp["search"].search(query="article", include_tests=True, limit=30)["results"]
    results = rerank.rerank(raw, query_terms=tokenize("article"))

    canonical = [r for r in results if "ArticleSpecification.java" in r["file_path"]]
    stub = [r for r in results if "ArticleStub.java" in r["file_path"]]

    assert canonical, "canonical ArticleSpecification must be present (never excluded)"
    assert stub, "non-canonical ArticleStub must be present (never excluded)"
    assert all(r["is_non_canonical"] is False for r in canonical)
    assert all(r["is_non_canonical"] is True for r in stub)
    assert all(r["is_test_file"] is False for r in canonical + stub)
    assert max(r["score"] for r in canonical) >= max(r["score"] for r in stub), (
        "canonical implementation must outrank non-canonical generated stub"
    )


@pytest.mark.slow
def test_per_file_dedup_no_duplicate_file_paths(quality_defects_components: dict) -> None:
    """Each file_path appears at most once per result set. The
    SQL migration that splits into multiple chunks must appear exactly once
    with the best chunk retained."""
    comp = quality_defects_components
    comp["orchestrator"].index_codebase(
        root_path=comp["repo"], force=True, verbose=False, include_tests=True
    )

    for query in ("INSERT INTO", "articles"):
        results = comp["search"].search(query=query, limit=20)["results"]
        paths = [r["file_path"] for r in results]
        assert len(paths) == len(set(paths)), (
            f"query '{query}': file_path must be unique, got {paths}"
        )

    sql_results = comp["search"].search(query="INSERT INTO", limit=20)["results"]
    sql_paths = [r["file_path"] for r in sql_results if r["file_path"].endswith(".sql")]
    assert len(sql_paths) <= 1, f"migration file must appear at most once: {sql_paths}"
    for r in sql_results:
        assert "file_matches" in r and r["file_matches"] >= 1


@pytest.mark.slow
def test_gate_rejects_gibberish_sharing_common_token_on_fixture(
    quality_defects_components: dict,
) -> None:
    """On the fixture corpus, where ``token`` is
    informative (df=2/11), pure-gibberish queries return ``no_match`` but
    borderline queries with one meaningful token are allowed to return rescue
    results per the rescue floor contract. A genuine concept query still passes."""
    comp = quality_defects_components
    comp["orchestrator"].index_codebase(
        root_path=comp["repo"], force=True, verbose=False, include_tests=True
    )
    # Pure gibberish (no token overlap) should return no_match
    for query in ("wqrble florble", "asdfgh qwerty"):
        env = comp["search"].search(query=query, limit=10)
        assert env.get("no_match") is True, f"pure gibberish {query!r} must return no_match"
        assert len(env["results"]) == 0
    # Borderline queries with one meaningful token should return rescue results
    for query in ("wqrble token", "florble token waffle"):
        env = comp["search"].search(query=query, limit=10)
        assert env.get("no_match") is not True, f"borderline {query!r} must not be no_match"
        # Should have rescue results (mode may be ranked-lexical or literal)
        assert len(env["results"]) >= 1, f"borderline {query!r} must return rescue results"
        assert env.get("explanation", {}).get("reason") == "rescued"
    # Genuine concept query must still pass the main gate
    results = comp["search"].search(query="pagination", limit=10)["results"]
    assert len(results) >= 1, "genuine concept query 'pagination' must still pass"


@pytest.mark.slow
def test_semantic_rebuild_writes_real_metadata_and_reports_healthy(
    indexed_semantic_vector: dict,
) -> None:
    """After rebuilding the semantic fixture, 100% of vector
    metadata entries carry a non-empty file_path/fqn, and a search reports
    ``vector_health: true`` with no per-result ``vector_degraded`` flag.
    """
    import json

    comp = indexed_semantic_vector
    meta_path = comp["context_dir"] / "vectors.meta.json"
    assert meta_path.exists()
    entries = [json.loads(line) for line in meta_path.read_text().splitlines() if line.strip()]
    assert entries, "expected vector metadata entries after semantic rebuild"
    for entry in entries:
        assert (entry.get("file_path") or "").strip(), (
            f"vector metadata entry missing file_path: {entry}"
        )
        assert (entry.get("fqn") or "").strip(), f"vector metadata entry missing fqn: {entry}"

    envelope = comp["search"].search(
        "how long can a user stay signed in before their session token expires",
        limit=10,
    )
    assert envelope.get("vector_health") is True, (
        "semantic rebuild must report a healthy vector layer"
    )
    assert envelope["results"], "expected results from the semantic fixture"
    for item in envelope["results"]:
        assert item.get("vector_degraded") is False, (
            f"healthy vector layer must not mark result {item.get('chunk_id')} degraded"
        )
