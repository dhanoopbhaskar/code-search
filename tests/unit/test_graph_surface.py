"""Unit tests for the read-only agent-facing graph surfaces."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_search.engine.config import Settings
from code_search.engine.graph import GraphDatabase
from code_search.engine.graph_surface import (
    check_index_coverage,
    get_file_outline,
    get_graph_schema,
    render_coverage_text,
    render_file_outline_text,
    render_graph_schema_text,
    render_symbol_search_text,
    search_symbols,
)


@pytest.fixture
def graph_db(tmp_path: Path) -> GraphDatabase:
    """Return an initialized graph with one file, three symbols, and coverage."""
    db = GraphDatabase(tmp_path / "graph.db", Settings(context_dir=tmp_path))
    db.initialize()
    with db.write_transaction() as conn:
        rows = [
            ("/repo/src/app.py::App", "App", "class", 0, 40, 0, 0, None),
            ("/repo/src/app.py::App.run", "run", "method", 5, 12, 4, 8, "App"),
            ("/repo/src/app.py::main", "main", "function", 20, 30, 0, 0, None),
            ("/repo/src/other.py::helper", "helper", "function", 0, 3, 0, 0, None),
        ]
        kind_by_fqn = {}
        for index, (fqn, name, kind, start, end, col_start, col_end, parent) in enumerate(rows):
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language, parent_symbol_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'python', ?);",
                (
                    fqn,
                    name,
                    kind,
                    fqn.split("::", 1)[0],
                    start,
                    end,
                    col_start,
                    col_end,
                    kind_by_fqn.get(f"/repo/src/app.py::{parent}") if parent else None,
                ),
            )
            kind_by_fqn[fqn] = index + 1
        conn.execute(
            "INSERT INTO graph_edges (source_symbol_id, target_symbol_id, edge_type, "
            "resolution_tier, resolved) VALUES (2, 3, 'CALLS', 'exact', 1);"
        )
        conn.execute(
            "INSERT INTO graph_edges (source_symbol_id, target_symbol_id, edge_type, "
            "resolved, target_raw) VALUES (3, NULL, 'CALLS', 0, 'external.save');"
        )
        conn.execute(
            "INSERT INTO index_coverage (file_path, kind, detail, generation) "
            "VALUES ('/repo/src/app.py', 'parse_partial', '2 syntax error range(s)', 'gen-1');"
        )
        conn.execute(
            "INSERT INTO index_metadata (key, value) VALUES ('index_generation', 'gen-1');"
        )
        conn.execute("INSERT INTO index_metadata (key, value) VALUES ('index_root', '/repo');")
        conn.execute(
            "INSERT INTO index_metadata (key, value) "
            "VALUES ('last_indexed_at', '2026-10-26T10:00:00.000Z');"
        )
    return db


def test_graph_schema_reports_labels_edges_and_generation(graph_db: GraphDatabase) -> None:
    """The schema exposes stored labels, edge counts, and coverage."""
    payload = get_graph_schema(graph_db)

    assert payload["index_generation"] == "gen-1"
    assert payload["index_root"] == "/repo"
    assert payload["schema_version"] == 18
    assert payload["node_labels"] == {"class": 1, "function": 2, "method": 1}
    assert payload["synthetic_labels"]["file"] == 2
    assert payload["edge_types"]["CALLS"]["total"] == 2
    assert payload["edge_types"]["CALLS"]["resolved"] == 1
    assert payload["stats"]["total_symbols"] == 4
    assert payload["coverage"]["by_kind"] == {"parse_partial": 1}
    assert payload["coverage"]["complete"] is False


def test_graph_schema_pages_node_labels(graph_db: GraphDatabase) -> None:
    """Node labels are returned in deterministic pages."""
    first = get_graph_schema(graph_db, node_limit=2)
    second = get_graph_schema(graph_db, node_limit=2, offset=2)

    assert first["node_labels"] == {"class": 1, "function": 2}
    assert first["node_labels_total"] == 3
    assert second["node_labels"] == {"method": 1}


def test_graph_schema_diagnostics_reports_property_keys(
    graph_db: GraphDatabase,
) -> None:
    """Diagnostics read edge properties now that the column exists."""
    payload = get_graph_schema(graph_db, diagnostics=True)

    assert payload["diagnostics"]["available"] is True
    assert payload["diagnostics"]["property_keys"] == {}


def test_file_outline_is_source_ordered_and_exact(graph_db: GraphDatabase) -> None:
    """An outline lists declarations in source order with exact totals."""
    payload = get_file_outline(
        graph_db, "src/app.py", index_root=Path("/repo"), include_docstring=True
    )

    assert payload["outcome"] == "resolved"
    assert payload["file_path"] == "src/app.py"
    assert payload["total"] == 3
    assert [entry["name"] for entry in payload["symbols"]] == ["App", "run", "main"]
    assert payload["symbols"][1]["parent_name"] == "App"
    assert "fqn" not in payload["symbols"][1]
    assert "column_start" not in payload["symbols"][1]
    assert payload["symbols"][1]["kind"] == "method"
    assert payload["truncated"] is False

    with_ids = get_file_outline(graph_db, "src/app.py", index_root=Path("/repo"), include_ids=True)
    assert with_ids["symbols"][1]["parent_fqn"] == "/repo/src/app.py::App"
    assert with_ids["symbols"][1]["fqn"] == "/repo/src/app.py::App.run"


def test_file_outline_filters_kinds_and_pages(graph_db: GraphDatabase) -> None:
    """Kind filters and paging keep the exact total."""
    payload = get_file_outline(
        graph_db, "src/app.py", index_root=Path("/repo"), kinds=["method", "function"], limit=1
    )

    assert payload["total"] == 2
    assert [entry["name"] for entry in payload["symbols"]] == ["run"]
    assert payload["truncated"] is True

    next_page = get_file_outline(
        graph_db,
        "src/app.py",
        index_root=Path("/repo"),
        kinds=["method", "function"],
        limit=1,
        offset=1,
    )
    assert [entry["name"] for entry in next_page["symbols"]] == ["main"]


def test_file_outline_distinguishes_not_indexed(graph_db: GraphDatabase) -> None:
    """An unknown file reports ``not_indexed`` instead of an empty outline."""
    payload = get_file_outline(graph_db, "src/missing.py", index_root=Path("/repo"))

    assert payload["outcome"] == "not_indexed"
    assert payload["symbols"] == []
    assert payload["total"] == 0


def test_renderers_include_absence_note(graph_db: GraphDatabase) -> None:
    """Text renderers surface the generation and the coverage caveat."""
    schema_text = render_graph_schema_text(get_graph_schema(graph_db))
    outline_text = render_file_outline_text(
        get_file_outline(graph_db, "src/app.py", index_root=Path("/repo"))
    )

    assert "generation gen-1" in schema_text
    assert "absence is not proof of completeness" in schema_text
    assert "src/app.py" in outline_text
    assert "main" in outline_text


def test_search_symbols_filters_kinds_and_entry_points(graph_db: GraphDatabase) -> None:
    """Structural search excludes entry points by default and can include them."""
    default = search_symbols(graph_db, index_root=Path("/repo"))

    assert [entry["name"] for entry in default["symbols"]] == ["App", "run", "helper"]
    assert default["symbols"][1]["degree"] == {"in": 0, "out": 1, "total": 1}
    assert all(not entry["is_entry_point"] for entry in default["symbols"])

    everything = search_symbols(
        graph_db, index_root=Path("/repo"), exclude_entry_points=False, kind="function"
    )
    assert [entry["name"] for entry in everything["symbols"]] == ["main", "helper"]
    assert everything["symbols"][0]["entry_point_reason"] == "main"


def test_search_symbols_degree_filters_ignore_unresolved_edges(graph_db: GraphDatabase) -> None:
    """Degree filters count resolved edges only."""
    inbound = search_symbols(
        graph_db,
        index_root=Path("/repo"),
        min_degree=1,
        exclude_entry_points=False,
    )

    names = [entry["name"] for entry in inbound["symbols"]]
    assert "main" in names
    assert "run" in names
    assert "helper" not in names
    assert "App" not in names


def test_search_symbols_regex_and_file_patterns(graph_db: GraphDatabase) -> None:
    """Name/QN regexes and file globs compose with paging."""
    payload = search_symbols(
        graph_db,
        index_root=Path("/repo"),
        name_pattern=r"[A-Z].*",
        file_pattern="src/*.py",
        exclude_entry_points=False,
    )

    assert [entry["name"] for entry in payload["symbols"]] == ["App"]
    assert payload["total"] == 1

    page = search_symbols(graph_db, index_root=Path("/repo"), limit=1, offset=1)
    assert page["returned"] == 1
    assert page["truncated"] is True


def test_search_symbols_invalid_regex_is_an_outcome(graph_db: GraphDatabase) -> None:
    """An invalid regex is reported, never raised or silently ignored."""
    payload = search_symbols(graph_db, name_pattern="[", index_root=Path("/repo"))

    assert payload["outcome"] == "invalid_argument"
    assert "name_pattern" in payload["error"]
    assert payload["symbols"] == []


def test_search_symbols_rejects_file_level_degree_edges(graph_db: GraphDatabase) -> None:
    """IMPORTS is file-level and cannot define a symbol degree filter."""
    payload = search_symbols(graph_db, edge_types=["IMPORTS"], index_root=Path("/repo"))

    assert payload["outcome"] == "invalid_argument"
    assert "IMPORTS is a file-level edge" in payload["error"]


def test_search_symbols_include_connected_is_batched(graph_db: GraphDatabase) -> None:
    """Connected neighbours are attached without duplicating the relation."""
    payload = search_symbols(
        graph_db,
        index_root=Path("/repo"),
        name_pattern="run",
        include_connected=True,
    )

    entry = payload["symbols"][0]
    assert entry["connected"] == [
        {
            "fqn": "/repo/src/app.py::main",
            "name": "main",
            "kind": "function",
            "relation": "CALLS",
            "direction": "outbound",
        }
    ]
    assert "1 matching symbols" in render_symbol_search_text(payload)


def _seed_checksums(db: GraphDatabase) -> None:
    """Add checksum rows for the fixture's indexed files."""
    with db.write_transaction() as conn:
        conn.executemany(
            "INSERT INTO file_checksums (file_path, checksum, size, file_mtime_ns, parse_failed) "
            "VALUES (?, 'abc', 10, 100, 0);",
            [("/repo/src/app.py",), ("/repo/src/other.py",)],
        )


