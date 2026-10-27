"""Unit tests for vector-arm gating and reduced cold-path labelling.

A cold query the lexical arm can justify is served immediately from the
labelled lexical-only reduced path. A cold natural-language query that only
the vector leg can admit waits for the bounded warmup budget and then uses the
hybrid path, so it is not dropped into the lexical rescue ladder. Once the
model is warm every query reports ``hybrid``/``warm``.
"""

from __future__ import annotations

import dataclasses
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import FIXTURES_DIR, _indexed_components


@pytest.fixture
def cold_components(tmp_path: Path) -> Iterator[dict[str, Any]]:
    """An indexed repo with a fresh (cold) embedding generator."""
    from code_search.engine.embeddings import (
        EmbeddingGenerator,
        VectorIndex,
        _loaded_model_path,
        _model_instance,
    )
    from code_search.engine.search import HybridSearch

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


def test_cold_lexical_query_stays_on_reduced_path(
    cold_components: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A query the lexical arm justifies is served without waiting for the model."""
    # Pin the model cold: the background load races the request, so measuring
    # the reduced path would otherwise depend on how fast the fixture warms.
    gen = cold_components["gen"]
    monkeypatch.setattr(gen, "is_warm", lambda: False)
    monkeypatch.setattr(gen, "begin_warmup", lambda: None)
    # Every concept in this query is in the fixture vocabulary, so the gate
    # admits it on lexical evidence alone.
    envelope = cold_components["search"].search("how do comments get created", limit=5)
    assert envelope["mode"] == "ranked"
    assert envelope["ranked_path"] == "lexical_reduced"
    assert envelope["warmup_state"] == "warming"
    assert envelope["degraded_reason"] == "warming"
    assert envelope["vector_health"] is True
    assert envelope["model_status"]["state"] == "initializing"
    assert envelope["model_status"]["warmup_state"] == "warming"


def test_cold_nl_query_waits_and_takes_hybrid_path(
    cold_components: dict[str, Any],
) -> None:
    """A long paraphrase waits for warmup instead of falling back to lexical rescue.

    Its exact-token coverage is below the gate floor, so the vector leg is the
    only signal that can admit it; serving it from the reduced path would
    silently return a different, worse result pool.
    """
    search = cold_components["search"]
    # Force the gate to depend on the vector leg regardless of the corpus's
    # measured coverage, and keep the ranked floor out of the way: this test
    # exercises the cold/warm transition, not floor calibration.
    search._settings = dataclasses.replace(
        search._settings,
        exact_token_coverage_min=1.01,
        top_vector_floor=0.3,
        ranked_score_floor=0.0,
        warmup_wait_s=30.0,
    )
    envelope = search.search("save a comment on an article", limit=5)
    assert envelope["mode"] == "ranked"
    assert envelope["ranked_path"] == "hybrid"
    assert envelope["warmup_state"] == "warm"
    assert envelope["degraded_reason"] is None
    assert envelope["results"]


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
    from code_search.engine.search import HybridSearch

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
