"""Unit tests for query analysis + language inference.

Written FIRST against the query analysis contract. Coverage is
computed over exact corpus-token matches only (never prefix), always AFTER
expansion; language precedence is explicit > symbol-resolved > single-language
vocab > None; definition-intent phrases resolve via ``SymbolStore.resolve_name``.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def builtin_table() -> Any:
    from src.engine.expansions import ExpansionTable

    return ExpansionTable(config_path="")


def _analyze(
    query: str,
    vocabulary: set[str],
    builtin_table: Any,
    symbol_store: Any = None,
    vocab_by_language: dict[str, set[str]] | None = None,
) -> Any:
    from src.engine.config import Settings
    from src.engine.language import analyze_query

    return analyze_query(
        query,
        settings=Settings(context_dir="/tmp/unused"),
        vocabulary=vocabulary,
        expansion_table=builtin_table,
        symbol_store=symbol_store,
        vocab_by_language=vocab_by_language,
    )


class TestCoverage:
    def test_e1_exact_coverage_is_025(self, builtin_table: Any) -> None:
        """E1 ``websocket real time notifications`` -> coverage 0.25: only
        ``time`` is an exact corpus token; no prefix expansion counts."""
        analysis = _analyze(
            "websocket real time notifications",
            vocabulary={"time"},
            builtin_table=builtin_table,
        )
        assert analysis.coverage == pytest.approx(0.25)
        assert analysis.exact_tokens == ["time"]

    def test_e1_high_vocabulary_raises_coverage(self, builtin_table: Any) -> None:
        """E1 coverage rises with vocabulary; exact-only, never prefix."""
        analysis = _analyze(
            "websocket real time notifications",
            vocabulary={"websocket", "real", "time", "notifications"},
            builtin_table=builtin_table,
        )
        assert analysis.coverage == pytest.approx(1.0)

    def test_s3_in_domain_coverage_is_10(self, builtin_table: Any) -> None:
        """S3 ``check if the article title or slug is already taken before
        saving`` -> coverage 1.0 when all concept sub-words are exact tokens."""
        vocabulary = {"check", "article", "title", "slug", "already", "taken", "saving"}
        analysis = _analyze(
            "check if the article title or slug is already taken before saving",
            vocabulary=vocabulary,
            builtin_table=builtin_table,
        )
        assert analysis.coverage == pytest.approx(1.0)

    def test_s6_pre_expansion_coverage_zero(self) -> None:
        """S6 without expansion -> coverage 0.0 (the internal intermediate)."""
        from src.engine.config import Settings
        from src.engine.language import analyze_query

        analysis = analyze_query(
            "configure cross origin requests from a browser",
            settings=Settings(context_dir="/tmp/unused"),
            vocabulary={"cors"},
            expansion_table=None,
        )
        assert analysis.coverage == pytest.approx(0.0)
        assert analysis.expanded_text == "configure cross origin requests from a browser"

    def test_s6_post_expansion_coverage_clears_floor(self, builtin_table: Any) -> None:
        """After ``cross origin`` -> ``cors`` expansion the coverage clears the
        default ``exact_token_coverage_min`` (0.5) floor."""
        vocabulary = {"cors", "origin", "configure"}
        analysis = _analyze(
            "configure cross origin requests from a browser",
            vocabulary=vocabulary,
            builtin_table=builtin_table,
        )
        assert analysis.expanded_text != "configure cross origin requests from a browser"
        assert analysis.coverage >= 0.5


class TestInferLanguage:
    def test_explicit_language_never_overridden(self, builtin_table: Any) -> None:
        """An explicit ``language`` argument beats inference."""
        from src.engine.config import Settings
        from src.engine.language import analyze_query

        analysis = analyze_query(
            "TokenService",
            settings=Settings(context_dir="/tmp/unused"),
            vocabulary={"token", "service"},
            expansion_table=builtin_table,
            explicit_language="java",
        )
        assert analysis.inferred_language == "java"

    def test_single_language_vocab_java(self, builtin_table: Any) -> None:
        """S4-style: all exact tokens come from one language's vocabulary -> java."""
        vocab_by_language = {
            "java": {"feed", "user", "article", "follow"},
            "sql": {"insert", "create", "table"},
            "yaml": {"services", "image", "ports"},
        }
        analysis = _analyze(
            "get the feed of articles from authors the current user follows",
            vocabulary={"feed", "user", "article", "follow"},
            builtin_table=builtin_table,
            vocab_by_language=vocab_by_language,
        )
        assert analysis.inferred_language == "java"

    def test_mixed_language_vocab_returns_none(self, builtin_table: Any) -> None:
        """Tokens drawn from multiple languages -> None (unscoped)."""
        vocab_by_language = {
            "java": {"feed", "user"},
            "sql": {"table"},
        }
        analysis = _analyze(
            "feed table user",
            vocabulary={"feed", "user", "table"},
            builtin_table=builtin_table,
            vocab_by_language=vocab_by_language,
        )
        assert analysis.inferred_language is None

    def test_general_query_returns_none(self, builtin_table: Any) -> None:
        """A general/no-match query stays unscoped (None)."""
        analysis = _analyze(
            "weird wuzzle frobnicator",
            vocabulary=set(),
            builtin_table=builtin_table,
        )
        assert analysis.inferred_language is None


class TestSymbolAndDefinition:
    def test_symbol_resolved_language(self, indexed_trust_defects: dict[str, Any]) -> None:
        """A symbol-like query that resolves via SymbolStore infers its language."""
        symbol_store = indexed_trust_defects["symbol_store"]
        from src.engine.config import Settings
        from src.engine.expansions import ExpansionTable
        from src.engine.language import analyze_query, language_vocabularies

        analysis = analyze_query(
            "TokenService",
            settings=Settings(context_dir=indexed_trust_defects["context_dir"]),
            vocabulary=set(),
            expansion_table=ExpansionTable(config_path=""),
            symbol_store=symbol_store,
            vocab_by_language=language_vocabularies(indexed_trust_defects["db"]),
        )
        assert analysis.inferred_language == "java"

    def test_definition_intent_detected(self, builtin_table: Any) -> None:
        analysis = _analyze(
            "definition of ArticleService.getBySlug",
            vocabulary=set(),
            builtin_table=builtin_table,
        )
        assert analysis.definition_intent is True

    def test_definition_target_resolves(self, indexed_trust_defects: dict[str, Any]) -> None:
        symbol_store = indexed_trust_defects["symbol_store"]
        from src.engine.config import Settings
        from src.engine.expansions import ExpansionTable
        from src.engine.language import analyze_query

        analysis = analyze_query(
            "definition of ArticleService.getBySlug",
            settings=Settings(context_dir=indexed_trust_defects["context_dir"]),
            vocabulary=set(),
            expansion_table=ExpansionTable(config_path=""),
            symbol_store=symbol_store,
        )
        assert analysis.definition_target is not None
        assert "getBySlug" in analysis.definition_target

    def test_definition_phrases(self, builtin_table: Any) -> None:
        for phrase in ("definition of Foo", "where is Foo defined", "define Foo", "what is Foo"):
            analysis = _analyze(phrase, vocabulary=set(), builtin_table=builtin_table)
            assert analysis.definition_intent is True, phrase
