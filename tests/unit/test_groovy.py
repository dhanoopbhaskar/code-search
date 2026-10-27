"""Tests for Groovy indexing without the optional tree-sitter grammar."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from code_search.engine.parser import ASTParser
from code_search.engine.symbols import SymbolExtractor


def test_groovy_is_a_supported_language() -> None:
    """``.groovy``/``.gvy`` resolve to the groovy language token."""
    parser = ASTParser()
    assert parser.detect_language(Path("CommitTaxRollbackHandlerSpec.groovy")) == "groovy"
    assert parser.detect_language(Path("build.gvy")) == "groovy"


def test_groovy_regex_fallback_extracts_types_and_methods(tmp_path: Path) -> None:
    """A Groovy source yields class and feature-method symbols."""
    source = (
        "package com.example.checkout\n"
        "\n"
        "class CommitTaxRollbackHandlerSpec extends Specification {\n"
        '  def "rolls back tax on payment failure"() {\n'
        "    given: 'an order'\n"
        "  }\n"
        "  void helper() {\n"
        "  }\n"
        "}\n"
    )
    path = tmp_path / "CommitTaxRollbackHandlerSpec.groovy"
    symbols = SymbolExtractor(ASTParser()).extract_symbols(path, source.encode())

    names = {symbol["name"] for symbol in symbols}
    assert "CommitTaxRollbackHandlerSpec" in names
    assert "rolls back tax on payment failure" in names
    assert "helper" in names
    spec = next(symbol for symbol in symbols if symbol["name"] == "CommitTaxRollbackHandlerSpec")
    assert spec["conventional_fqn"] == "com.example.checkout.CommitTaxRollbackHandlerSpec"
    assert spec["language"] == "groovy"
    assert spec["kind"] == "class"
    assert spec["line_start"] == 3
    assert all(symbol["file_path"] == str(path) for symbol in symbols)


def test_groovy_regex_fallback_used_when_grammar_reports_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A present-but-incomplete Groovy tree falls back to the regex extractor."""

    class _Root:
        type = "program"
        children: tuple[Any, ...] = ()
        has_error = True

    class _ErrorTree:
        root_node = _Root()

    parser = ASTParser()

    def fake_parse(*_args: Any, **_kwargs: Any) -> Any:
        return _ErrorTree()

    monkeypatch.setattr(parser, "parse_file", fake_parse)
    source = b'class HandlerSpec {\n  def "handles"() { }\n}\n'
    symbols = SymbolExtractor(parser).extract_symbols(tmp_path / "HandlerSpec.groovy", source)

    names = {symbol["name"] for symbol in symbols}
    assert "HandlerSpec" in names
    assert "handles" in names


def test_groovy_fallback_is_not_used_for_other_missing_grammars(tmp_path: Path) -> None:
    """A non-Groovy file with no grammar still yields no fabricated symbols."""
    path = tmp_path / "unknown.zzz"
    symbols = SymbolExtractor(ASTParser()).extract_symbols(path, b"class Thing {}")
    assert symbols == []


def test_groovy_symbols_can_be_indexed(tmp_path: Path) -> None:
    """The indexer discovers and stores Groovy declarations."""
    from tests.conftest import _indexed_components

    repo = tmp_path / "groovy_repo"
    repo.mkdir()
    (repo / "HandlerSpec.groovy").write_text(
        'package demo\nclass HandlerSpec {\n  def "handles"() { }\n}\n',
        encoding="utf-8",
    )
    comps: dict[str, Any] = _indexed_components(repo, repo / ".context")
    envelope = comps["symbol_store"].resolve_name("HandlerSpec", prefer_type=True)
    assert envelope["kind"] == "exact"
    assert envelope["symbol"]["language"] == "groovy"
