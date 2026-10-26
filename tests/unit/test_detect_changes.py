"""Unit tests for direction-aware impact and change detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_search.engine.config import Settings
from code_search.engine.graph import EdgeStore, GraphDatabase
from code_search.engine.graph_query import GraphQueryService
from code_search.engine.symbols import SymbolStore


@pytest.fixture
def service(tmp_path: Path) -> GraphQueryService:
    """Return a service over a small dependency chain with a test caller."""
    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "graph.db", settings)
    db.initialize()
    files = {
        "changed": tmp_path / "changed.py",
        "caller": tmp_path / "caller.py",
        "consumer": tmp_path / "consumer.py",
        "other": tmp_path / "other.py",
        "test": tmp_path / "tests" / "test_changed.py",
    }
    for path in files.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n", encoding="utf-8")
    symbols = [
        (f"{files['changed']}::Store", "Store", "class", files["changed"], None),
        (f"{files['changed']}::save", "save", "method", files["changed"], "Store"),
        (f"{files['caller']}::caller", "caller", "function", files["caller"], None),
        (f"{files['consumer']}::consumer", "consumer", "function", files["consumer"], None),
        (f"{files['other']}::Other", "Other", "class", files["other"], None),
        (f"{files['test']}::test_save", "test_save", "function", files["test"], None),
    ]
    with db.write_transaction() as conn:
        ids: dict[str, int] = {}
        for fqn, name, kind, path, parent in symbols:
            cursor = conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language, parent_symbol_id) "
                "VALUES (?, ?, ?, ?, 0, 2, 0, 1, 'python', ?);",
                (
                    fqn,
                    name,
                    kind,
                    str(path),
                    ids.get(f"{files['changed']}::{parent}") if parent else None,
                ),
            )
            ids[fqn] = int(cursor.lastrowid)
        for path in {item[3] for item in symbols}:
            conn.execute(
                "INSERT INTO code_chunks (file_path, line_start, line_end, content, language) "
                "VALUES (?, 0, 2, 'pass', 'python');",
                (str(path),),
            )
        caller_id = ids[f"{files['caller']}::caller"]
        consumer_id = ids[f"{files['consumer']}::consumer"]
        test_id = ids[f"{files['test']}::test_save"]
        save_id = ids[f"{files['changed']}::save"]
        store_id = ids[f"{files['changed']}::Store"]
        other_id = ids[f"{files['other']}::Other"]
        conn.executemany(
            "INSERT INTO graph_edges (source_symbol_id, target_symbol_id, edge_type, "
            "resolution_tier, resolved) VALUES (?, ?, 'CALLS', 'exact', 1);",
            [
                (caller_id, save_id),
                (consumer_id, caller_id),
                (test_id, save_id),
            ],
        )
        conn.execute(
            "INSERT INTO graph_edges (source_symbol_id, target_symbol_id, edge_type, "
            "resolution_tier, resolved) VALUES (?, ?, 'REFERENCES', 'exact', 1);",
            (caller_id, store_id),
        )
        conn.execute(
            "INSERT INTO graph_edges (source_symbol_id, target_symbol_id, edge_type, "
            "resolution_tier, resolved) VALUES (?, ?, 'REFERENCES', 'exact', 1);",
            (caller_id, other_id),
        )
        conn.execute(
            "INSERT INTO index_metadata (key, value) VALUES ('index_generation', 'gen-1');"
        )
        conn.execute(
            "INSERT INTO index_metadata (key, value) VALUES ('index_root', ?);",
            (str(tmp_path),),
        )
    return GraphQueryService(db, SymbolStore(db, settings), EdgeStore(db), None, settings)


def _changed_path(service: GraphQueryService) -> Path:
    return service._index_root / "changed.py"


def test_impact_inbound_includes_callers_and_tests(service: GraphQueryService) -> None:
    """The default reverse walk finds callers and test callers."""
    answer = service.impact([str(_changed_path(service))], depth=3)

    names = {node.name for node in answer.impacted}
    assert {"save", "caller", "consumer", "test_save"} <= names
    assert answer.test_files == ["tests/test_changed.py"]
    assert answer.production_files == ["changed.py", "caller.py", "consumer.py"]
    assert answer.summary["test_symbols"] == 1


def test_impact_outbound_follows_dependencies(service: GraphQueryService) -> None:
    """Outbound traversal from a caller reaches the symbol it calls."""
    caller_file = service._index_root / "consumer.py"
    answer = service.impact([str(caller_file)], depth=2, direction="outbound")

    names = {node.name for node in answer.impacted}
    assert {"consumer", "caller", "save"} <= names
    assert "test_save" not in names
    assert answer.direction == "outbound"


def test_impact_risk_labels_types_and_fan_in(service: GraphQueryService) -> None:
    """A type boundary is high risk; a function without callers is low risk."""
    answer = service.impact([str(_changed_path(service))], depth=2)

    store_key = next(key for key in answer.risks if key.endswith("::Store"))
    save_key = next(key for key in answer.risks if key.endswith("::save"))
    assert answer.risks[store_key] == "high"
    assert answer.risks[save_key] in {"medium", "high"}
    assert set(answer.risk_summary) == {"high", "medium", "low"}


def test_impact_seed_filter_product_drops_test_seeds(service: GraphQueryService) -> None:
    """A test file contributes no seeds when seed_filter is product."""
    test_file = service._index_root / "tests" / "test_changed.py"
    answer = service.impact([str(test_file)], depth=2, seed_filter="product")

    assert answer.symbols == []
    assert answer.impacted == []


def test_detect_changes_scope_files_skips_traversal(service: GraphQueryService) -> None:
    """``scope=files`` returns the changed set without graph work."""
    payload = service.detect_changes([str(_changed_path(service))], scope="files")

    assert payload["outcome"] == "resolved"
    assert payload["scope"] == "files"
    assert payload["changed_files"] == ["changed.py"]
    assert "impacted" not in payload


def test_detect_changes_scope_tests_narrows_results(service: GraphQueryService) -> None:
    """``scope=tests`` returns only test files and test symbols."""
    payload = service.detect_changes([str(_changed_path(service))], scope="tests")

    assert payload["files"] == ["tests/test_changed.py"]
    assert [node["name"] for node in payload["impacted"]] == ["test_save"]
    assert payload["summary"]["changed_files"] == 1


def test_detect_changes_rejects_unknown_scope(service: GraphQueryService) -> None:
    """An unknown scope is an explicit outcome, not an empty result."""
    payload = service.detect_changes(["changed.py"], scope="everything")

    assert payload["outcome"] == "invalid_argument"
    assert "unsupported scope" in payload["error"]


def test_detect_changes_no_changes_is_an_outcome(service: GraphQueryService) -> None:
    """An empty change set is reported distinctly from no impact."""
    payload = service.detect_changes([])

    assert payload["outcome"] == "no_changes"
    assert payload["summary"] == {"changed_files": 0}


def test_query_direction_narrows_the_neighbourhood(service: GraphQueryService) -> None:
    """Inbound and outbound return only the requested side."""
    save_fqn = f"{service._index_root / 'changed.py'}::save"
    outbound = service.query("save", seeds=[save_fqn], direction="outbound", depth=2)
    assert outbound.stats["direction"] == "outbound"
    assert {node.name for node in outbound.nodes} == {"save"}

    inbound = service.query("save", seeds=[save_fqn], direction="inbound", depth=1)
    assert inbound.stats["direction"] == "inbound"
    names = {node.name for node in inbound.nodes}
    assert {"save", "caller", "test_save"} <= names
    assert "consumer" not in names

    both = service.query("save", seeds=[save_fqn], direction="both", depth=2)
    assert "consumer" in {node.name for node in both.nodes}


def test_shortest_path_edge_type_filter(service: GraphQueryService) -> None:
    """The path walk obeys the requested edge types."""
    consumer = f"{service._index_root / 'consumer.py'}::consumer"
    caller = f"{service._index_root / 'caller.py'}::caller"
    save = f"{service._index_root / 'changed.py'}::save"
    other = f"{service._index_root / 'other.py'}::Other"

    calls = service.shortest_path(consumer, save, edge_types={"CALLS"})
    assert calls.found
    assert [hop.relation for hop in calls.hops] == ["CALLS", "CALLS"]

    references = service.shortest_path(caller, other, edge_types={"CALLS"})
    assert not references.found
    assert references.outcome == "no_path"

    reference_path = service.shortest_path(caller, other, edge_types={"REFERENCES"})
    assert reference_path.found
    assert [hop.relation for hop in reference_path.hops] == ["REFERENCES"]
