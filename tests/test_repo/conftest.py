from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--force-index",
        action="store_true",
        default=False,
        help="Force full re-index even if cache exists.",
    )


TEST_REPO = Path(__file__).resolve().parent.parent.parent / "test-repo"


def _run_cs(
    args: list[str], cwd: Path | None = None, timeout: int = 120
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "src.cli.main", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
        env={**os.environ, "NO_COLOR": "1"},
    )


@pytest.fixture(scope="session")
def repo_path() -> Path:
    """The initialized ``test-repo`` submodule, or skip when it is unavailable.

    CI checks out the repository without submodules, so the submodule directory
    is either absent or an empty placeholder. Skip these tests instead of
    failing so the rest of the suite still runs.
    """
    if not TEST_REPO.exists() or not any(TEST_REPO.iterdir()):
        pytest.skip(
            f"test-repo not available at {TEST_REPO}; "
            "run `git submodule update --init` to enable these tests."
        )
    return TEST_REPO


@pytest.fixture(scope="session")
def indexed(repo_path: Path, pytestconfig: pytest.Config) -> dict[str, object]:
    keep = pytestconfig.getoption("--keep-index")
    force = pytestconfig.getoption("--force-index")
    context_dir = repo_path / ".context"

    if keep and context_dir.exists() and (context_dir / "graph.db").exists() and not force:
        return {"repo_path": repo_path, "context_dir": context_dir, "cached": True}

    if context_dir.exists():
        shutil.rmtree(context_dir)

    result = _run_cs(
        ["index", "--path", str(repo_path), "--force", "--include-resources", "--include-tests"],
        cwd=repo_path,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"Index failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert context_dir.exists()
    assert (context_dir / "graph.db").exists()

    return {"repo_path": repo_path, "context_dir": context_dir, "cached": False}
