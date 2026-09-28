"""Integration tests for auto-scope detection.

Runs against the ``indexed_transparency`` fixture (a ``docs/`` prose tree, an
``application-dev.properties`` config chunk, and Spring code). Verifies the
docs-intent inference policy (empty default pass switches to ``all``, a
non-empty pass is returned unchanged with a suggestion), config-intent message
accuracy, explicit-scope precedence, the disable toggle, and the documented
edge cases.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from src.engine.search import HybridSearch

DOCS_QUERY = "how to deploy"
DOCS_QUERY_NO_PROSE = "readme documentation"
MIXED_QUERY = "article documentation"
EMPTY_INFERRED_QUERY = "definitely-no-match-xyzzy documentation"

DOCS_INTENT_SET = ["readme documentation", "how to deploy", "operations guide"]
NEUTRAL_QUERY_SET = ["user login handler", "parse config file"]


def _names(results: list[dict[str, Any]]) -> set[str]:
    return {Path(r["file_path"]).name for r in results}


def _docs_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in results if r.get("content_type") == "docs"]


def _disabled_search(comps: dict[str, Any]) -> HybridSearch:
    settings = dataclasses.replace(comps["settings"], intent_scope_enabled=False)
    return HybridSearch(comps["db"], comps["vector_index"], comps["embedding_gen"], settings)


class TestDocsIntentReachability:
    def test_empty_default_pass_switches_to_all_and_returns_prose(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """An empty default pass re-runs under ``all``
        and returns a prose chunk from ``docs/``."""
        envelope = indexed_transparency["search"].search(DOCS_QUERY, limit=10)
        assert envelope["content"] == "all"
        assert envelope["scope"]["origin"] == "inferred"
        assert envelope["scope"]["intent"] == "docs"
        assert envelope["scope"]["signal"] is not None
        assert _docs_results(envelope["results"]), "the inferred all pass returned no prose"

    def test_inferred_all_scope_keeps_code_reachable(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """The docs-inferred ``all`` scope does not drop code content."""
        envelope = indexed_transparency["search"].search(DOCS_QUERY, limit=10)
        assert envelope["content"] == "all"
        assert any(r.get("content_type") == "code" for r in envelope["results"])

    def test_non_empty_default_pass_returned_unchanged_with_suggestion(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """A non-empty default pass is returned unchanged with
        a strong suggestion; the scope is not switched."""
        search = indexed_transparency["search"]
        explicit_default = search.search(MIXED_QUERY, limit=10, content="code_focused")
        envelope = search.search(MIXED_QUERY, limit=10)
        assert envelope["content"] == "code_focused"
        assert envelope["scope"]["origin"] == "default"
        assert envelope["scope"]["suggested"] == "all"
        assert envelope["scope"]["signal"] is not None
        assert _names(envelope["results"]) == _names(explicit_default["results"])

    def test_mixed_code_and_docs_tokens_do_not_hide_code(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """Edge case: an ambiguous code + docs query keeps the code hits."""
        envelope = indexed_transparency["search"].search(MIXED_QUERY, limit=10)
        assert any(r.get("content_type") == "code" for r in envelope["results"])

    def test_inferred_scope_with_no_content_reports_honest_empty(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """An inferred scope with no matching content reports it."""
        envelope = indexed_transparency["search"].search(EMPTY_INFERRED_QUERY, limit=10)
        assert envelope["content"] == "all"
        assert envelope["scope"]["origin"] == "inferred"
        assert not envelope["results"]
        assert "no matching" in (envelope["scope"]["signal"] or "").lower()

    def test_docs_intent_set_returns_prose_or_direction(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """Each documented docs-intent case returns prose or a direction."""
        for query in DOCS_INTENT_SET:
            envelope = indexed_transparency["search"].search(query, limit=10)
            has_prose = bool(_docs_results(envelope["results"]))
            has_direction = bool(envelope["scope"].get("signal"))
            assert has_prose or has_direction, query


class TestNeutralQueries:
    def test_neutral_set_acquires_no_hint(self, indexed_transparency: dict[str, Any]) -> None:
        """Neutral queries keep the default scope and no signal."""
        for query in NEUTRAL_QUERY_SET:
            envelope = indexed_transparency["search"].search(query, limit=10)
            assert envelope["scope"]["origin"] == "default", query
            assert envelope["scope"]["signal"] is None, query

    def test_unusual_phrasing_is_neutral_and_silent(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """Edge case: a false negative (unusual phrasing) is never worse."""
        envelope = indexed_transparency["search"].search("sum two numbers", limit=10)
        assert envelope["content"] == "code_focused"
        assert envelope["scope"]["intent"] == "neutral"
        assert envelope["scope"]["signal"] is None


class TestNonRankedModes:
    def test_exhaustive_docs_intent_does_not_switch_or_suggest(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """Exhaustive keeps the effective scope and suggests nothing."""
        envelope = indexed_transparency["search"].search(
            DOCS_QUERY_NO_PROSE, limit=10, mode="exhaustive"
        )
        assert envelope["mode"] == "exhaustive"
        assert envelope["content"] == "code_focused"
        assert envelope["scope"]["origin"] == "default"
        assert envelope["scope"]["suggested"] is None

    def test_enumerate_docs_intent_does_not_switch_or_suggest(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """Enumerate keeps the effective scope and suggests nothing."""
        envelope = indexed_transparency["search"].search(
            "readme list all classes", limit=10, mode="enumerate"
        )
        assert envelope["mode"] == "enumerate"
        assert envelope["content"] == "code_focused"
        assert envelope["scope"]["origin"] == "default"
        assert envelope["scope"]["suggested"] is None


class TestConfigIntentAccuracy:
    def test_default_scope_keeps_config_reachable_without_signal(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """The default scope includes configuration and emits no
        contradictory exclusion message."""
        envelope = indexed_transparency["search"].search("database configuration", limit=10)
        assert envelope["content"] == "code_focused"
        assert envelope["scope"]["origin"] == "default"
        assert envelope["scope"]["signal"] is None
        assert any(r.get("content_type") == "config" for r in envelope["results"])

    def test_code_scope_gives_accurate_config_direction(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """A genuinely excluding scope names the override."""
        envelope = indexed_transparency["search"].search(
            "database configuration", limit=10, content="code"
        )
        assert envelope["content"] == "code"
        assert envelope["scope"]["origin"] == "explicit"
        assert envelope["scope"]["override"] == "config"
        signal = envelope["scope"]["signal"]
        assert signal is not None
        assert "content scope config" in signal

    def test_config_named_token_does_not_change_scope(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """Edge case: a config word under the default scope never switches."""
        envelope = indexed_transparency["search"].search("config", limit=10)
        assert envelope["content"] == "code_focused"
        assert envelope["scope"]["origin"] == "default"
        assert envelope["scope"]["signal"] is None


class TestExplicitPrecedenceAndToggle:
    def test_explicit_scope_wins_over_inference(self, indexed_transparency: dict[str, Any]) -> None:
        """An explicit scope is honoured and disables inference."""
        envelope = indexed_transparency["search"].search(
            DOCS_QUERY_NO_PROSE, limit=10, content="code_focused"
        )
        assert envelope["content"] == "code_focused"
        assert envelope["scope"]["origin"] == "explicit"
        assert envelope["scope"]["suggested"] is None

    def test_explicit_scope_on_exhaustive_still_scopes(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """The explicit scope is applied in non-ranked modes too."""
        envelope = indexed_transparency["search"].search(
            "config", limit=10, content="code", mode="exhaustive"
        )
        assert envelope["content"] == "code"
        assert envelope["scope"]["origin"] == "explicit"

    def test_disable_toggle_restores_default_behaviour(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """With inference disabled the engine behaves as before."""
        search = _disabled_search(indexed_transparency)
        for query in (DOCS_QUERY, DOCS_QUERY_NO_PROSE):
            envelope = search.search(query, limit=10)
            assert envelope["content"] == "code_focused", query
            assert envelope["scope"]["origin"] == "default", query
            assert envelope["scope"]["signal"] is None, query
            assert envelope["scope"]["suggested"] is None, query

    def test_disabled_result_set_matches_default_pass(
        self, indexed_transparency: dict[str, Any]
    ) -> None:
        """The disabled result set equals the default-scope pass."""
        search = _disabled_search(indexed_transparency)
        disabled = search.search(DOCS_QUERY, limit=10)
        explicit_default = indexed_transparency["search"].search(
            DOCS_QUERY, limit=10, content="code_focused"
        )
        assert _names(disabled["results"]) == _names(explicit_default["results"])
