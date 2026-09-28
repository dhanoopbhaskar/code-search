"""Unit tests for the concurrency-safe background model warmup lifecycle.

Verifies that concurrent first callers trigger exactly one load, that repeat
calls are idempotent, that ``is_warm``/``warm_state`` never block, and that the
``failed``/``disabled`` terminal states return promptly instead of hanging.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.engine import embeddings
from src.engine.config import Settings
from src.engine.embeddings import EmbeddingGenerator, WarmupState


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(context_dir=tmp_path)


@pytest.fixture
def restore_module_singleton() -> Iterator[None]:
    saved_instance = embeddings._model_instance
    saved_path = embeddings._loaded_model_path
    try:
        embeddings._model_instance = None
        embeddings._loaded_model_path = None
        yield
    finally:
        embeddings._model_instance = saved_instance
        embeddings._loaded_model_path = saved_path


def _counting_loader(delay: float, result: object | None) -> tuple[object, dict[str, int]]:
    calls = {"n": 0}

    def loader(_settings: Settings | None = None) -> object | None:
        calls["n"] += 1
        time.sleep(delay)
        return result

    return loader, calls


def test_concurrent_begin_warmup_triggers_exactly_one_load(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, restore_module_singleton: None
) -> None:
    loader, calls = _counting_loader(0.05, object())
    monkeypatch.setattr(embeddings, "_load_model", loader)

    gen = EmbeddingGenerator(settings)
    threads = [threading.Thread(target=gen.begin_warmup) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert gen.wait_warm(2.0) is True
    assert calls["n"] == 1
    assert gen.is_warm() is True
    assert gen.warm_state() is WarmupState.WARM


def test_begin_warmup_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, restore_module_singleton: None
) -> None:
    loader, calls = _counting_loader(0.01, object())
    monkeypatch.setattr(embeddings, "_load_model", loader)

    gen = EmbeddingGenerator(settings)
    gen.begin_warmup()
    gen.begin_warmup()
    assert gen.wait_warm(2.0) is True
    gen.begin_warmup()
    assert calls["n"] == 1


def test_is_warm_and_warm_state_never_block(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, restore_module_singleton: None
) -> None:
    loader, _ = _counting_loader(0.3, object())
    monkeypatch.setattr(embeddings, "_load_model", loader)

    gen = EmbeddingGenerator(settings)
    gen.begin_warmup()

    start = time.monotonic()
    assert gen.is_warm() is False
    assert gen.warm_state() is WarmupState.WARMING
    elapsed = time.monotonic() - start
    assert elapsed < 0.1, f"is_warm/warm_state blocked for {elapsed:.3f}s"

    assert gen.wait_warm(2.0) is True


def test_failed_state_is_terminal_and_never_hangs(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, restore_module_singleton: None
) -> None:
    loader, calls = _counting_loader(0.01, None)
    monkeypatch.setattr(embeddings, "_load_model", loader)

    gen = EmbeddingGenerator(settings)
    gen.begin_warmup()
    assert gen.wait_warm(2.0) is False
    assert gen.warm_state() is WarmupState.FAILED

    start = time.monotonic()
    assert gen.wait_warm(2.0) is False
    assert time.monotonic() - start < 0.5
    gen.begin_warmup()
    assert calls["n"] == 1


def test_disabled_state_is_terminal(settings: Settings) -> None:
    gen = EmbeddingGenerator(settings, disabled=True)
    assert gen.warm_state() is WarmupState.DISABLED
    gen.begin_warmup()
    start = time.monotonic()
    assert gen.wait_warm(0.5) is False
    assert time.monotonic() - start < 0.2
    assert gen.is_warm() is False


def test_wait_warm_is_bounded(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, restore_module_singleton: None
) -> None:
    loader, _ = _counting_loader(5.0, object())
    monkeypatch.setattr(embeddings, "_load_model", loader)

    gen = EmbeddingGenerator(settings)
    gen.begin_warmup()
    start = time.monotonic()
    assert gen.wait_warm(0.05) is False
    assert time.monotonic() - start < 0.5


def test_reset_model_returns_to_cold_and_rewarms(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, restore_module_singleton: None
) -> None:
    loader, calls = _counting_loader(0.01, object())
    monkeypatch.setattr(embeddings, "_load_model", loader)

    gen = EmbeddingGenerator(settings)
    gen.begin_warmup()
    assert gen.wait_warm(2.0) is True

    gen.reset_model()
    assert gen.warm_state() is WarmupState.COLD
    assert gen.is_warm() is False

    gen.begin_warmup()
    assert gen.wait_warm(2.0) is True
    assert calls["n"] == 2


def test_external_warmup_suppresses_in_process_load(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, restore_module_singleton: None
) -> None:
    loader, calls = _counting_loader(0.01, object())
    monkeypatch.setattr(embeddings, "_load_model", loader)

    gen = EmbeddingGenerator(settings)
    gen.warmup_external = True
    gen.begin_warmup()
    assert gen.is_warm() is False
    assert calls["n"] == 0
