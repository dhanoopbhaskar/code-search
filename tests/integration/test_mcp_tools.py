from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastmcp")

from fastmcp import FastMCP

from src.context import ContextManager
from src.engine.audit import AuditDatabase
from src.engine.config import Settings
from src.engine.embeddings import EmbeddingGenerator, VectorIndex
from src.engine.graph import EdgeStore, GraphDatabase, IndexMetadataStore
from src.engine.indexer import IndexOrchestrator
from src.engine.metrics import MetricsCollector
from src.engine.parser import ASTParser
from src.engine.redactor import Redactor
from src.engine.reranking import Reranker
from src.engine.search import HybridSearch
from src.engine.session import SessionDatabase
from src.engine.symbols import SymbolExtractor, SymbolStore
from src.mcp.server import (
    _call_neighbors_payload,
    _definition_payload,
    _implementations_payload,
)


@pytest.fixture
def indexed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample_repo"
    (repo / "src").mkdir(parents=True)

    auth_py = repo / "src" / "auth.py"
    auth_py.write_text(
        "def validate_token(token: str) -> dict:\n"
        '    """Validate JWT token and return payload."""\n'
        '    payload = {"user": "test"}\n'
        "    return payload\n"
        "\n"
        "class AuthHandler:\n"
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
        "from src.auth import validate_token\n"
        "\ndef test_validate_token():\n"
        "    result = validate_token('test')\n"
        "    assert result is not None\n"
    )

    return repo


@pytest.fixture
def mcp_components(indexed_repo: Path) -> dict[str, Any]:
    context_dir = indexed_repo / ".context"
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

    hybrid_search = HybridSearch(db, vector_index, embedding_gen, settings)
    reranker = Reranker(db, session_db, settings)

    metrics_collector = MetricsCollector(settings)

    return {
        "db": db,
        "metadata": metadata_store,
        "edge_store": edge_store,
        "parser": parser,
        "symbol_store": symbol_store,
        "embedding_gen": embedding_gen,
        "vector_index": vector_index,
        "session_db": session_db,
        "audit_db": audit_db,
        "orchestrator": orchestrator,
        "search": hybrid_search,
        "reranker": reranker,
        "settings": settings,
        "context_dir": context_dir,
        "metrics_collector": metrics_collector,
        "redactor": Redactor(),
    }


