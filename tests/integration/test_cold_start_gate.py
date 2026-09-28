"""Fast mechanism gate for cold-start latency.

Non-``benchmark`` and included in ``scripts/check.sh``: asserts the *mechanism*
deterministically — the reduced cold path is fast and correctly labelled, the
warm path stays hybrid and within the recorded baseline, concurrent first
queries trigger exactly one load, and a missing/corrupt model degrades promptly
without hanging.
"""

from __future__ import annotations

import shutil
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import FIXTURES_DIR, _indexed_components

COLD_BUDGET_MS = 200.0
WARM_BASELINE_MS = 100.0


@pytest.fixture(scope="module")
def gate_components(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One indexed relevance corpus shared by the gate tests."""
    tmp = tmp_path_factory.mktemp("cold_start_gate")
    repo = tmp / "r"
    shutil.copytree(FIXTURES_DIR / "relevance", repo)
    return _indexed_components(repo, tmp / "ctx", settings_kwargs={"index_prose": True})


@pytest.fixture
def cold_generator(gate_components: dict[str, Any]) -> Iterator[Any]:
    """A fresh generator over the gate index, with a controlled cold state."""
    from src.engine import embeddings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex

    saved_instance = embeddings._model_instance
    saved_path = embeddings._loaded_model_path
    embeddings._model_instance = None
    try:
        settings = gate_components["settings"]
        gen = EmbeddingGenerator(settings)
        index = VectorIndex(
            gate_components["context_dir"] / "vectors.bin",
            gate_components["context_dir"] / "vectors.meta.json",
        )
        index.load()
        yield {"gen": gen, "index": index, "settings": settings}
    finally:
        embeddings._model_instance = saved_instance
        embeddings._loaded_model_path = saved_path


def test_reduced_first_query_within_budget_and_labelled(
    gate_components: dict[str, Any], cold_generator: dict[str, Any]
) -> None:
    """The reduced first query returns under budget, labelled."""
    from src.engine.search import HybridSearch

    search = HybridSearch(
        gate_components["db"],
        cold_generator["index"],
        cold_generator["gen"],
        cold_generator["settings"],
    )
    start = time.monotonic()
    envelope = search.search("how do comments get created", limit=5)
    elapsed = (time.monotonic() - start) * 1000.0
    assert envelope["ranked_path"] == "lexical_reduced"
    assert envelope["degraded_reason"] == "warming"
    assert envelope["model_status"]["state"] == "initializing"
    assert elapsed < COLD_BUDGET_MS, f"reduced first query took {elapsed:.0f} ms"


def test_warm_path_is_hybrid_and_not_regressed(gate_components: dict[str, Any]) -> None:
    """The warm path stays hybrid and within the baseline."""
    search = gate_components["search"]
    search.search("how do comments get created", limit=5)
    start = time.monotonic()
    envelope = search.search("how do comments get created", limit=5)
    elapsed = (time.monotonic() - start) * 1000.0
    assert envelope["ranked_path"] == "hybrid"
    assert envelope["warmup_state"] == "warm"
    assert envelope["degraded_reason"] is None
    assert elapsed < WARM_BASELINE_MS, f"warm query took {elapsed:.0f} ms"


def test_concurrent_first_queries_trigger_one_load(
    gate_components: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concurrent first queries trigger exactly one model load."""
    from src.engine import embeddings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.search import HybridSearch

    original = embeddings._load_model
    state = {"loads": 0}

    def counting(settings: Any = None) -> Any:
        before = embeddings._model_instance
        result = original(settings)
        after = embeddings._model_instance
        if before is None and after is not None and after is not embeddings._LOAD_FAILED_SENTINEL:
            state["loads"] += 1
        return result

    saved_instance = embeddings._model_instance
    saved_path = embeddings._loaded_model_path
    embeddings._model_instance = None
    monkeypatch.setattr(embeddings, "_load_model", counting)
    try:
        settings = gate_components["settings"]
        gen = EmbeddingGenerator(settings)
        index = VectorIndex(
            gate_components["context_dir"] / "vectors.bin",
            gate_components["context_dir"] / "vectors.meta.json",
        )
        index.load()
        search = HybridSearch(gate_components["db"], index, gen, settings)

        errors: list[Exception] = []

        def run() -> None:
            try:
                search.search("how do comments get created", limit=5)
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=run) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert not errors, errors
        assert gen.wait_warm(30.0) is True
        assert state["loads"] == 1
    finally:
        embeddings._load_model = original
        embeddings._model_instance = saved_instance
        embeddings._loaded_model_path = saved_path


def test_missing_model_degrades_promptly_without_hanging(
    gate_components: dict[str, Any],
) -> None:
    """An unusable vector layer degrades promptly, never hangs."""
    from pathlib import Path

    from src.engine.embeddings import VectorIndex
    from src.engine.search import HybridSearch

    context_dir = Path(gate_components["context_dir"])
    empty = VectorIndex(context_dir / "empty.bin", context_dir / "empty.meta.json")
    empty.load()
    search = HybridSearch(
        gate_components["db"], empty, gate_components["embedding_gen"], gate_components["settings"]
    )
    start = time.monotonic()
    envelope = search.search("how do comments get created", limit=5)
    elapsed = (time.monotonic() - start) * 1000.0
    assert envelope["ranked_path"] == "lexical_degraded"
    assert envelope["degraded_reason"] == "model_unavailable"
    assert elapsed < 5000.0, f"degraded path hung for {elapsed:.0f} ms"


def test_repeated_resets_do_not_accumulate_loads(
    gate_components: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated warm/reset cycles re-warm without accumulating duplicate loads."""
    from src.engine import embeddings
    from src.engine.embeddings import EmbeddingGenerator

    original = embeddings._load_model
    state = {"loads": 0}

    def counting(settings: Any = None) -> Any:
        before = embeddings._model_instance
        result = original(settings)
        after = embeddings._model_instance
        if before is None and after is not None and after is not embeddings._LOAD_FAILED_SENTINEL:
            state["loads"] += 1
        return result

    monkeypatch.setattr(embeddings, "_load_model", counting)
    saved_instance = embeddings._model_instance
    saved_path = embeddings._loaded_model_path
    embeddings._model_instance = None
    try:
        gen = EmbeddingGenerator(gate_components["settings"])
        for _ in range(3):
            gen.reset_model()
            gen.begin_warmup()
            assert gen.wait_warm(30.0) is True
        assert state["loads"] == 1
    finally:
        embeddings._load_model = original
        embeddings._model_instance = saved_instance
        embeddings._loaded_model_path = saved_path


def test_fast_profile_withheld_from_user_surface(tmp_path: Path) -> None:
    """The fast profile is withheld without a qualifying candidate."""
    from src.cli.main import _check_model_profile
    from src.engine.config import Settings

    assert _check_model_profile(Settings(context_dir=tmp_path, model_profile="default")) is None
    assert _check_model_profile(Settings(context_dir=tmp_path, model_profile="fast")) == 1
    assert _check_model_profile(Settings(context_dir=tmp_path, model_profile="turbo")) == 1
