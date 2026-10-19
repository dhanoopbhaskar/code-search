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
    PathAnswer,
    edge_resolution_stats,
    render_architecture_markdown,
    render_explain_text,
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


def test_edge_store_imports_are_not_symbol_edges(tmp_path: Path) -> None:
    """Module edges live in their own table and do not pollute graph_edges."""
    db = GraphDatabase(tmp_path / "graph.db", Settings(context_dir=tmp_path))
    db.initialize()
    store = EdgeStore(db)
    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM graph_edges;").fetchone()["c"]
    assert count == 0
    assert store.get_call_graph(1) == {"callers": [], "callees": []}