def test_coverage_summary_reports_recorded_gaps(graph_db: GraphDatabase) -> None:
    """The index-wide summary lists recorded gaps with parsed line ranges."""
    _seed_checksums(graph_db)
    with graph_db.write_transaction() as conn:
        conn.execute(
            "UPDATE index_coverage SET line_ranges = '[[3, 4], [9, 9]]' "
            "WHERE file_path = '/repo/src/app.py';"
        )

    payload = check_index_coverage(graph_db, index_root=Path("/repo"))

    assert payload["outcome"] == "resolved"
    assert payload["status"] == "partial"
    assert payload["coverage_complete"] is False
    assert payload["gaps"][0]["file_path"] == "src/app.py"
    assert payload["gaps"][0]["line_ranges"] == [[3, 4], [9, 9]]
    assert payload["summary"]["by_status"] == {"partial": 1}
    assert "partial" in render_coverage_text(payload)


def test_coverage_per_path_distinguishes_clean_and_missing(
    graph_db: GraphDatabase,
) -> None:
    """A clean indexed file is not the same as an unindexed path."""
    _seed_checksums(graph_db)

    payload = check_index_coverage(
        graph_db,
        paths=["src/other.py", "src/missing.py", "src/app.py"],
        index_root=Path("/repo"),
    )

    by_path = {entry["file_path"]: entry for entry in payload["entries"]}
    assert by_path["src/other.py"]["status"] == "no_recorded_issue"
    assert by_path["src/missing.py"]["status"] == "not_indexed"
    assert by_path["src/app.py"]["status"] == "partial"
    assert by_path["src/app.py"]["stored_path"] == "/repo/src/app.py"
    assert by_path["src/missing.py"]["stored_path"] is None
    assert payload["status"] == "not_indexed"


