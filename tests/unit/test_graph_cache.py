"""Tests for the generation-keyed in-memory adjacency cache."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from code_search.engine.config import Settings
from code_search.engine.graph import EdgeStore, GraphDatabase
from code_search.engine.graph_cache import (
    adjacency_cache_stats,
    adjacency_snapshot,
    build_snapshot,
    clear_adjacency_cache,
)
from code_search.engine.graph_query import GraphQueryService
from code_search.engine.symbols import SymbolStore


@pytest.fixture(autouse=True)
def _isolate_cache():
    """Start and end every test with an empty process-wide cache."""
    clear_adjacency_cache()
    yield
    clear_adjacency_cache()


def _build_graph(
    tmp_path: Path, *, generation: str | None = "gen-1"
) -> tuple[GraphDatabase, Settings]:
    """Build a two-file graph: a caller, a callee, and a class with a method."""
    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "graph.db", settings)
    db.initialize()
    caller_file = tmp_path / "caller.py"
    callee_file = tmp_path / "callee.py"
    with db.write_transaction() as conn:
        rows = [
            (f"{caller_file}::caller", "caller", "function", caller_file, None),
            (f"{callee_file}::save", "save", "function", callee_file, None),
            (f"{callee_file}::Store", "Store", "class", callee_file, None),
            (f"{callee_file}::Store.load", "load", "method", callee_file, "Store"),
        ]
        ids: dict[str, int] = {}
        for fqn, name, kind, path, parent in rows:
            cursor = conn.execute(
                "INSERT INTO symbols "
                "(fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language, parent_symbol_id) "
                "VALUES (?, ?, ?, ?, 0, 2, 0, 1, 'python', ?);",
                (
                    fqn,
                    name,
                    kind,
                    str(path),
                    ids.get(f"{callee_file}::{parent}") if parent else None,
                ),
            )
            ids[fqn] = int(cursor.lastrowid)
        conn.execute(
            "INSERT INTO graph_edges "
            "(source_symbol_id, target_symbol_id, edge_type, resolution_tier, resolved) "
            "VALUES (?, ?, 'CALLS', 'exact', 1);",
            (ids[f"{caller_file}::caller"], ids[f"{callee_file}::save"]),
        )
        conn.execute(
            "INSERT INTO graph_edges "
            "(source_symbol_id, target_symbol_id, edge_type, resolution_tier, resolved) "
            "VALUES (?, ?, 'CALLS', 'independent', 0);",
            (ids[f"{caller_file}::caller"], ids[f"{callee_file}::Store"]),
        )
        conn.executemany(
            "INSERT INTO code_chunks "
            "(file_path, line_start, line_end, content, language, content_type) "
            "VALUES (?, 0, 2, 'pass', 'python', 'code');",
            [(str(caller_file),), (str(callee_file),)],
        )
        if generation is not None:
            conn.execute(
                "INSERT INTO index_metadata (key, value) VALUES ('index_generation', ?);",
                (generation,),
            )
        conn.execute(
            "INSERT INTO index_metadata (key, value) VALUES ('index_root', ?);",
            (str(tmp_path),),
        )
    return db, settings


def test_snapshot_builds_csr_and_metadata(tmp_path: Path) -> None:
    """The snapshot exposes directed neighbours, containment, and metadata."""
    db, settings = _build_graph(tmp_path)
    snapshot = adjacency_snapshot(db, settings)
    assert snapshot is not None
    assert snapshot.generation == "gen-1"
    assert snapshot.symbol_count == 4
    assert snapshot.edge_count == 1  # the resolved CALLS edge only

    with db.connect() as conn:
        ids = {
            str(row["name"]): int(row["id"])
            for row in conn.execute("SELECT id, name FROM symbols;")
        }
    caller = ids["caller"]
    save = ids["save"]
    store = ids["Store"]
    load = ids["load"]

    outgoing = list(snapshot.iter_out(caller, snapshot.type_codes({"CALLS"})))
    assert [(item.symbol_id, item.edge_type) for item in outgoing] == [(save, "CALLS")]
    assert list(snapshot.iter_out(caller, snapshot.type_codes({"INHERITS"}))) == []
    assert [item.symbol_id for item in snapshot.iter_in(save)] == [caller]
    assert list(snapshot.children(store)) == [load]
    assert snapshot.parent(load) == store
    assert snapshot.symbol(save).fqn.endswith("callee.py::save")


def test_same_generation_reuses_the_snapshot(tmp_path: Path) -> None:
    """A warm lookup returns the same object instead of rebuilding."""
    db, settings = _build_graph(tmp_path)
    first = adjacency_snapshot(db, settings)
    second = adjacency_snapshot(db, settings)
    assert first is not None and first is second
    stats = adjacency_cache_stats()
    assert stats["builds"] == 1
    assert stats["hits"] == 1


def test_write_invalidates_and_the_next_read_sees_new_edges(tmp_path: Path) -> None:
    """A committed write drops the snapshot even when the generation is unchanged."""
    db, settings = _build_graph(tmp_path)
    service = GraphQueryService(db, SymbolStore(db, settings), EdgeStore(db), None, settings)
    assert service.shortest_path("caller", "save").found
    assert adjacency_cache_stats()["entries"]

    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO graph_edges "
            "(source_symbol_id, target_symbol_id, edge_type, resolution_tier, resolved) "
            "SELECT (SELECT id FROM symbols WHERE name = 'save'), "
            "(SELECT id FROM symbols WHERE name = 'caller'), "
            "'CALLS', 'exact', 1;"
        )

    assert adjacency_cache_stats()["entries"] == []
    result = service.shortest_path("save", "caller")
    assert result.found
    assert adjacency_cache_stats()["builds"] == 2


def test_new_generation_replaces_the_previous_snapshot(tmp_path: Path) -> None:
    """A changed generation token makes the old snapshot unreachable."""
    db, settings = _build_graph(tmp_path)
    first = adjacency_snapshot(db, settings)
    assert first is not None

    with db.write_transaction() as conn:
        conn.execute("UPDATE index_metadata SET value = 'gen-2' WHERE key = 'index_generation';")
    second = adjacency_snapshot(db, settings)
    assert second is not None
    assert second.generation == "gen-2"
    assert second is not first
    stats = adjacency_cache_stats()
    assert [entry["generation"] for entry in stats["entries"]] == ["gen-2"]


def test_snapshot_is_refused_over_the_budget(tmp_path: Path) -> None:
    """An over-budget snapshot returns ``None`` and is not retried every call."""
    db, _ = _build_graph(tmp_path)
    tiny = Settings(context_dir=tmp_path, graph_cache_max_bytes=512)
    assert adjacency_snapshot(db, tiny) is None
    stats = adjacency_cache_stats()
    assert stats["entries"] == []
    assert stats["over_budget"] == 1

    # The refusal is remembered for this generation: no second build attempt.
    assert adjacency_snapshot(db, tiny) is None
    assert adjacency_cache_stats()["builds"] == 1


def test_cache_can_be_disabled(tmp_path: Path) -> None:
    """An explicit disabled setting never reads or builds a snapshot."""
    db, _ = _build_graph(tmp_path)
    disabled = Settings(context_dir=tmp_path, graph_cache_enabled=False)
    assert adjacency_snapshot(db, disabled) is None
    assert adjacency_cache_stats()["builds"] == 0


def test_missing_generation_disables_the_cache(tmp_path: Path) -> None:
    """An index without a generation token keeps using the SQL path."""
    db, settings = _build_graph(tmp_path, generation=None)
    assert adjacency_snapshot(db, settings) is None
    assert adjacency_cache_stats()["builds"] == 0


def test_idle_snapshots_expire(tmp_path: Path) -> None:
    """An unused snapshot is dropped after the configured idle interval."""
    db, _ = _build_graph(tmp_path)
    idle = Settings(context_dir=tmp_path, graph_cache_idle_seconds=0.001)
    assert adjacency_snapshot(db, idle) is not None
    # Sleep past the Windows monotonic-clock granularity (GetTickCount64 is
    # ~15.6 ms on Python 3.12), not merely past the 1 ms idle threshold.
    time.sleep(0.1)
    assert adjacency_snapshot(db, idle) is not None
    assert adjacency_cache_stats()["builds"] == 2


def test_shortest_path_uses_the_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With a warm snapshot the SQL adjacency builder is never called."""
    db, settings = _build_graph(tmp_path)
    service = GraphQueryService(db, SymbolStore(db, settings), EdgeStore(db), None, settings)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("SQL adjacency must not be used when a snapshot exists")

    monkeypatch.setattr(service, "_build_adjacency", fail)
    answer = service.shortest_path("caller", "save")
    assert answer.found
    assert answer.stats["adjacency"] == "cache"


