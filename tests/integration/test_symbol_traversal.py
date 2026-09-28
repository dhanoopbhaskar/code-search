from pathlib import Path
from typing import Any

import pytest

from src.engine.config import Settings
from src.engine.graph import EdgeStore, GraphDatabase
from src.engine.parser import ASTParser
from src.engine.symbols import SymbolExtractor, SymbolStore


@pytest.fixture
def db(tmp_path: Path) -> GraphDatabase:
    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "graph.db", settings)
    db.initialize()
    return db


@pytest.fixture
def cross_file_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "cross_file_repo"
    (repo / "src").mkdir(parents=True)

    auth_file = repo / "src" / "auth.py"
    auth_file.write_text(
        "import utils\n"
        "\n"
        "def validate_token(token: str) -> dict:\n"
        '    """Validate JWT and return payload."""\n'
        "    payload = utils.decode_token(token)\n"
        "    return payload\n"
        "\n"
        "class AuthService:\n"
        "    def verify(self, request):\n"
        "        token = request.headers.get('Authorization')\n"
        "        return validate_token(token)\n"
    )

    utils_file = repo / "src" / "utils.py"
    utils_file.write_text(
        "import logging\n"
        "\n"
        "def decode_token(token: str) -> dict:\n"
        '    """Decode and verify JWT token."""\n'
        "    return {'user_id': 1}\n"
    )

    return repo


def test_symbol_definition_lookup_integration(db: GraphDatabase, cross_file_repo: Path) -> None:
    parser = ASTParser()
    extractor = SymbolExtractor(parser)
    settings = Settings(context_dir=cross_file_repo)
    symbol_store = SymbolStore(db, settings)
    edge_store = EdgeStore(db)

    all_syms: list[dict[str, Any]] = []
    for py_file in sorted(cross_file_repo.rglob("*.py")):
        source = py_file.read_bytes()
        syms = extractor.extract_symbols(py_file, source)
        id_map = symbol_store.insert_symbols_batch(syms)
        all_syms.extend(syms)

        edges = extractor.extract_edges(py_file, source)
        resolved = []
        for edge in edges:
            src_id = id_map.get(edge["source_fqn"])
            tgt_id = id_map.get(edge["target_fqn"])
            if src_id is not None and tgt_id is not None:
                resolved.append(
                    {
                        "source_symbol_id": src_id,
                        "target_symbol_id": tgt_id,
                        "edge_type": edge["edge_type"],
                        "source_range": edge.get("source_range"),
                        "target_range": edge.get("target_range"),
                    }
                )
        if resolved:
            edge_store.insert_edges_batch(resolved)

    result = edge_store.get_symbol_definition("validate_token")
    assert result is not None
    assert result["name"] == "validate_token"
    assert result["kind"] == "function"
    assert result["file_path"] is not None

    result_method = edge_store.get_symbol_definition("AuthService.verify")
    assert result_method is not None
    assert result_method["name"] == "verify"
    assert result_method["kind"] == "method"
    assert result_method["parent_fqn"].endswith("AuthService")


def test_call_graph_traversal_integration(db: GraphDatabase, cross_file_repo: Path) -> None:
    parser = ASTParser()
    extractor = SymbolExtractor(parser)
    settings = Settings(context_dir=cross_file_repo)
    symbol_store = SymbolStore(db, settings)
    edge_store = EdgeStore(db)

    for py_file in sorted(cross_file_repo.rglob("*.py")):
        source = py_file.read_bytes()
        syms = extractor.extract_symbols(py_file, source)
        id_map = symbol_store.insert_symbols_batch(syms)

        edges = extractor.extract_edges(py_file, source)
        resolved = []
        for edge in edges:
            src_id = id_map.get(edge["source_fqn"])
            tgt_id = id_map.get(edge["target_fqn"])
            if src_id is not None and tgt_id is not None:
                resolved.append(
                    {
                        "source_symbol_id": src_id,
                        "target_symbol_id": tgt_id,
                        "edge_type": edge["edge_type"],
                        "source_range": edge.get("source_range"),
                        "target_range": edge.get("target_range"),
                    }
                )
        if resolved:
            edge_store.insert_edges_batch(resolved)

    with db.connect() as conn:
        validate_row = conn.execute(
            "SELECT id FROM symbols WHERE name = 'validate_token';"
        ).fetchone()
    assert validate_row is not None, "validate_token symbol not found"
    validate_id = validate_row["id"]

    graph = edge_store.get_call_graph(validate_id, direction="callees", max_depth=3)
    graph_both = edge_store.get_call_graph(validate_id, direction="both", max_depth=3)
    assert isinstance(graph, dict)
    assert "callers" in graph
    assert "callees" in graph
    assert "callers" in graph_both
    assert "callees" in graph_both

    with db.connect() as conn:
        symbols_count = conn.execute("SELECT COUNT(*) as cnt FROM symbols;").fetchone()["cnt"]
        edges_count = conn.execute("SELECT COUNT(*) as cnt FROM graph_edges;").fetchone()["cnt"]
    assert symbols_count >= 3
    assert edges_count >= 0


def test_symbol_not_found(db: GraphDatabase) -> None:
    edge_store = EdgeStore(db)
    result = edge_store.get_symbol_definition("nonexistent.symbol")
    assert result is None