def test_coverage_uses_parser_for_excluded_and_unsupported_paths(
    graph_db: GraphDatabase,
) -> None:
    """The optional parser separates ignore rules from unsupported files."""

    class _Parser:
        def is_excluded_file(self, path: Path, root: Path) -> bool:
            return path.name == "ignored.py"

        def is_supported_file(self, path: Path) -> bool:
            return path.suffix == ".py"

    payload = check_index_coverage(
        graph_db,
        paths=["src/ignored.py", "src/style.xyz"],
        index_root=Path("/repo"),
        parser=_Parser(),
    )

    by_path = {entry["file_path"]: entry for entry in payload["entries"]}
    assert by_path["src/ignored.py"]["status"] == "excluded"
    assert by_path["src/ignored.py"]["kind"] == "excluded_ignore"
    assert by_path["src/style.xyz"]["status"] == "skipped"
    assert by_path["src/style.xyz"]["kind"] == "skipped_extension"


def test_coverage_scope_aggregates_gaps(graph_db: GraphDatabase) -> None:
    """A directory scope reports its file counts and gap files."""
    _seed_checksums(graph_db)

    payload = check_index_coverage(graph_db, scopes=["src"], index_root=Path("/repo"))

    scope = payload["scopes"][0]
    assert scope["scope"] == "src"
    assert scope["indexed_files"] == 2
    assert scope["files_with_gaps"] == 1
    assert scope["status"] == "partial"
    assert scope["gaps"][0]["file_path"] == "src/app.py"


def test_coverage_unavailable_without_generation(tmp_path: Path) -> None:
    """An old index without a generation is explicitly unusable for coverage."""
    db = GraphDatabase(tmp_path / "old.db", Settings(context_dir=tmp_path))
    db.initialize()

    payload = check_index_coverage(db)

    assert payload["outcome"] == "coverage_unavailable"
    assert payload["status"] == "coverage_unavailable"
    assert payload["index_generation"] is None
    assert "Reindex" in payload["recommended_action"]
