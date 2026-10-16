"""Tests for the CLI's indexing progress reporter."""

from __future__ import annotations

import pytest

from code_search.cli.main import _make_index_progress_reporter


def test_reporter_prints_at_each_ten_percent_milestone(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _make_index_progress_reporter()
    for completed in range(1, 101):
        report("parsing", completed, 100)

    lines = capsys.readouterr().err.strip().splitlines()
    assert lines[0] == "Indexing parsing: 10% (10/100)"
    assert lines[-1] == "Indexing parsing: 100% (100/100)"
    assert len(lines) == 10


def test_reporter_tracks_milestones_per_phase(capsys: pytest.CaptureFixture[str]) -> None:
    report = _make_index_progress_reporter()
    report("parsing", 10, 100)
    report("embedding", 10, 100)

    err = capsys.readouterr().err
    assert "Indexing parsing: 10%" in err
    assert "Indexing embedding: 10%" in err


def test_reporter_ignores_empty_and_below_threshold_totals(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _make_index_progress_reporter()
    report("parsing", 0, 0)
    report("parsing", 5, 100)

    assert capsys.readouterr().err == ""
