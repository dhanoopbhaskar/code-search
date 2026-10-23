"""Tests for recovering the index from an interrupted run."""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from code_search.cli import main


def _args(repo: Path, context_dir: Path) -> SimpleNamespace:
    """Build the argument namespace consumed by ``cmd_index``."""
    return SimpleNamespace(
        path=str(repo),
        context_dir=str(context_dir),
        verbose=False,
        prune_stale=False,
        exclude=None,
        include_resources=False,
        exclude_resources=False,
        resource_extensions=None,
        include_tests=True,
        force=False,
        incremental=False,
        watch=False,
    )


def _components(context_dir: Path) -> tuple[dict[str, Any], Mock, Mock]:
    """Return a component registry with a mocked metadata/orchestrator pair."""
    metadata = Mock()
    metadata.get_index_status.return_value = "indexing"
    orchestrator = Mock()
    orchestrator.index_codebase.return_value = {
        "total_files": 1,
        "total_symbols": 1,
        "total_chunks": 1,
        "languages": ["python"],
        "duration_s": 0.1,
    }
    comps: dict[str, Any] = {
        "settings": SimpleNamespace(lock_timeout=30.0, resource_extensions=()),
        "metadata": metadata,
        "embedding_gen": Mock(is_available=Mock(return_value=True)),
        "orchestrator": orchestrator,
    }
    return comps, metadata, orchestrator


def _patch(monkeypatch: pytest.MonkeyPatch, comps: dict[str, Any]) -> None:
    """Replace component wiring and model-profile validation."""

    def _components_for(_context: Path, **_kwargs: Any) -> dict[str, Any]:
        return comps

    monkeypatch.setattr(main, "_initialize_components", _components_for)
    monkeypatch.setattr(main, "_check_model_profile", lambda _: None)


def test_live_index_lock_blocks_a_second_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    context_dir = repo / ".context"
    context_dir.mkdir()
    (context_dir / "index.lock").write_text("lock")
    comps, _, orchestrator = _components(context_dir)
    _patch(monkeypatch, comps)

    assert main.cmd_index(_args(repo, context_dir)) == 2
    orchestrator.index_codebase.assert_not_called()


def test_stale_indexing_status_without_lock_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    context_dir = repo / ".context"
    context_dir.mkdir()
    comps, metadata, orchestrator = _components(context_dir)
    _patch(monkeypatch, comps)

    assert main.cmd_index(_args(repo, context_dir)) == 0
    metadata.set_index_status.assert_called_once_with("stale")
    orchestrator.index_codebase.assert_called_once()


def test_old_index_lock_is_treated_as_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    context_dir = repo / ".context"
    context_dir.mkdir()
    lock_path = context_dir / "index.lock"
    lock_path.write_text("lock")
    old = time.time() - 3600
    os.utime(lock_path, (old, old))
    comps, metadata, orchestrator = _components(context_dir)
    _patch(monkeypatch, comps)

    assert main.cmd_index(_args(repo, context_dir)) == 0
    assert not lock_path.exists()
    metadata.set_index_status.assert_called_once_with("stale")
    orchestrator.index_codebase.assert_called_once()
