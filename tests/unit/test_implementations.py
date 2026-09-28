"""The shared implementation-lookup rule."""

from pathlib import Path

import pytest

from src.engine.config import Settings
from src.engine.graph import EdgeStore, GraphDatabase
from src.engine.implementations import find_implementations
from src.engine.symbols import SymbolStore

_SYMBOLS: list[tuple[str, str, str, str | None]] = [
    ("src/i.py::I", "I", "interface", None),
    ("src/i.py::I.m(String)", "m", "method", "src/i.py::I"),
    ("src/a.py::A", "A", "class", None),
    ("src/a.py::A.m(String)", "m", "method", "src/a.py::A"),
    ("src/base.py::Base", "Base", "class", None),
    ("src/base.py::Base.m(String)", "m", "method", "src/base.py::Base"),
    ("src/b.py::B", "B", "class", None),
    ("src/b.py::B.x", "x", "method", "src/b.py::B"),
    ("src/p.py::P", "P", "interface", None),
    ("src/p.py::P.m(String)", "m", "method", "src/p.py::P"),
    ("src/c.py::C", "C", "class", None),
    ("src/c.py::C.m(String)", "m", "method", "src/c.py::C"),
    ("src/d.py::D", "D", "class", None),
    ("src/d.py::D.m(int)", "m", "method", "src/d.py::D"),
    ("src/alpha.py::Alpha", "Alpha", "interface", None),
    ("src/alpha.py::Alpha.handle", "handle", "method", "src/alpha.py::Alpha"),
    ("src/beta.py::Beta", "Beta", "interface", None),
    ("src/beta.py::Beta.handle", "handle", "method", "src/beta.py::Beta"),
    ("src/multi.py::Multi", "Multi", "class", None),
    ("src/multi.py::Multi.handle", "handle", "method", "src/multi.py::Multi"),
    ("src/repo.py::Repo", "Repo", "interface", None),
    ("src/repo.py::Repo.find", "find", "method", "src/repo.py::Repo"),
]

_EDGES = [
    ("src/a.py::A", "src/i.py::I"),
    ("src/base.py::Base", "src/i.py::I"),
    ("src/b.py::B", "src/base.py::Base"),
    ("src/p.py::P", "src/i.py::I"),
    ("src/c.py::C", "src/p.py::P"),
    ("src/d.py::D", "src/i.py::I"),
    ("src/multi.py::Multi", "src/alpha.py::Alpha"),
    ("src/multi.py::Multi", "src/beta.py::Beta"),
]


@pytest.fixture
def stores(
    tmp_path: Path,
) -> tuple[SymbolStore, EdgeStore, dict[str, int]]:
    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "graph.db", settings)
    db.initialize()
    symbol_store = SymbolStore(db, settings)
    edge_store = EdgeStore(db, settings)

    rows: list[dict[str, object]] = []
    for fqn, name, kind, parent_fqn in _SYMBOLS:
        rows.append(
            {
                "fqn": fqn,
                "name": name,
                "kind": kind,
                "file_path": fqn.split("::", 1)[0],
                "line_start": 1,
                "line_end": 2,
                "column_start": 0,
                "column_end": 10,
                "language": "java",
                "parent_fqn": parent_fqn,
            }
        )
    ids = symbol_store.insert_symbols_batch(rows)
    edge_store.insert_edges_batch(
        [
            {
                "source_symbol_id": ids[src],
                "target_symbol_id": ids[tgt],
                "edge_type": "INHERITS",
            }
            for src, tgt in _EDGES
        ]
    )
    return symbol_store, edge_store, ids


def _names(result: dict) -> list[str]:
    return [impl["type"]["fqn"].rsplit("::", 1)[-1] for impl in result["implementations"]]


def test_resolves_direct_indirect_and_inherited(stores: tuple) -> None:
    symbol_store, edge_store, _ids = stores
    result = find_implementations(symbol_store, edge_store, "src/i.py::I.m(String)")
    assert result["outcome"] == "resolved"
    assert result["declaring_type"]["fqn"] == "src/i.py::I"
    # Direct before indirect; declared before inherited within the same depth.
    assert _names(result) == ["A", "Base", "P", "C", "B"]
    by_name = {impl["type"]["fqn"].rsplit("::", 1)[-1]: impl for impl in result["implementations"]}
    assert by_name["B"]["relationship"] == "indirect"
    assert by_name["B"]["site"]["inherited"] is True
    assert by_name["B"]["site"]["declaring_type_fqn"] == "src/base.py::Base"
    assert by_name["C"]["site"]["inherited"] is False
    assert by_name["A"]["site"]["match"] == "signature"


