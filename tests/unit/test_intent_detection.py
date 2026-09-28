"""Unit tests for the lexical query content-intent classifier.

Covers documentation/configuration/neutral classification, the fixed
docs → config → neutral precedence, determinism for a repeated query string,
and the scope-signal accuracy invariant that a message is never produced when
the effective scope already includes the intent's content type.
"""

from __future__ import annotations

from src.engine.intent_detection import (
    ContentIntent,
    build_scope_signal,
    classify_content_intent,
    scope_override,
)

DOCS_QUERIES = ["readme documentation", "how to deploy", "operations guide", "tutorial"]
CONFIG_QUERIES = ["database configuration", "connection pool settings", "yaml property timeout"]
NEUTRAL_QUERIES = ["user login handler", "sum two numbers", "ArticleService.save"]


class TestClassifyDocsIntent:
    def test_documentation_shaped_queries_classify_docs(self) -> None:
        for query in DOCS_QUERIES:
            assert classify_content_intent(query) is ContentIntent.DOCS, query

    def test_deterministic_across_repeated_calls(self) -> None:
        query = "readme documentation"
        outcomes = {classify_content_intent(query) for _ in range(5)}
        assert outcomes == {ContentIntent.DOCS}


class TestClassifyConfigIntent:
    def test_configuration_shaped_queries_classify_config(self) -> None:
        for query in CONFIG_QUERIES:
            assert classify_content_intent(query) is ContentIntent.CONFIG, query

    def test_config_vocabulary_comes_from_shared_scent_detector(self) -> None:
        from src.engine.scent_detection import detect_config_ddl_scent

        query = "connection pool settings"
        assert detect_config_ddl_scent(query)["has_scent"] is True
        assert classify_content_intent(query) is ContentIntent.CONFIG


class TestPrecedence:
    def test_docs_wins_over_config(self) -> None:
        # Both docs ("guide") and config ("database") vocabulary are present.
        assert classify_content_intent("database guide") is ContentIntent.DOCS

    def test_neutral_when_no_signal(self) -> None:
        for query in NEUTRAL_QUERIES:
            assert classify_content_intent(query) is ContentIntent.NEUTRAL, query

    def test_symbol_named_like_docs_word_stays_neutral(self) -> None:
        # A symbol that merely contains a docs word must not trigger docs intent.
        assert classify_content_intent("guide_factory") is ContentIntent.NEUTRAL


class TestScopeSignalAccuracy:
    def test_no_signal_when_effective_scope_includes_docs(self) -> None:
        assert build_scope_signal(ContentIntent.DOCS, "docs", "explicit", None) is None
        assert build_scope_signal(ContentIntent.DOCS, "all", "explicit", None) is None

    def test_no_signal_when_effective_scope_includes_config(self) -> None:
        for effective in ("code_focused", "config", "all"):
            assert build_scope_signal(ContentIntent.CONFIG, effective, "default", None) is None, (
                effective
            )

    def test_config_signal_when_genuinely_excluded(self) -> None:
        signal = build_scope_signal(ContentIntent.CONFIG, "code", "explicit", None)
        assert signal is not None
        assert "config" in signal.lower()
        assert "content scope config" in signal

    def test_docs_signal_when_genuinely_excluded(self) -> None:
        signal = build_scope_signal(ContentIntent.DOCS, "code_focused", "explicit", None)
        assert signal is not None
        assert "content scope all" in signal

    def test_docs_suggestion_names_suggested_scope(self) -> None:
        signal = build_scope_signal(ContentIntent.DOCS, "code_focused", "default", "all")
        assert signal is not None
        assert "content scope all" in signal

    def test_docs_inferred_signal_names_origin(self) -> None:
        signal = build_scope_signal(ContentIntent.DOCS, "all", "inferred", None)
        assert signal is not None
        assert "inferred" in signal

    def test_neutral_never_signals(self) -> None:
        assert build_scope_signal(ContentIntent.NEUTRAL, "code", "default", None) is None

    def test_signal_is_surface_neutral(self) -> None:
        """The message names a neutral scope, never a CLI flag."""
        for intent in (ContentIntent.DOCS, ContentIntent.CONFIG):
            signal = build_scope_signal(intent, "code", "explicit", None)
            assert signal is not None
            assert "--content" not in signal
            assert 'content="' not in signal


class TestScopeOverride:
    def test_override_by_intent(self) -> None:
        assert scope_override(ContentIntent.DOCS, "code_focused") == "all"
        assert scope_override(ContentIntent.CONFIG, "code") == "config"

    def test_neutral_override_is_effective_scope(self) -> None:
        assert scope_override(ContentIntent.NEUTRAL, "code_focused") == "code_focused"
