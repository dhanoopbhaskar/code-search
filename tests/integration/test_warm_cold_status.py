"""Integration tests for the warm/cold status contract.

A cold natural-language query waits for the bounded warmup budget and reports
``hybrid``/``warm``. A cold query the lexical arm can justify is still served
from the labelled ``lexical_reduced`` path without waiting. A later request
once warmup completes reports ``hybrid``/``warm`` with no degraded reason.
"""

from __future__ import annotations

import dataclasses

import pytest

from tests.conftest import FIXTURES_DIR, _indexed_components


@pytest.fixture
def cold_search(tmp_path):
    """A ``HybridSearch`` whose embedding model is not yet loaded."""
    import shutil

    from code_search.engine.embeddings import (
        EmbeddingGenerator,
        VectorIndex,
        _loaded_model_path,
        _model_instance,
    )
    from code_search.engine.search import HybridSearch

    repo = tmp_path / "cold_repo"
    shutil.copytree(FIXTURES_DIR / "relevance", repo)
    comps = _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})

    # Force a cold model state: the fixture's indexer loaded the module-level
    # singleton during indexing, so reset it and give the search a fresh
    # generator that has not touched the model.
    saved_instance = _model_instance
    saved_path = _loaded_model_path
    _model_instance = None
    _loaded_model_path = None
    try:
        settings = comps["settings"]
        fresh_gen = EmbeddingGenerator(settings)
        fresh_index = VectorIndex(
            comps["context_dir"] / "vectors.bin",
            comps["context_dir"] / "vectors.meta.json",
        )
        fresh_index.load()
        hs = HybridSearch(comps["db"], fresh_index, fresh_gen, settings)
        yield {"search": hs, "gen": fresh_gen, "settings": settings, "comps": comps}
    finally:
        _model_instance = saved_instance
        _loaded_model_path = saved_path


class TestWarmColdStatus:
    def test_first_nl_request_waits_and_reports_hybrid(self, cold_search) -> None:
        """A cold NL query waits for warmup and reports the hybrid path."""
        search = cold_search["search"]
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
        assert "query_time_ms" in envelope
        assert envelope["ranked_path"] == "hybrid"
        assert envelope["warmup_state"] == "warm"
        assert envelope["degraded_reason"] is None
        model_status = envelope["model_status"]
        assert isinstance(model_status, dict), "model_status should be a dict per contract"
        assert model_status["state"] == "warm"

    def test_cold_lexical_request_is_reduced_without_waiting(
        self, cold_search, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A query the lexical arm justifies is served reduced without waiting."""
        gen = cold_search["gen"]
        monkeypatch.setattr(gen, "is_warm", lambda: False)
        monkeypatch.setattr(gen, "begin_warmup", lambda: None)
        envelope = cold_search["search"].search("how do comments get created", limit=5)
        assert envelope["mode"] == "ranked"
        assert envelope["ranked_path"] == "lexical_reduced"
        assert envelope["warmup_state"] == "warming"
        assert envelope["degraded_reason"] == "warming"
        assert envelope["model_status"]["state"] == "initializing"

    def test_warm_request_reports_warm(self, cold_search) -> None:
        """After warmup completes, a request reports ``hybrid``/``warm``."""
        search = cold_search["search"]
        search.search("how do comments get created", limit=5)
        assert cold_search["gen"].wait_warm(15.0) is True

        second = search.search("how do comments get created", limit=5)
        second_status = second["model_status"]
        assert isinstance(second_status, dict)
        assert second["ranked_path"] == "hybrid"
        assert second["warmup_state"] == "warm"
        assert second_status["state"] == "warm", second_status
        assert second_status["is_first_request"] is False
        assert second["degraded_reason"] is None
        assert "query_time_ms" in second
