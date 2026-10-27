"""Tests for daemon-managed live index refresh."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from code_search.engine.index_service import LiveIndexUpdater


class _FakeMetadata:
    """Minimal metadata store exposing the recorded discovery policy."""

    def __init__(self, root: Path) -> None:
        self._values = {
            "index_root": str(root),
            "index_include_tests": "false",
            "index_include_resources": "true",
        }
        self._json = {
            "index_resource_extensions": [".xml", ".properties"],
            "index_exclusion_patterns": ["generated"],
        }

    def get(self, key: str) -> str | None:
        return self._values.get(key)

    def get_json(self, key: str) -> Any:
        return self._json.get(key)


class _FakeOrchestrator:
    """Records the policy passed to an incremental index run."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def index_codebase(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"total_files": 1, "total_symbols": 2}


class _FakeVector:
    def __init__(self) -> None:
        self.loaded = 0

    def load(self) -> None:
        self.loaded += 1


class _FakeSearch:
    def __init__(self) -> None:
        self.resets = 0
        self._embedding_generator = None

    def reset_caches(self) -> None:
        self.resets += 1


class _FakeDetector:
    def __init__(self) -> None:
        self.completed = 0

    def mark_reload_complete(self, _metadata: Any) -> None:
        self.completed += 1


class _FakeWatcher:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


@pytest.fixture
def live_components(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Component registry with a stubbed watcher and real updater logic."""
    fake_watcher = _FakeWatcher()
    monkeypatch.setattr(
        "code_search.engine.watcher.create_watcher",
        lambda **_kwargs: fake_watcher,
    )
    root = tmp_path / "repo"
    root.mkdir()
    orchestrator = _FakeOrchestrator()
    vector = _FakeVector()
    search = _FakeSearch()
    detector = _FakeDetector()
    metadata = _FakeMetadata(root)
    comps: dict[str, Any] = {
        "metadata": metadata,
        "orchestrator": orchestrator,
        "vector_index": vector,
        "search": search,
        "embedding_gen": object(),
        "index_change_detector": detector,
        "settings": type("Settings", (), {"watch_debounce_seconds": 0.01})(),
        "context_dir": tmp_path / ".context",
    }
    comps["_watcher"] = fake_watcher
    return comps


def test_reindex_uses_the_recorded_discovery_policy(live_components: dict[str, Any]) -> None:
    """An incremental run passes the indexing policy stored at index time."""
    updater = LiveIndexUpdater(live_components)
    summary = updater.reindex_once()

    assert summary == {"total_files": 1, "total_symbols": 2}
    call = live_components["orchestrator"].calls[0]
    assert call["incremental"] is True
    assert call["include_tests"] is False
    assert call["include_resources"] is True
    assert call["resource_extensions"] == (".xml", ".properties")
    assert "generated" in call["exclusion_patterns"]
    assert ".context" in call["exclusion_patterns"]


def test_reindex_reloads_vectors_and_search_caches(live_components: dict[str, Any]) -> None:
    """A completed run reloads vectors, resets caches, and updates the detector."""
    updater = LiveIndexUpdater(live_components)
    updater.reindex_once()

    assert live_components["vector_index"].loaded == 1
    assert live_components["search"].resets == 1
    assert live_components["index_change_detector"].completed == 1


def test_failed_reindex_keeps_the_previous_index(live_components: dict[str, Any]) -> None:
    """A failing incremental run is logged and does not reload state."""

    def _fail(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("lock held")

    live_components["orchestrator"].index_codebase = _fail
    updater = LiveIndexUpdater(live_components)
    assert updater.reindex_once() is None
    assert live_components["vector_index"].loaded == 0
    assert live_components["search"].resets == 0


def test_start_stop_delegate_to_the_watcher(live_components: dict[str, Any]) -> None:
    """The daemon lifecycle owns the watcher lifecycle."""
    updater = LiveIndexUpdater(live_components)
    updater.start()
    updater.stop()
    assert live_components["_watcher"].started == 1
    assert live_components["_watcher"].stopped == 1


def test_root_defaults_to_the_recorded_index_root(live_components: dict[str, Any]) -> None:
    """The watcher follows the indexed tree, not the context directory."""
    updater = LiveIndexUpdater(live_components)
    assert updater.root_path == Path(live_components["metadata"].get("index_root") or "")
