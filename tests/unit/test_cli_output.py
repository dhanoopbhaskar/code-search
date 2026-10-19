"""Human CLI output uses the indexed root and basename-qualified symbols.

Machine-readable JSON intentionally keeps absolute paths; these tests cover the
table/list renderers that users read directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_search.cli.main import (
    _print_ambiguous_candidates,
    _print_graph_results,
    _print_implementations,
    _print_search_results,
    _print_symbol_details,
)
from code_search.engine.config import Settings


def test_search_table_uses_relative_paths_and_basename_symbols(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The search table hides the absolute root and the FQN path prefix."""
    source = tmp_path / "src" / "main" / "TokenService.java"
    _print_search_results(
        [
            {
                "score": 0.9,
                "file_path": str(source),
                "line_start": 10,
                "line_end": 12,
                "fqn": f"{source}::TokenService.generateToken",
                "content": "String token = generate();",
            }
        ],
        Settings(context_dir=tmp_path),
        root=tmp_path,
    )

    out = capsys.readouterr().out
    assert "src/main/TokenService.java:10-12" in out
    assert "TokenService.generateToken" in out
    assert str(tmp_path) not in out


def test_symbol_details_use_relative_location_and_basename_fqn(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Symbol identity and location omit the filesystem prefix."""
    source = tmp_path / "src" / "Repo.java"
    _print_symbol_details(
        {
            "name": "save",
            "fqn": f"{source}::Repo.save",
            "kind": "method",
            "file_path": str(source),
            "line_start": 5,
            "line_end": 6,
        },
        {"fqn": f"{source}::Repo", "kind": "class"},
        root=tmp_path,
    )

    out = capsys.readouterr().out
    assert "FQN:    Repo.save" in out
    assert "File:   src/Repo.java:5-6" in out
    assert "Parent: Repo (class)" in out
    assert str(tmp_path) not in out


def test_implementations_use_relative_locations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Implementation headings and sites omit the absolute index root."""
    declaring = tmp_path / "src" / "Repo.java"
    implementation = tmp_path / "src" / "RepoImpl.java"
    _print_implementations(
        {
            "outcome": "found",
            "declaring_type": {"fqn": f"{declaring}::Repo"},
            "implementations": [
                {
                    "type": {
                        "fqn": f"{implementation}::RepoImpl",
                        "file_path": str(implementation),
                        "line_start": 4,
                    },
                    "site": {
                        "fqn": f"{implementation}::RepoImpl.save",
                        "file_path": str(implementation),
                        "line_start": 9,
                        "inherited": False,
                    },
                    "relationship": "direct",
                }
            ],
        },
        "Repo.save",
        root=tmp_path,
    )

    out = capsys.readouterr().out
    assert "Implementations of Repo.save via Repo" in out
    assert "RepoImpl  (direct, declared)" in out
    assert "src/RepoImpl.java:9" in out
    assert str(tmp_path) not in out


def test_graph_and_ambiguous_outputs_are_relative(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Call-graph and ambiguity lists share the same display rules."""
    source = tmp_path / "src" / "Repo.java"
    caller = {
        "fqn": f"{source}::Service.load",
        "file_path": str(source),
        "line_start": 20,
    }
    _print_graph_results({"fqn": f"{source}::Repo.save"}, [caller], [], root=tmp_path)
    _print_ambiguous_candidates(
        "save",
        [
            {
                "fqn": f"{source}::Repo.save",
                "name": "save",
                "kind": "method",
                "file_path": str(source),
                "line_start": 5,
                "line_end": 6,
            }
        ],
        root=tmp_path,
    )

    out = capsys.readouterr().out
    assert "Call graph for: Repo.save" in out
    assert "Service.load" in out
    assert "src/Repo.java:20" in out
    assert "Repo.save (save, method) @ src/Repo.java:5-6" in out
    assert str(tmp_path) not in out