def test_impact_uses_the_snapshot_and_reports_deterministic_parents(tmp_path: Path) -> None:
    """Impact walks the snapshot and records the same parent on every run."""
    db, settings = _build_graph(tmp_path)
    service = GraphQueryService(db, SymbolStore(db, settings), EdgeStore(db), None, settings)
    changed = tmp_path / "callee.py"
    first = service.impact([str(changed)], depth=2)
    second = service.impact([str(changed)], depth=2)
    assert first.summary["adjacency"] == "cache"
    assert first.parents == second.parents
    caller_fqn = f"{tmp_path / 'caller.py'}::caller"
    assert first.parents[caller_fqn] == {
        "parent": f"{tmp_path / 'callee.py'}::save",
        "relation": "CALLS",
    }


def test_sql_fallback_matches_the_cached_path(tmp_path: Path) -> None:
    """Disabling the cache keeps path answers correct in both directions."""
    db, _settings = _build_graph(tmp_path)
    disabled = Settings(context_dir=tmp_path, graph_cache_enabled=False)
    service = GraphQueryService(db, SymbolStore(db, disabled), EdgeStore(db), None, disabled)

    forward = service.shortest_path("caller", "save")
    assert forward.found
    assert forward.stats["adjacency"] == "sql"

    reverse = service.shortest_path("save", "caller", undirected=True)
    assert reverse.found
    assert reverse.stats["adjacency"] == "sql"


def test_direct_build_reads_the_current_generation(tmp_path: Path) -> None:
    """``build_snapshot`` is usable without the cache registry."""
    db, _ = _build_graph(tmp_path)
    snapshot = build_snapshot(db, "manual")
    assert snapshot.generation == "manual"
    assert snapshot.edge_count == 1
