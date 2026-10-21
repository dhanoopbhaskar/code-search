"""CLI ``find-related`` parity with the MCP tool."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import FIXTURES_DIR, _indexed_components


@pytest.fixture
def indexed_tsreact(tmp_path: Path) -> dict[str, Any]:
    """Index a copy of the TS/React fixture."""
    repo = tmp_path / "tsreact_repo"
    shutil.copytree(FIXTURES_DIR / "tsreact", repo)
    return _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})


def _run_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    from code_search.cli.main import main

    previous = sys.argv
    sys.argv = ["code-search", *argv]
    code = 0
    try:
        main()
    except SystemExit as exc:
        code = int(exc.code or 0)
    finally:
        sys.argv = previous
    return code, capsys.readouterr().out


def test_cli_find_related_json_is_relative_and_shared(
    indexed_tsreact: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI command returns the shared payload with relative paths."""
    repo: Path = indexed_tsreact["repo"]
    context_dir: Path = indexed_tsreact["context_dir"]
    anchor = repo / "src" / "store" / "articlesSlice.ts"

    code, out = _run_cli(
        [
            "find-related",
            str(anchor),
            "--line",
            "4",
            "--json",
            f"--context-dir={context_dir}",
        ],
        capsys,
    )

    assert code == 0
    payload = json.loads(out)
    assert "results" in payload
    for result in payload["results"]:
        assert not Path(result["file_path"]).is_absolute()
