import json
import sys
from pathlib import Path
from typing import Any

import pytest


def _run_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    from src.cli.main import main

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
def test_cli_verbose_before_subcommand() -> None:
    from src.cli.main import main

    test_args = ["code-search", "--verbose", "list-languages"]
    try:
        sys.argv = test_args
        main()
    except SystemExit as e:
        assert e.code == 0, f"Expected exit code 0, got {e.code}"


@pytest.mark.integration
def test_cli_verbose_after_subcommand() -> None:
    from src.cli.main import main

    test_args = ["code-search", "list-languages", "--verbose"]
    try:
        sys.argv = test_args
        main()
    except SystemExit as e:
        assert e.code == 0, f"Expected exit code 0, got {e.code}"


@pytest.mark.integration
def test_cli_context_dir_before_subcommand(tmp_path: Path) -> None:
    from src.cli.main import main

    ctx_dir = tmp_path / ".context"
    ctx_dir.mkdir()
    test_args = ["code-search", f"--context-dir={ctx_dir}", "list-languages"]
    try:
        sys.argv = test_args
        main()
    except SystemExit as e:
        assert e.code == 0, f"Expected exit code 0, got {e.code}"


@pytest.mark.integration
def test_cli_context_dir_after_subcommand(tmp_path: Path) -> None:
    from src.cli.main import main

    ctx_dir = tmp_path / ".context"
    ctx_dir.mkdir()
    test_args = ["code-search", "list-languages", f"--context-dir={ctx_dir}"]
    try:
        sys.argv = test_args
        main()
    except SystemExit as e:
        assert e.code == 0, f"Expected exit code 0, got {e.code}"


@pytest.mark.integration
def test_cli_implementations_json(
    indexed_implementations: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    fqn = indexed_implementations["symbol_fqns"][("python", "Animal", "speak")][0]
    code, out = _run_cli(
        [
            "implementations",
            fqn,
            "--json",
            f"--context-dir={indexed_implementations['context_dir']}",
        ],
        capsys,
    )
    assert code == 0
    envelope = json.loads(out)
    assert envelope["outcome"] == "resolved"
    assert envelope["implementations"]
    assert "freshness" in envelope
    assert isinstance(envelope["query_time_ms"], (int, float))


@pytest.mark.integration
def test_cli_implementations_human(
    indexed_implementations: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    fqn = indexed_implementations["symbol_fqns"][("python", "Animal", "speak")][0]
    code, out = _run_cli(
        ["implementations", fqn, f"--context-dir={indexed_implementations['context_dir']}"],
        capsys,
    )
    assert code == 0
    assert "Dog" in out
    assert "direct" in out


@pytest.mark.integration
def test_cli_implementations_not_found_exits_zero(
    indexed_implementations: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run_cli(
        [
            "implementations",
            "does.not.Exist",
            "--json",
            f"--context-dir={indexed_implementations['context_dir']}",
        ],
        capsys,
    )
    assert code == 0
    assert json.loads(out)["outcome"] == "not_found"


@pytest.mark.integration
def test_cli_graph_implements_direction(
    indexed_implementations: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    fqn = indexed_implementations["symbol_fqns"][("python", "Animal", "speak")][0]
    code, out = _run_cli(
        [
            "graph",
            fqn,
            "--direction",
            "implements",
            "--json",
            f"--context-dir={indexed_implementations['context_dir']}",
        ],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    assert data["implementations"]
    assert data["callers"] == []
    assert data["callees"] == []


@pytest.mark.integration
def test_cli_context_dir_conflicting_values(tmp_path: Path) -> None:
    from src.cli.main import main

    ctx_dir1 = tmp_path / ".context1"
    ctx_dir1.mkdir()
    ctx_dir2 = tmp_path / ".context2"
    ctx_dir2.mkdir()
    test_args = [
        "code-search",
        f"--context-dir={ctx_dir1}",
        "list-languages",
        f"--context-dir={ctx_dir2}",
    ]
    try:
        sys.argv = test_args
        main()
    except SystemExit as e:
        assert e.code == 0, f"Expected exit code 0, got {e.code}"
