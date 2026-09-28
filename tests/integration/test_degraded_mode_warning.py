"""Integration tests for degraded search modes: they must be loud and
documented.

``--no-model`` prints a prominent stderr warning and the ranked envelope
reports ``vector_health: false``, ``model_status: disabled``, and a visible
``degraded_reason`` (``model_disabled``/``model_unavailable``) — never a
silent false.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.engine.search import HybridSearch


class TestDegradedModeEnvelope:
    def test_no_model_envelope_reports_disabled(self, indexed_relevance: dict[str, Any]) -> None:
        """A ``--no-model`` search reports ``vector_health: false``,
        ``model_status: disabled``, and ``degraded_reason:
        model_disabled``."""
        comps = indexed_relevance
        search = HybridSearch(
            comps["db"],
            comps["vector_index"],
            comps["embedding_gen"],
            comps["settings"],
            no_model=True,
        )
        envelope = search.search("how do comments get created", limit=5)
        assert envelope["mode"] == "ranked"
        assert envelope["vector_health"] is False
        assert envelope["model_status"] == "disabled", envelope.get("model_status")
        assert envelope["degraded_reason"] == "model_disabled", envelope.get("degraded_reason")
        for r in envelope["results"]:
            assert r["vector_degraded"] is True

    def test_unavailable_model_reports_model_unavailable(
        self, indexed_relevance: dict[str, Any]
    ) -> None:
        """When the vector layer is genuinely unusable (empty index metadata),
        the envelope reports ``degraded_reason: model_unavailable``."""
        comps = indexed_relevance
        # Build a search over the same index but an empty vector store so the
        # vector layer is unusable even with the model loaded.
        from pathlib import Path

        from src.engine.embeddings import VectorIndex

        empty = Path(comps["context_dir"]) / "empty_vectors.bin"
        meta = Path(comps["context_dir"]) / "empty_vectors.meta.json"
        empty.unlink(missing_ok=True)
        meta.unlink(missing_ok=True)
        vi = VectorIndex(empty, meta)
        vi.load()
        search = HybridSearch(comps["db"], vi, comps["embedding_gen"], comps["settings"])
        envelope = search.search("how do comments get created", limit=5)
        assert envelope["model_status"] == "disabled", envelope.get("model_status")
        assert envelope["degraded_reason"] == "model_unavailable", envelope.get("degraded_reason")


class TestDegradedModeWarning:
    def test_no_model_warning_is_prominent(
        self, indexed_relevance: dict[str, Any], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The ``--no-model`` fast path emits a prominent stderr warning that
        semantic/vector signals are disabled."""
        from src.cli.main import cmd_search

        args = type(
            "Args",
            (),
            {
                "no_model": True,
                "query": "how do comments get created",
                "limit": 5,
                "language": None,
                "include_tests": True,
                "mode": "ranked",
                "content": "code_focused",
                "matching": "all_tokens",
                "json": True,
                "verbose": False,
                "context_dir": str(indexed_relevance["context_dir"]),
            },
        )()
        cmd_search(args)
        captured = capsys.readouterr()
        assert "no-model" in captured.err.lower(), "stderr must carry the --no-model warning"
        assert "lexical" in captured.err.lower(), "the warning must state the lexical-only mode"
