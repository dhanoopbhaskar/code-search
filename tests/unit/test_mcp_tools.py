"""Unit tests for ``find_related`` correctness.

Drives the extracted ``_find_related_payload`` against a real graph DB and
vector index so the self-match exclusion and the
vector-layer-unavailable status are asserted without the full MCP
transport. The embedding model is mocked only where needed;
the exclusion test uses real embeddings over a populated index.
"""

from __future__ import annotations

from typing import Any

from src.engine.redactor import Redactor
from src.mcp.server import _find_related_payload


def _indexed_components_unit(tmp_path: Any, n_chunks: int = 2) -> dict[str, Any]:
    """A minimal component registry with a real graph DB + vector index.

    By default two chunks (``a.py``, ``b.py``) are inserted and embedded with
    the real model so ``find_related`` on one of them has a genuine neighbour
    to return; ``n_chunks=1`` builds the single-chunk index used to assert
    the no-candidates-after-self-match-exclusion status.
    """
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.graph import GraphDatabase, IndexMetadataStore

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "test.db", settings)
    db.initialize()
    chunks = (
        ("mod.a", "a.py", "def connect(): return 'session'"),
        ("mod.b", "b.py", "def disconnect(): return 'gone'"),
    )[:n_chunks]
    with db.write_transaction() as conn:
        for i, (fqn, filename, content) in enumerate(chunks, start=1):
            path = str(tmp_path / filename)
            conn.execute(
                "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
                "content, language) VALUES (?, ?, ?, ?, ?, ?);",
                (fqn, path, 1, 2, content, "python"),
            )
            conn.execute("INSERT INTO chunks_fts (rowid, content) VALUES (?, ?);", (i, content))

    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(tmp_path / "v.bin", tmp_path / "v.meta.json")
    vector_index.load()
    for i, (fqn, filename, content) in enumerate(chunks, start=1):
        vec = embedding_gen.encode(content)
        assert vec is not None
        vector_index.add(
            i,
            vec,
            {"file_path": str(tmp_path / filename), "fqn": fqn},
        )

    return {
        "db": db,
        "metadata": IndexMetadataStore(db),
        "embedding_gen": embedding_gen,
        "vector_index": vector_index,
        "context_dir": tmp_path,
        "settings": settings,
        "redactor": Redactor(),
    }


def test_find_related_excludes_anchor_chunk(tmp_path: Any) -> None:
    """``find_related`` excludes the anchor chunk (self-match).

    The anchor is queried by its own file+line; the returned set must contain
    the other chunk and never the anchor chunk id.
    """
    comps = _indexed_components_unit(tmp_path)
    payload = _find_related_payload(comps, str(tmp_path / "a.py"), 1, limit=5)
    data = __import__("json").loads(payload)
    results = data["results"]
    assert results, "expected a non-empty related set"
    ids = [r["chunk_id"] for r in results]
    assert 1 not in ids, f"anchor chunk must be excluded, got {ids}"
    assert 2 in ids, f"the related chunk must be present, got {ids}"
    assert data.get("vector_health") is True


def test_find_related_vector_layer_unavailable_status(tmp_path: Any) -> None:
    """When the embedding model returns ``None``, ``find_related``
    reports a clear ``vector_health: false`` status instead of a bare empty
    array.
    """
    comps = _indexed_components_unit(tmp_path)

    class _DownEmbedding:
        def encode(self, _text: str) -> None:
            return None

    comps["embedding_gen"] = _DownEmbedding()  # type: ignore[assignment]
    payload = _find_related_payload(comps, str(tmp_path / "a.py"), 1, limit=5)
    data = __import__("json").loads(payload)
    assert data.get("vector_health") is False
    assert data.get("results") == []
    assert data.get("status") == "empty", data.get("status")
    assert "unavailable" in data.get("explanation", ""), (
        f"status must explain the unavailable layer, got {data.get('explanation')}"
    )


def test_find_related_unindexed_location_returns_clear_error(tmp_path: Any) -> None:
    """An unindexed location returns the clear
    non-crashing ``error`` status.
    """
    comps = _indexed_components_unit(tmp_path)
    payload = _find_related_payload(comps, str(tmp_path / "missing.py"), 1, limit=5)
    data = __import__("json").loads(payload)
    assert "error" in data, f"expected a clear error, got {data}"
    assert "No indexed chunk found" in data["error"]


def test_implementations_payload_shape_and_no_snippet(tmp_path: Any) -> None:
    """The dedicated payload carries identity + location only: the
    envelope has no source snippet and reports the shared keys."""
    import json

    from src.engine.config import Settings
    from src.engine.graph import EdgeStore, GraphDatabase
    from src.engine.symbols import SymbolStore
    from src.mcp.server import _implementations_payload

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "impl.db", settings)
    db.initialize()
    symbol_store = SymbolStore(db, settings)
    edge_store = EdgeStore(db, settings)
    ids = symbol_store.insert_symbols_batch(
        [
            {
                "fqn": "src/i.py::I",
                "name": "I",
                "kind": "interface",
                "file_path": "src/i.py",
                "line_start": 1,
                "line_end": 2,
                "column_start": 0,
                "column_end": 5,
                "language": "java",
                "parent_fqn": None,
            },
            {
                "fqn": "src/i.py::I.m",
                "name": "m",
                "kind": "method",
                "file_path": "src/i.py",
                "line_start": 3,
                "line_end": 4,
                "column_start": 0,
                "column_end": 5,
                "language": "java",
                "parent_fqn": "src/i.py::I",
            },
            {
                "fqn": "src/a.py::A",
                "name": "A",
                "kind": "class",
                "file_path": "src/a.py",
                "line_start": 1,
                "line_end": 2,
                "column_start": 0,
                "column_end": 5,
                "language": "java",
                "parent_fqn": None,
            },
            {
                "fqn": "src/a.py::A.m",
                "name": "m",
                "kind": "method",
                "file_path": "src/a.py",
                "line_start": 3,
                "line_end": 4,
                "column_start": 0,
                "column_end": 5,
                "language": "java",
                "parent_fqn": "src/a.py::A",
            },
        ]
    )
    edge_store.insert_edges_batch(
        [
            {
                "source_symbol_id": ids["src/a.py::A"],
                "target_symbol_id": ids["src/i.py::I"],
                "edge_type": "INHERITS",
            }
        ]
    )
    data = json.loads(_implementations_payload(symbol_store, edge_store, "src/i.py::I.m"))
    assert data["outcome"] == "resolved"
    assert data["declaring_type"]["fqn"] == "src/i.py::I"
    assert data["implementations"][0]["type"]["fqn"] == "src/a.py::A"
    assert "source_code" not in json.dumps(data)


def test_find_related_single_chunk_index_returns_clear_status(tmp_path: Any) -> None:
    """Against a single-chunk index, self-match exclusion leaves
    no candidates, so ``find_related`` returns a clear status instead of a
    fabricated empty ``vector_health: true`` result set.
    """
    comps = _indexed_components_unit(tmp_path, n_chunks=1)
    payload = _find_related_payload(comps, str(tmp_path / "a.py"), 1, limit=5)
    data = __import__("json").loads(payload)
    assert data.get("results") == []
    assert "vector_health" in data, "the status must report vector health"
    assert data["vector_health"] is True, "the single-chunk index is still populated"
    assert "status" in data, "a single-chunk index must return a clear status"
    assert data["status"] == "empty", data["status"]
    assert "no related" in data.get("explanation", ""), data.get("explanation")
