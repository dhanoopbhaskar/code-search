"""Unit tests for non-blocking vector-arm gating and reduced cold-path labelling.

A ranked query that races warmup is served immediately from the labelled
lexical-only reduced path; once the model is warm the unchanged hybrid path is
used and the envelope reports ``hybrid``/``warm``.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import FIXTURES_DIR, _indexed_components


@pytest.fixture
def cold_components(tmp_path: Path) -> Iterator[dict[str, Any]]:
    """An indexed repo with a fresh (cold) embedding generator."""
    from src.engine.embeddings import (
        EmbeddingGenerator,
        VectorIndex,
        _loaded_model_path,
        _model_instance,
    )
    from src.engine.search import HybridSearch

    repo = tmp_path / "reduced_repo"
    shutil.copytree(FIXTURES_DIR / "relevance", repo)
    comps = _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})

    saved_instance = _model_instance
    saved_path = _loaded_model_path
    _model_instance = None
    _loaded_model_path = None
    try:
        settings = comps["settings"]
        gen = EmbeddingGenerator(settings)
        index = VectorIndex(
            comps["context_dir"] / "vectors.bin",
            comps["context_dir"] / "vectors.meta.json",
        )
        index.load()
        search = HybridSearch(comps["db"], index, gen, settings)
        yield {"search": search, "gen": gen, "settings": settings, "comps": comps}
    finally:
        _model_instance = saved_instance
        _loaded_model_path = saved_path


def test_cold_query_defers_vector_arm_and_labels_reduced(
    cold_components: dict[str, Any],
) -> None:
    envelope = cold_components["search"].search("how do comments get created", limit=5)
    assert envelope["mode"] == "ranked"
    assert envelope["ranked_path"] == "lexical_reduced"
    assert envelope["warmup_state"] == "warming"
    assert envelope["degraded_reason"] == "warming"
    assert envelope["vector_health"] is True
    assert envelope["model_status"]["state"] == "initializing"
    assert envelope["model_status"]["warmup_state"] == "warming"


def test_warm_query_takes_hybrid_path(cold_components: dict[str, Any]) -> None:
    search = cold_components["search"]
    search.search("how do comments get created", limit=5)
    assert cold_components["gen"].wait_warm(15.0) is True

    envelope = search.search("how do comments get created", limit=5)
    assert envelope["ranked_path"] == "hybrid"
    assert envelope["warmup_state"] == "warm"
    assert envelope["degraded_reason"] is None
    assert envelope["model_status"]["state"] == "warm"


def test_no_model_query_is_lexical_degraded(cold_components: dict[str, Any]) -> None:
    from src.engine.search import HybridSearch

    comps = cold_components["comps"]
    settings = cold_components["settings"]
    no_model_search = HybridSearch(
        comps["db"],
        comps["vector_index"],
        comps["embedding_gen"],
        settings,
        no_model=True,
    )
    envelope = no_model_search.search("how do comments get created", limit=5)
    assert envelope["ranked_path"] == "lexical_degraded"
    assert envelope["warmup_state"] == "disabled"
    assert envelope["degraded_reason"] == "model_disabled"
    assert envelope["model_status"] == "disabled"