def test_signature_mismatch_is_not_an_implementation(stores: tuple) -> None:
    symbol_store, edge_store, _ids = stores
    result = find_implementations(symbol_store, edge_store, "src/i.py::I.m(String)")
    assert "D" not in _names(result)


def test_type_query_returns_subtypes_without_sites(stores: tuple) -> None:
    symbol_store, edge_store, _ids = stores
    result = find_implementations(symbol_store, edge_store, "src/i.py::I")
    assert result["outcome"] == "resolved"
    assert _names(result) == ["A", "Base", "D", "P", "B", "C"]
    assert all(impl["site"] is None for impl in result["implementations"])
    assert all("depth" in impl["type"] for impl in result["implementations"])


def test_no_static_implementation_is_explicit(stores: tuple) -> None:
    symbol_store, edge_store, _ids = stores
    result = find_implementations(symbol_store, edge_store, "src/repo.py::Repo.find")
    assert result["outcome"] == "no_static_implementation"
    assert result["implementations"] == []
    assert "runtime-generated implementation may exist" in (result["explanation"] or "")


def test_not_found_is_disjoint_from_no_static(stores: tuple) -> None:
    symbol_store, edge_store, _ids = stores
    not_found = find_implementations(symbol_store, edge_store, "does.not.Exist")
    no_static = find_implementations(symbol_store, edge_store, "src/repo.py::Repo.find")
    assert not_found["outcome"] == "not_found"
    assert no_static["outcome"] == "no_static_implementation"
    assert not_found["outcome"] != no_static["outcome"]


def test_ambiguous_reference_never_auto_selects(stores: tuple) -> None:
    symbol_store, edge_store, _ids = stores
    result = find_implementations(symbol_store, edge_store, "handle")
    assert result["outcome"] == "ambiguous"
    assert result["symbol"] is None
    assert result["implementations"] == []
    assert {c["parent_name"] for c in result["candidates"]} >= {"Alpha", "Beta", "Multi"}


def test_multi_interface_type_reported_once_per_declaring_type(stores: tuple) -> None:
    symbol_store, edge_store, _ids = stores
    result = find_implementations(symbol_store, edge_store, "src/alpha.py::Alpha.handle")
    assert _names(result) == ["Multi"]
    assert result["implementations"][0]["site"]["declaring_type_fqn"] == "src/multi.py::Multi"


def test_qualified_reference_resolves_declaring_type(stores: tuple) -> None:
    symbol_store, edge_store, _ids = stores
    result = find_implementations(symbol_store, edge_store, "Alpha.handle")
    assert result["outcome"] == "resolved"
    assert result["declaring_type"]["fqn"] == "src/alpha.py::Alpha"


def _seeded_store(tmp_path: Path, language: str, kind: str) -> tuple[SymbolStore, EdgeStore, str]:
    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "wording.db", settings)
    db.initialize()
    symbol_store = SymbolStore(db, settings)
    edge_store = EdgeStore(db, settings)
    rows = [
        {
            "fqn": "src/x.py::T",
            "name": "T",
            "kind": kind,
            "file_path": "src/x.py",
            "line_start": 1,
            "line_end": 2,
            "column_start": 0,
            "column_end": 5,
            "language": language,
            "parent_fqn": None,
        },
        {
            "fqn": "src/x.py::T.run",
            "name": "run",
            "kind": "method",
            "file_path": "src/x.py",
            "line_start": 3,
            "line_end": 4,
            "column_start": 0,
            "column_end": 5,
            "language": language,
            "parent_fqn": "src/x.py::T",
        },
    ]
    symbol_store.insert_symbols_batch(rows)
    return symbol_store, edge_store, "src/x.py::T.run"


def test_no_static_wording_for_non_interface(tmp_path: Path) -> None:
    symbol_store, edge_store, fqn = _seeded_store(tmp_path, "java", "class")
    result = find_implementations(symbol_store, edge_store, fqn)
    assert result["outcome"] == "no_static_implementation"
    assert result["explanation"] == "No statically-known implementing type found"


def test_no_static_notes_uncaptured_language(tmp_path: Path) -> None:
    symbol_store, edge_store, fqn = _seeded_store(tmp_path, "php", "interface")
    result = find_implementations(symbol_store, edge_store, fqn)
    assert result["outcome"] == "no_static_implementation"
    assert "runtime-generated implementation may exist" in (result["explanation"] or "")
    assert "may be uncaptured" in (result["explanation"] or "")
