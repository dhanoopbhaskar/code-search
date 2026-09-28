"""Integration tests for the warm/cold status contract after the reduced cold path.

The first ranked request racing warmup is served from the labelled
``lexical_reduced`` path and does not load the model inline; a later request
once warmup completes reports ``hybrid``/``warm`` with no degraded reason.
"""

from __future__ import annotations

import pytest

from tests.conftest import FIXTURES_DIR, _indexed_components


@pytest.fixture
def cold_search(tmp_path):
    """A ``HybridSearch`` whose embedding model is not yet loaded."""
    import shutil

    from src.engine.embeddings import (
        EmbeddingGenerator,
        VectorIndex,
        _loaded_model_path,
        _model_instance,
    )
    from src.engine.search import HybridSearch

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
    def test_first_request_is_reduced_and_not_blocked(self, cold_search) -> None:
        """A first request racing warmup is served reduced and does not block."""
        envelope = cold_search["search"].search("how do comments get created", limit=5)
        assert envelope["mode"] == "ranked"
        assert "query_time_ms" in envelope
        assert envelope["ranked_path"] == "lexical_reduced"
        assert envelope["warmup_state"] == "warming"
        assert envelope["degraded_reason"] == "warming"
        model_status = envelope["model_status"]
        assert isinstance(model_status, dict), "model_status should be a dict per contract"
        assert model_status["state"] == "initializing"
        assert model_status["is_first_request"] is True

    def test_warm_request_reports_warm(self, cold_search) -> None:
        """After warmup completes, a request reports ``hybrid``/``warm``."""
        search = cold_search["search"]
        first = search.search("how do comments get created", limit=5)
        assert first["ranked_path"] == "lexical_reduced"

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

    def test_flag_reflects_measured_state(self, cold_search) -> None:
        """The warm/cold label reflects measured model state, not elapsed time."""
        envelope = cold_search["search"].search("how do comments get created", limit=5)
        assert envelope["ranked_path"] == "lexical_reduced"
        assert envelope["model_status"]["state"] == "initializing"
