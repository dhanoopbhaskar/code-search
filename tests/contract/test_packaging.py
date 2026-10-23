"""Contract tests for the files shipped in built distributions."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.contract
def test_embedding_model_is_declared_as_wheel_data() -> None:
    """The model must ship with wheels built from a git checkout."""
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    data_files = config["tool"]["setuptools"]["data-files"]
    target = "share/code-search/models/potion-code-16m-32d"

    assert target in data_files
    patterns = data_files[target]
    files = [path for pattern in patterns for path in REPO_ROOT.glob(pattern)]
    assert any(path.name == "model.safetensors" for path in files)
