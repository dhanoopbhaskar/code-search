from __future__ import annotations

from pathlib import Path

from code_search.engine.response_service import (
    compact_result,
    compact_results,
    relativize_results,
)


def test_compact_result_keeps_location_signature_and_snippet() -> None:
    """Compact results drop the score envelope but preserve navigation data."""
    result = {
        "chunk_id": 1,
        "file_path": "/repo/src/settings.ts",
        "line_start": 10,
        "line_end": 40,
        "fqn": "/repo/src/settings.ts::baseApiUrl",
        "language": "typescript",
        "score": 0.9,
        "is_definition": True,
        "content": "\n".join(f"line {i}" for i in range(1, 31)),
        "score_sources": {"bm25": 1.0},
        "bm25_score": 1.0,
        "vector_score": 0.5,
    }

    compact = compact_result(result, max_snippet_lines=3)

    assert compact["file_path"] == result["file_path"]
    assert compact["line_start"] == 10
    assert compact["line_end"] == 40
    assert compact["signature"] == "line 1"
    assert compact["content"] == "line 1\nline 2\nline 3"
    assert compact["content_truncated"] is True
    assert "score_sources" not in compact
    assert "bm25_score" not in compact


def test_compact_results_preserves_order() -> None:
    """Compacting a list never reorders the ranked results."""
    results = [{"chunk_id": i, "content": "x"} for i in range(3)]
    assert [r["chunk_id"] for r in compact_results(results)] == [0, 1, 2]


def test_relativize_results_strips_index_root(tmp_path: Path) -> None:
    """Machine-readable paths/fqn prefixes become portable relative spellings."""
    source = tmp_path / "src" / "settings.ts"
    results = [
        {
            "file_path": str(source),
            "fqn": f"{source}::baseApiUrl",
        }
    ]

    relative = relativize_results(results, tmp_path)

    assert relative[0]["file_path"] == "src/settings.ts"
    assert relative[0]["fqn"] == "src/settings.ts::baseApiUrl"
    assert results[0]["file_path"] == str(source)
