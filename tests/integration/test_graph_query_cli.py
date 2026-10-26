"""CLI acceptance tests for the graph-query commands."""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import FIXTURES_DIR, _indexed_components


@pytest.fixture
def indexed_multihop_cli(tmp_path: Path) -> Generator[tuple[dict[str, Any], Path], None, None]:
    """Index the multi-hop fixture and expose its context directory."""
    repo = tmp_path / "multihop"
    shutil.copytree(FIXTURES_DIR / "multihop", repo)
    context_dir = tmp_path / ".context"
    comps = _indexed_components(repo, context_dir)
    yield comps, context_dir


def _run_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    """Run the real CLI entry point and capture stdout."""
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


@pytest.mark.integration
def test_cli_query_json(
    indexed_multihop_cli: tuple[dict[str, Any], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``query --json`` returns a structured graph answer."""
    _comps, context_dir = indexed_multihop_cli
    code, out = _run_cli(
        [
            "query",
            "how does favoriting an article flow from the controller to the repository",
            "--json",
            f"--context-dir={context_dir}",
        ],
        capsys,
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["outcome"] == "resolved"
    assert payload["nodes"]
    assert payload["edges"]
    assert "freshness" in payload
    assert all("confidence" in edge for edge in payload["edges"])


@pytest.mark.integration
def test_cli_path_json(
    indexed_multihop_cli: tuple[dict[str, Any], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``path --json`` returns the known directed call chain."""
    _comps, context_dir = indexed_multihop_cli
    code, out = _run_cli(
        [
            "path",
            "ArticleController.favoriteArticle",
            "ArticleRepository.save",
            "--json",
            f"--context-dir={context_dir}",
        ],
        capsys,
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["outcome"] == "resolved"
    assert [hop["relation"] for hop in payload["hops"]] == ["CALLS", "CALLS"]


@pytest.mark.integration
def test_cli_explain_json(
    indexed_multihop_cli: tuple[dict[str, Any], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``explain --json`` surfaces rationale comments."""
    _comps, context_dir = indexed_multihop_cli
    code, out = _run_cli(
        ["explain", "ArticleService.favorite", "--json", f"--context-dir={context_dir}"],
        capsys,
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["outcome"] == "resolved"
    assert payload["rationale"]
    assert payload["rationale"][0]["kind"] == "why"


@pytest.mark.integration
def test_cli_affected_json(
    indexed_multihop_cli: tuple[dict[str, Any], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``affected --json`` reverse-traverses from a changed file."""
    comps, context_dir = indexed_multihop_cli
    repo = Path(comps["metadata"].get("index_root"))
    changed = repo / "src/main/java/com/example/core/ArticleRepository.java"
    code, out = _run_cli(
        ["affected", str(changed), "--json", f"--context-dir={context_dir}"],
        capsys,
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["summary"]["symbols"] > 0
    names = {node["fqn"].rsplit("::", 1)[-1].split("(", 1)[0] for node in payload["symbols"]}
    assert any(name.startswith("ArticleService") for name in names)


@pytest.mark.integration
def test_cli_map_json(
    indexed_multihop_cli: tuple[dict[str, Any], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``map --json`` returns god nodes and import statistics."""
    _comps, context_dir = indexed_multihop_cli
    code, out = _run_cli(
        ["map", "--json", "--top", "5", f"--context-dir={context_dir}"],
        capsys,
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["god_nodes"]
    assert payload["edge_stats"]
