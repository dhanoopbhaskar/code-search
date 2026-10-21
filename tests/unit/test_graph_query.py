"""Unit tests for graph-query provenance, rendering, and metrics."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_search.engine.config import Settings
from code_search.engine.graph import EdgeStore, GraphDatabase
from code_search.engine.graph_query import (
    ArchitectureReport,
    ExplainAnswer,
    GraphAnswer,
    GraphEdge,
    GraphNode,
    ImpactAnswer,
    PathAnswer,
    display_symbol,
    edge_resolution_stats,
    render_architecture_markdown,
    render_explain_text,
    render_impact_text,
    render_path_text,
    render_query_text,
    resolve_confidence,
)


@pytest.mark.parametrize(
    ("tier", "resolved", "expected"),
    [
        ("exact", True, "EXTRACTED"),
        ("conventional", True, "EXTRACTED"),
        ("same_file", True, "INFERRED"),
        ("range", True, "INFERRED"),
        ("fallback", True, "AMBIGUOUS"),
        (None, True, "INFERRED"),
        ("exact", False, "UNRESOLVED"),
    ],
)
def test_resolve_confidence(tier: str | None, resolved: bool, expected: str) -> None:
    """Resolution tiers map to the documented provenance labels."""
    assert resolve_confidence(tier, resolved) == expected


def test_edge_resolution_stats(tmp_path: Path) -> None:
    """Per-edge-type resolution counts and ratios are reported."""
    db = GraphDatabase(tmp_path / "graph.db", Settings(context_dir=tmp_path))
    db.initialize()
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) "
            "VALUES ('f::a', 'a', 'function', 'f', 0, 1, 0, 1, 'python');"
        )
        source = conn.execute("SELECT last_insert_rowid() AS id;").fetchone()["id"]
        conn.execute(
            "INSERT INTO graph_edges (source_symbol_id, target_symbol_id, edge_type, "
            "resolution_tier, resolved, target_raw) VALUES (?, NULL, 'CALLS', NULL, 0, 'ext');",
            (source,),
        )
    stats = edge_resolution_stats(db)
    assert stats["CALLS"]["total"] == 1
    assert stats["CALLS"]["unresolved"] == 1
    assert stats["CALLS"]["ratio"] == 0


def test_render_query_text_marks_seeds_and_confidence() -> None:
    """The compact renderer marks seeds and renders provenance."""
    seed = GraphNode("f::A", "f::A", "A", "function", "f", 1, 2)
    other = GraphNode("f::B", "f::B", "B", "function", "f", 3, 4, distance=1)
    edge = GraphEdge("f::A", "f::B", "CALLS", "EXTRACTED")
    answer = GraphAnswer("how", seeds=[seed], nodes=[seed, other], edges=[edge])
    text = render_query_text(answer)
    assert "* f::A" in text
    assert "f::A --CALLS/EXTRACTED--> f::B" in text


def test_render_path_text_handles_no_path() -> None:
    """A refused path renders its explanation and candidates."""
    answer = PathAnswer(
        outcome="ambiguous",
        explanation="ambiguous source",
        candidates=[{"fqn": "f::A"}],
    )
    text = render_path_text(answer)
    assert "ambiguous" in text
    assert "f::A" in text


def test_render_explain_text_includes_rationale() -> None:
    """Explain output includes rationale kind, location, and text."""
    node = GraphNode("f::A", "f::A", "A", "method", "f", 1, 2)
    answer = ExplainAnswer(
        symbol=node,
        nodes=[node],
        rationale=[
            {
                "kind": "why",
                "file_path": "f",
                "line_start": 2,
                "text": "// WHY: keep the read path fast",
            }
        ],
    )
    text = render_explain_text(answer)
    assert "why f:2" in text
    assert "keep the read path fast" in text


def test_render_architecture_markdown_is_deterministic() -> None:
    """Markdown sections appear in a stable order."""
    report = ArchitectureReport(
        god_nodes=[{"fqn": "f::A", "kind": "class", "degree": 4, "file_path": "f"}],
        communities=[
            {
                "label": 1,
                "label_fqn": "f::A",
                "size": 2,
                "members": [{"id": 1, "fqn": "f::A"}, {"id": 2, "fqn": "f::B"}],
            }
        ],
        import_cycles=[["a.py", "b.py", "a.py"]],
        edge_stats={"CALLS": {"total": 1, "resolved": 1, "unresolved": 0, "ratio": 1000}},
        suggested_questions=["How does f::A work?"],
        stats={"symbols": 2, "edges": 1},
    )
    text = render_architecture_markdown(report)
    assert text.index("## God nodes") < text.index("## Communities")
    assert "a.py -> b.py -> a.py" in text
    assert text == render_architecture_markdown(report)


def test_display_symbol_drops_filesystem_prefix_only() -> None:
    """Absolute path prefixes are hidden while logical module prefixes remain."""
    assert (
        display_symbol("/repo/src/main/java/example/ArticleController.java::ArticleController")
        == "ArticleController"
    )
    assert display_symbol("pkg.module::Thing") == "pkg.module::Thing"


def test_render_query_text_uses_relative_paths(tmp_path: Path) -> None:
    """Node grouping uses paths relative to the indexed root."""
    node = GraphNode("abs::A", "abs::A", "A", "class", str(tmp_path / "src/A.java"), 1, 2)
    answer = GraphAnswer("how", seeds=[node], nodes=[node], edges=[])
    text = render_query_text(answer, root=tmp_path)
    assert "src/A.java" in text
    assert str(tmp_path) not in text
    assert "abs::A" in text


def test_render_explain_text_compacts_containment_into_members() -> None:
    """Containment edges render as a member list, not relation noise."""
    symbol = GraphNode("abs::A", "abs::A", "A", "class", "/repo/A.java", 1, 2)
    member = GraphNode("abs::A.run()", "abs::A.run()", "run", "method", "/repo/A.java", 3, 4)
    edge = GraphEdge("abs::A", "abs::A.run()", "CONTAINS", "EXTRACTED")
    answer = ExplainAnswer(symbol=symbol, nodes=[symbol, member], edges=[edge])
    text = render_explain_text(answer, root="/repo")
    assert "members (1):" in text
    assert "A.run() (method)" in text
    assert "--CONTAINS" not in text


def test_render_impact_text_separates_production_and_tests(tmp_path: Path) -> None:
    """Impact output buckets test files separately and relativises paths."""
    prod = GraphNode("abs::A", "abs::A", "A", "class", str(tmp_path / "src/A.java"), 1, 2)
    test = GraphNode(
        "abs::ATest", "abs::ATest", "ATest", "class", str(tmp_path / "tests/ATest.java"), 1, 2
    )
    answer = ImpactAnswer(
        impacted=[prod, test],
        files=["src/A.java", "tests/ATest.java"],
        production_files=["src/A.java"],
        test_files=["tests/ATest.java"],
        summary={"symbols": 2, "files": 2, "tests": 1, "changed_files": 1},
    )
    text = render_impact_text(answer, root=tmp_path)
    assert "production (1 files):" in text
    assert "tests (1 files):" in text
    assert "src/A.java" in text
    assert "tests/ATest.java" in text
    assert str(tmp_path) not in text


def test_edge_store_imports_are_not_symbol_edges(tmp_path: Path) -> None:
    """Module edges live in their own table and do not pollute graph_edges."""
    db = GraphDatabase(tmp_path / "graph.db", Settings(context_dir=tmp_path))
    db.initialize()
    store = EdgeStore(db)
    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM graph_edges;").fetchone()["c"]
    assert count == 0
    assert store.get_call_graph(1) == {"callers": [], "callees": []}


def test_render_architecture_reports_graph_coverage() -> None:
    """The map report makes extraction/resolution coverage visible."""
    report = ArchitectureReport(
        stats={
            "symbols": 3,
            "symbols_extracted": 4,
            "symbol_coverage": 0.75,
            "edges": 2,
            "edges_total": 4,
            "edges_resolved": 3,
            "edge_coverage": 0.75,
        }
    )
    text = render_architecture_markdown(report)
    assert "Symbol coverage: 75.0% (3 connected / 4 extracted)" in text
    assert "Edge coverage: 75.0% (3 / 4)" in text
