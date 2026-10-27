"""Coverage rows and index-generation metadata produced by indexing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import _indexed_components

_CLEAN = """\
def ok():
    return 1
"""

_PARTIAL = """\
def ok():
    return 1


def broken(:
    return 2
"""

_UNUSABLE = "this is not python at all !!!\n" * 10


def _coverage_by_name(comps: dict[str, Any]) -> dict[str, dict[str, Any]]:
    with comps["db"].connect() as conn:
        rows = conn.execute(
            "SELECT file_path, kind, detail, line_ranges, generation "
            "FROM index_coverage ORDER BY file_path, kind;"
        ).fetchall()
    return {Path(row["file_path"]).name: dict(row) for row in rows}


def test_index_records_partial_and_unusable_parse_coverage(tmp_path: Path) -> None:
    """Parse-error ranges become queryable coverage for the current generation."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "clean.py").write_text(_CLEAN)
    (repo / "partial.py").write_text(_PARTIAL)
    (repo / "unusable.py").write_text(_UNUSABLE)

    comps = _indexed_components(repo, repo / ".context")
    coverage = _coverage_by_name(comps)

    assert "clean.py" not in coverage
    assert coverage["partial.py"]["kind"] == "parse_partial"
    assert json.loads(coverage["partial.py"]["line_ranges"])
    assert coverage["unusable.py"]["kind"] == "parse_unusable"
    generation = comps["metadata"].get("index_generation")
    assert generation
    assert {row["generation"] for row in coverage.values()} == {generation}


def test_index_records_oversized_files(tmp_path: Path) -> None:
    """A file above ``max_file_bytes`` is reported instead of silently dropped."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "small.py").write_text(_CLEAN)
    (repo / "big.py").write_text("# filler\n" * 40)

    comps = _indexed_components(repo, repo / ".context", settings_kwargs={"max_file_bytes": 64})
    coverage = _coverage_by_name(comps)

    assert coverage["big.py"]["kind"] == "skipped_oversized"
    assert "small.py" not in coverage
    assert comps["metadata"].get("index_generation")


@pytest.mark.integration
def test_coverage_generation_matches_metadata(tmp_path: Path) -> None:
    """Coverage rows and ``index_generation`` describe the same index run."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "partial.py").write_text(_PARTIAL)

    comps = _indexed_components(repo, repo / ".context")
    coverage = _coverage_by_name(comps)
    assert coverage["partial.py"]["generation"] == comps["metadata"].get("index_generation")
