"""Integration tests for the ``.gitignore`` opt-out wiring.

The ``CODE_SEARCH_RESPECT_GITIGNORE`` environment variable is only useful if
the CLI hands its ``Settings`` to the parser used for discovery. These tests
build the real component registry so a parser created without settings (which
silently defaults to respecting ``.gitignore``) is caught.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from code_search.cli.main import _initialize_components


def _gitignore_repo(tmp_path: Path) -> Path:
    """Create a repository whose ``.gitignore`` excludes ``generated/``.

    Args:
        tmp_path: Temporary directory to create the repository under.

    Returns:
        The repository root.
    """
    repo = tmp_path / "repo"
    (repo / "generated").mkdir(parents=True)
    (repo / "generated" / "artifact.py").write_text("x = 1")
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("y = 2")
    (repo / ".gitignore").write_text("generated/\n")
    return repo


def _discovered(comps: dict[str, Any], repo: Path) -> set[str]:
    """Return the repository-relative paths discovered by *comps*' parser."""
    return {path.relative_to(repo).as_posix() for path in comps["parser"].discover_files(repo)}


def test_cli_parser_honours_gitignore_opt_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``CODE_SEARCH_RESPECT_GITIGNORE=false`` indexes gitignored files."""
    monkeypatch.setenv("CODE_SEARCH_RESPECT_GITIGNORE", "false")
    repo = _gitignore_repo(tmp_path)

    comps = _initialize_components(tmp_path / "ctx")

    assert comps["settings"].respect_gitignore is False
    assert comps["parser"]._respect_gitignore is False
    assert _discovered(comps, repo) == {"generated/artifact.py", "src/main.py"}


def test_cli_parser_respects_gitignore_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without the opt-out, gitignored files stay out of discovery."""
    monkeypatch.delenv("CODE_SEARCH_RESPECT_GITIGNORE", raising=False)
    repo = _gitignore_repo(tmp_path)

    comps = _initialize_components(tmp_path / "ctx")

    assert comps["settings"].respect_gitignore is True
    assert comps["parser"]._respect_gitignore is True
    assert _discovered(comps, repo) == {"src/main.py"}