def _freshness_envelope(comps: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    from src.engine.freshness import FreshnessChecker

    checker = comps.get("freshness")
    if checker is None:
        checker = FreshnessChecker(
            db=comps["db"],
            metadata=comps["metadata"],
            parser=comps["parser"],
            context_dir=comps["context_dir"],
            settings=comps["settings"],
        )
        comps["freshness"] = checker
    return {"results": results, "freshness": checker.signal()}


def _build_mcp_server(comps: dict[str, Any]) -> FastMCP:
    mcp: FastMCP = FastMCP("code-search")
    mc: MetricsCollector | None = comps.get("metrics_collector")
    comps.setdefault("redactor", Redactor())
    _freshness_envelope(comps, [])

    @mcp.tool()
    async def search(
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_test_files: bool = False,
        mode: str = "ranked",
        content: str = "all",
        no_model: bool = False,
    ) -> str:
        from src.engine.search import HybridSearch

        if no_model:
            hs: HybridSearch = HybridSearch(
                comps["db"],
                comps["vector_index"],
                comps["embedding_gen"],
                comps["settings"],
                no_model=True,
            )
        else:
            hs = comps["search"]
        envelope = hs.search(
            query,
            limit=limit,
            language=language,
            include_tests=include_test_files,
            mode=mode,
            content=content if content in ("code", "config", "docs", "all") else "all",
        )
        raw = envelope["results"]
        reranked = comps["reranker"].rerank(raw)
        if mc:
            mc.record_query(1.0)
        payload = _freshness_envelope(comps, reranked)
        payload["ranked_path"] = envelope.get("ranked_path")
        payload["warmup_state"] = envelope.get("warmup_state")
        if "degraded_reason" in envelope:
            payload["degraded_reason"] = envelope["degraded_reason"]
        if envelope.get("model_status") is not None:
            payload["model_status"] = envelope["model_status"]
        return json.dumps(payload, default=str)

    @mcp.tool()
    async def get_symbol_definition(symbol: str) -> str:
        if mc:
            mc.record_query(1.0)
        return _definition_payload(
            comps["symbol_store"], comps["redactor"], symbol, comps.get("freshness")
        )

    @mcp.tool()
    async def get_call_neighbors(
        symbol: str,
        direction: str = "both",
        max_depth: int = 1,
        transitive: bool = False,
    ) -> str:
        if mc:
            mc.record_query(1.0)
        return _call_neighbors_payload(
            comps["symbol_store"],
            comps["edge_store"],
            symbol,
            direction,
            max_depth,
            comps.get("freshness"),
            transitive,
        )

    @mcp.tool()
    async def find_related(
        file_path: str,
        line_number: int,
        limit: int = 5,
    ) -> str:
        from pathlib import Path

        from src.engine.paths import normalize_indexed_path, resolve_stored_path

        embedding_gen = comps["embedding_gen"]
        vector_index = comps["vector_index"]

        index_root = Path(comps["context_dir"]).parent
        stored_root = comps["metadata"].get("index_root")
        if stored_root:
            index_root = Path(stored_root)

        stored_path: str | None = None
        normalized = normalize_indexed_path(file_path, index_root)
        if normalized is not None:
            with comps["db"].connect() as conn:
                stored_path = resolve_stored_path(normalized, conn)

        if stored_path is None:
            if mc:
                mc.record_query(1.0)
            return json.dumps(
                {
                    "error": f"No indexed chunk found at '{file_path}:{line_number}'",
                    "freshness": _freshness_envelope(comps, [])["freshness"],
                }
            )

        with comps["db"].connect() as conn:
            row = conn.execute(
                "SELECT id, content FROM code_chunks "
                "WHERE file_path = ? AND line_start <= ? AND line_end >= ? LIMIT 1",
                (stored_path, line_number, line_number),
            ).fetchone()
            if row is None:
                if mc:
                    mc.record_query(1.0)
                return json.dumps(
                    {
                        "error": f"No indexed chunk found at '{file_path}:{line_number}'",
                        "freshness": _freshness_envelope(comps, [])["freshness"],
                    }
                )
            chunk_content = row["content"] or ""

        query_vec = embedding_gen.encode(chunk_content)
        if query_vec is None:
            if mc:
                mc.record_query(1.0)
            return json.dumps(_freshness_envelope(comps, []))

        search_results = vector_index.search(query_vec, top_k=limit)

        if not search_results:
            if mc:
                mc.record_query(1.0)
            return json.dumps(_freshness_envelope(comps, []))

        chunk_ids = [cid for cid, _ in search_results]
        score_map = {cid: sc for cid, sc in search_results}
        placeholders = ",".join("?" for _ in chunk_ids)
        with comps["db"].connect() as conn:
            chunk_rows = conn.execute(
                f"SELECT id, fqn, file_path, line_start, line_end, content, "
                f"language FROM code_chunks "
                f"WHERE id IN ({placeholders});",
                chunk_ids,
            ).fetchall()
        results: list[dict[str, Any]] = []
        for cr in chunk_rows:
            results.append(
                {
                    "chunk_id": cr["id"],
                    "file_path": cr["file_path"],
                    "line_start": cr["line_start"],
                    "line_end": cr["line_end"],
                    "content": cr["content"],
                    "fqn": cr["fqn"],
                    "language": cr["language"],
                    "similarity": score_map.get(cr["id"], 0.0),
                }
            )
        if mc:
            mc.record_query(1.0)
        return json.dumps(_freshness_envelope(comps, results), default=str)

    @mcp.tool()
    async def get_implementations(symbol: str) -> str:
        if mc:
            mc.record_query(1.0)
        return _implementations_payload(
            comps["symbol_store"], comps["edge_store"], symbol, comps.get("freshness")
        )

    return mcp


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_search_tool(mcp_components: dict[str, Any], indexed_repo: Path) -> None:
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    result = await mcp.call_tool("search", {"query": "validate JWT token", "limit": 5})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert isinstance(data["results"], list)
    assert len(data["results"]) >= 1
    item = data["results"][0]
    assert "chunk_id" in item
    assert "file_path" in item
    assert "content" in item
    assert "score" in item


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_search_empty_results(mcp_components: dict[str, Any], indexed_repo: Path) -> None:
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    result = await mcp.call_tool("search", {"query": "zzzznotexists"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert isinstance(data["results"], list)
    assert len(data["results"]) == 0


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_symbol_tool(mcp_components: dict[str, Any], indexed_repo: Path) -> None:
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    result = await mcp.call_tool("get_symbol_definition", {"symbol": "validate_token"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["found"] is True
    assert data["symbol"]["name"] == "validate_token"
    assert data["symbol"]["kind"] == "function"
    assert "auth.py" in data["symbol"]["file_path"]
    assert data["symbol"]["source_code"], "source_code should be populated from the file slice"


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_symbol_source_code_contains_body(
    mcp_components: dict[str, Any], indexed_repo: Path
) -> None:
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    result = await mcp.call_tool("get_symbol_definition", {"symbol": "AuthHandler.login"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["found"] is True
    assert "return 'token123'" in data["symbol"]["source_code"]


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_symbol_partial_name_resolves_scratch(
    scratch_index_components: dict[str, Any],
) -> None:
    scratch_index_components["orchestrator"].index_codebase(
        root_path=scratch_index_components["repo"],
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(scratch_index_components)

    result = await mcp.call_tool("get_symbol_definition", {"symbol": "TokenService.isTokenValid"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["found"] is True
    assert data["symbol"]["name"] == "isTokenValid"
    assert "TokenService" in data["symbol"]["file_path"]


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_symbol_ambiguous_returns_candidates(
    scratch_index_components: dict[str, Any],
) -> None:
    scratch_index_components["orchestrator"].index_codebase(
        root_path=scratch_index_components["repo"],
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(scratch_index_components)

    result = await mcp.call_tool("get_symbol_definition", {"symbol": "getBySlug"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["found"] is True
    assert data["ambiguous"] is True
    assert data["symbol"] is None
    assert isinstance(data["candidates"], list)
    assert len(data["candidates"]) >= 2
    assert all(c["name"] == "getBySlug" for c in data["candidates"])
    for cand in data["candidates"]:
        assert "fqn" in cand
        assert "file_path" in cand


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_symbol_not_found(mcp_components: dict[str, Any], indexed_repo: Path) -> None:
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    result = await mcp.call_tool("get_symbol_definition", {"symbol": "nonexistent.symbol"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["found"] is False
    assert data["symbol"] is None


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_graph_tool(mcp_components: dict[str, Any], indexed_repo: Path) -> None:
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    result = await mcp.call_tool(
        "get_call_neighbors",
        {
            "symbol": "validate_token",
            "direction": "both",
            "max_depth": 1,
        },
    )
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert "symbol" in data
    assert "callers" in data
    assert "callees" in data
    assert isinstance(data["callers"], list)
    assert isinstance(data["callees"], list)


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_graph_symbol_not_found(
    mcp_components: dict[str, Any], indexed_repo: Path
) -> None:
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    result = await mcp.call_tool("get_call_neighbors", {"symbol": "does.not.exist"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["symbol"] is None
    assert data["callers"] == []
    assert data["callees"] == []


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_call_neighbors_field_qualified_caller(
    scratch_index_components: dict[str, Any],
) -> None:
    """get_call_neighbors for TokenService.isTokenValid must return the
    field-qualified caller SecurityFilter.doFilterInternal."""
    scratch_index_components["orchestrator"].index_codebase(
        root_path=scratch_index_components["repo"],
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(scratch_index_components)

    result = await mcp.call_tool(
        "get_call_neighbors",
        {"symbol": "TokenService.isTokenValid", "direction": "callers", "max_depth": 1},
    )
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["symbol"] is not None
    callers = data["callers"]
    assert len(callers) >= 1, "Expected a caller for TokenService.isTokenValid"
    caller = callers[0]
    assert "SecurityFilter" in caller["fqn"]
    assert caller["fqn"].endswith("doFilterInternal")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_call_neighbors_service_callee(
    scratch_index_components: dict[str, Any],
) -> None:
    """get_call_neighbors for ArticleController.getBySlug must list
    ArticleService.getBySlug as a callee (not itself)."""
    scratch_index_components["orchestrator"].index_codebase(
        root_path=scratch_index_components["repo"],
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(scratch_index_components)

    result = await mcp.call_tool(
        "get_call_neighbors",
        {"symbol": "ArticleController.getBySlug", "direction": "callees", "max_depth": 1},
    )
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["symbol"] is not None
    callees = data["callees"]
    assert len(callees) >= 1
    assert any("ArticleService" in c["fqn"] for c in callees)
    assert all("ArticleController" not in c["fqn"] for c in callees)


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_find_related(mcp_components: dict[str, Any], indexed_repo: Path) -> None:
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    auth_path = str(indexed_repo / "src" / "auth.py")
    result = await mcp.call_tool(
        "find_related",
        {
            "file_path": auth_path,
            "line_number": 1,
            "limit": 3,
        },
    )
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert isinstance(data["results"], list)


@pytest.mark.integration
@pytest.mark.slow
def test_find_related_semantic_fixture_returns_related_set_excluding_anchor(
    indexed_semantic_vector: dict[str, Any],
) -> None:
    """``find_related`` returns a non-empty, related set for
    indexed locations in the semantic fixture, excluding the anchor chunk
    itself.
    """
    from src.mcp.server import _find_related_payload

    comps = indexed_semantic_vector
    repo = comps["repo"]
    anchor_file = (
        repo
        / "src"
        / "main"
        / "java"
        / "com"
        / "example"
        / "semvec"
        / "session"
        / "SessionWindowPolicy.java"
    )
    payload = _find_related_payload(comps, str(anchor_file), 9, 5)
    data = json.loads(payload)
    assert data.get("vector_health") is True, data
    results = data["results"]
    assert results, "expected a non-empty related set from the semantic fixture"
    with comps["db"].connect() as conn:
        anchor_id = conn.execute(
            "SELECT id FROM code_chunks WHERE file_path = ? AND line_start <= 9 AND line_end >= 9 "
            "LIMIT 1;",
            (str(anchor_file),),
        ).fetchone()
    assert anchor_id is not None
    returned_ids = [r["chunk_id"] for r in results]
    assert anchor_id["id"] not in returned_ids, (
        f"anchor chunk {anchor_id['id']} must be excluded, got {returned_ids}"
    )
    assert len(results) <= 5
    for item in results:
        assert all(
            k in item
            for k in (
                "chunk_id",
                "file_path",
                "line_start",
                "line_end",
                "content",
                "fqn",
                "language",
                "similarity",
            )
        )


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_find_related_not_found(
    mcp_components: dict[str, Any], indexed_repo: Path
) -> None:
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    result = await mcp.call_tool(
        "find_related",
        {
            "file_path": str(indexed_repo / "nonexistent.py"),
            "line_number": 1,
        },
    )
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert isinstance(data, dict)
    assert "error" in data


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_find_related_relative_path_matches_absolute(
    mcp_components: dict[str, Any], indexed_repo: Path
) -> None:
    """A project-relative file_path resolves to the same
    indexed location and returns the identical result set as the absolute
    form."""
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    abs_result = await mcp.call_tool(
        "find_related",
        {
            "file_path": str(indexed_repo / "src" / "auth.py"),
            "line_number": 1,
            "limit": 3,
        },
    )
    assert not abs_result.is_error
    abs_data = json.loads(abs_result.content[0].text)

    rel_result = await mcp.call_tool(
        "find_related",
        {
            "file_path": "src/auth.py",
            "line_number": 1,
            "limit": 3,
        },
    )
    assert not rel_result.is_error
    rel_data = json.loads(rel_result.content[0].text)

    assert isinstance(abs_data["results"], list)
    assert abs_data["results"] == rel_data["results"]
    assert len(abs_data["results"]) > 0, "expected at least one related chunk for the seed chunk"


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_find_related_dotdot_path_matches_absolute(
    mcp_components: dict[str, Any], indexed_repo: Path
) -> None:
    """``.``/``..`` segments are normalized before resolution."""
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    abs_result = await mcp.call_tool(
        "find_related",
        {
            "file_path": str(indexed_repo / "src" / "utils.py"),
            "line_number": 1,
            "limit": 3,
        },
    )
    abs_data = json.loads(abs_result.content[0].text)

    dot_result = await mcp.call_tool(
        "find_related",
        {
            "file_path": "./src/../src/utils.py",
            "line_number": 1,
            "limit": 3,
        },
    )
    dot_data = json.loads(dot_result.content[0].text)

    assert abs_data["results"] == dot_data["results"]


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_find_related_relative_missing_keeps_error(
    mcp_components: dict[str, Any], indexed_repo: Path
) -> None:
    """A genuinely missing file in either path form keeps the
    existing not-found outcome."""
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    result = await mcp.call_tool(
        "find_related",
        {
            "file_path": "src/does_not_exist.py",
            "line_number": 1,
        },
    )
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert isinstance(data, dict)
    assert "error" in data


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_all_five_tools_work(mcp_components: dict[str, Any], indexed_repo: Path) -> None:
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    assert tool_names == {
        "search",
        "get_symbol_definition",
        "get_call_neighbors",
        "find_related",
        "get_implementations",
    }

    for tool_name, args in [
        ("search", {"query": "hash password", "limit": 5}),
        ("get_symbol_definition", {"symbol": "AuthHandler.login"}),
        ("get_call_neighbors", {"symbol": "AuthHandler.login"}),
        ("get_implementations", {"symbol": "AuthHandler.login"}),
        ("find_related", {"file_path": str(indexed_repo / "src" / "utils.py"), "line_number": 1}),
    ]:
        result = await mcp.call_tool(tool_name, args)
        assert not result.is_error, f"Tool {tool_name} failed"
        assert result.content


@pytest.mark.integration
@pytest.mark.slow
async def test_metrics_collector_wired_in_mcp_paths(
    mcp_components: dict[str, Any], indexed_repo: Path
) -> None:
    mcp_components["metrics_collector"].reset()
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    auth_path = str(indexed_repo / "src" / "auth.py")

    await mcp.call_tool("search", {"query": "validate JWT token", "limit": 5})
    await mcp.call_tool("get_symbol_definition", {"symbol": "validate_token"})
    await mcp.call_tool("get_call_neighbors", {"symbol": "validate_token"})
    await mcp.call_tool("find_related", {"file_path": auth_path, "line_number": 1})

    mc = mcp_components["metrics_collector"]
    assert mc.get_total_queries() == 4
    stats = mc.get_latency_stats()
    assert stats["p50"] > 0
    assert stats["p95"] > 0
    assert stats["p99"] > 0


FRESHNESS_KEYS = {
    "stale",
    "stale_change_count",
    "modified_files",
    "deleted_files",
    "new_files",
    "index_age_s",
    "index_status",
    "index_root",
    "checked_at",
}


def _assert_freshness_shape(signal: dict[str, Any]) -> None:
    assert isinstance(signal, dict)
    assert set(signal.keys()) >= FRESHNESS_KEYS, (
        f"missing freshness keys: {FRESHNESS_KEYS - set(signal)}"
    )
    assert isinstance(signal["stale"], bool)
    assert isinstance(signal["stale_change_count"], int)
    assert isinstance(signal["modified_files"], int)
    assert isinstance(signal["deleted_files"], int)
    assert isinstance(signal["new_files"], int)
    assert isinstance(signal["index_status"], str)
    assert signal["checked_at"]


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_search_returns_freshness_envelope(
    mcp_components: dict[str, Any], indexed_repo: Path
) -> None:
    """Search returns the additive envelope with a full freshness signal."""
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    result = await mcp.call_tool("search", {"query": "validate JWT token", "limit": 5})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert isinstance(data, dict)
    assert "results" in data
    assert "freshness" in data
    _assert_freshness_shape(data["freshness"])


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_find_related_returns_freshness_envelope(
    mcp_components: dict[str, Any], indexed_repo: Path
) -> None:
    """find_related wraps results in the additive envelope."""
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    result = await mcp.call_tool(
        "find_related",
        {"file_path": str(indexed_repo / "src" / "auth.py"), "line_number": 1, "limit": 3},
    )
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert isinstance(data, dict)
    assert "results" in data
    assert "freshness" in data
    _assert_freshness_shape(data["freshness"])


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_find_related_not_found_carries_freshness(
    mcp_components: dict[str, Any], indexed_repo: Path
) -> None:
    """The not-found outcome keeps its error shape and gains freshness."""
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    result = await mcp.call_tool(
        "find_related",
        {"file_path": "src/does_not_exist.py", "line_number": 1},
    )
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert isinstance(data, dict)
    assert "error" in data
    assert "freshness" in data
    _assert_freshness_shape(data["freshness"])


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_symbol_returns_freshness(
    mcp_components: dict[str, Any], indexed_repo: Path
) -> None:
    """get_symbol_definition carries a top-level freshness key."""
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    result = await mcp.call_tool("get_symbol_definition", {"symbol": "validate_token"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert "freshness" in data
    _assert_freshness_shape(data["freshness"])


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_graph_returns_freshness(
    mcp_components: dict[str, Any], indexed_repo: Path
) -> None:
    """get_call_neighbors carries a top-level freshness key."""
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    result = await mcp.call_tool("get_call_neighbors", {"symbol": "validate_token"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert "freshness" in data
    _assert_freshness_shape(data["freshness"])


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_search_stale_after_modified_file(
    mcp_components: dict[str, Any], indexed_repo: Path
) -> None:
    """A content-modified indexed file flips the search freshness signal stale."""
    import dataclasses

    mcp_components["settings"] = dataclasses.replace(
        mcp_components["settings"], freshness_ttl_seconds=0.0
    )
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    (indexed_repo / "src" / "auth.py").write_text(
        "def validate_token(token: str) -> dict:\n    return {'user': 'changed'}\n"
    )
    mcp = _build_mcp_server(mcp_components)

    result = await mcp.call_tool("search", {"query": "validate JWT token", "limit": 5})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["freshness"]["stale"] is True
    assert data["freshness"]["modified_files"] >= 1
    assert data["freshness"]["stale_change_count"] >= 1


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_search_new_file_signal(
    mcp_components: dict[str, Any], indexed_repo: Path
) -> None:
    """A new discoverable file is reported via the new_files counter."""
    import dataclasses

    mcp_components["settings"] = dataclasses.replace(
        mcp_components["settings"], freshness_ttl_seconds=0.0
    )
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    (indexed_repo / "src" / "new_module.py").write_text("def brand_new(): return 42\n")
    mcp = _build_mcp_server(mcp_components)

    result = await mcp.call_tool("search", {"query": "validate JWT token", "limit": 5})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["freshness"]["stale"] is True
    assert data["freshness"]["new_files"] >= 1


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_search_content_filter_returns_only_config_chunks(tmp_path: Path) -> None:
    """The MCP ``search`` ``content`` argument scopes results to the selected
    content type: a config-scoped query returns only config chunks.
    """
    from tests.conftest import FIXTURES_DIR, _indexed_components

    repo = tmp_path / "transparency_repo"
    shutil.copytree(FIXTURES_DIR / "transparency", repo)
    comps = _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})
    comps["redactor"] = Redactor()
    from src.engine.reranking import Reranker

    comps["reranker"] = Reranker(comps["db"], comps["session_db"], comps["settings"])
    mcp = _build_mcp_server(comps)

    result = await mcp.call_tool(
        "search", {"query": "database connection pool settings", "content": "config"}
    )
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["results"], "expected config-scoped results"
    for r in data["results"]:
        assert (r.get("content_type") or "").startswith("config"), (
            f"non-config result leaked through: {r.get('file_path')}"
        )
        assert "resources" in (r.get("file_path") or "")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_search_no_model_skips_vector_model(tmp_path: Path) -> None:
    """The MCP ``search`` ``no_model`` argument runs the lexical-only fast
    path: a query returns results with the vector model skipped.
    """
    from tests.conftest import FIXTURES_DIR, _indexed_components

    repo = tmp_path / "transparency_repo"
    shutil.copytree(FIXTURES_DIR / "transparency", repo)
    comps = _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})
    comps["redactor"] = Redactor()
    from src.engine.reranking import Reranker

    comps["reranker"] = Reranker(comps["db"], comps["session_db"], comps["settings"])
    mcp = _build_mcp_server(comps)

    result = await mcp.call_tool("search", {"query": "save article", "limit": 5, "no_model": True})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert isinstance(data["results"], list)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mcp_search_reports_ranked_path_and_warmup_state(
    mcp_components: dict[str, Any], indexed_repo: Path
) -> None:
    """The MCP ranked envelope carries the additive cold-path/warmup fields."""
    mcp_components["orchestrator"].index_codebase(
        root_path=indexed_repo,
        force=True,
        verbose=False,
    )
    mcp = _build_mcp_server(mcp_components)

    result = await mcp.call_tool("search", {"query": "validate JWT token", "limit": 5})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["ranked_path"] in ("hybrid", "lexical_reduced", "lexical_degraded")
    assert data["warmup_state"] in ("cold", "warming", "warm", "failed", "disabled")
    assert "degraded_reason" in data
    assert data["model_status"] is not None
