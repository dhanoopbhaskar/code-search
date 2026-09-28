"""Unit tests for declared-rule extraction and persistence.

Pins the index-time plumbing that feeds the declared-rules search pass: the
parser attaches ``declared_rules`` to annotated/decorated definitions, the
symbol extractor records them on symbols, and the indexer persists the column
into ``code_chunks``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.engine.parser import ASTParser

JAVA_GUARD = """
package com.example;

import org.springframework.security.access.prepost.PreAuthorize;

public class ArticleAuthorization {

    @PreAuthorize("hasRole('ADMIN') or isArticleOwner(#article)")
    public boolean canDeleteArticle(String article) {
        return true;
    }

    public boolean canEditArticle(String article) {
        return true;
    }
}
"""

PYTHON_DECORATED = """
from functools import wraps

def admin_only(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)
    return wrapper

class ArticleService:
    @admin_only
    def delete(self, article_id):
        return True

    def edit(self, article_id):
        return True
"""


@pytest.fixture
def parser() -> ASTParser:
    return ASTParser()


def test_java_annotation_rules_captured_on_method(parser: ASTParser, tmp_path: Path) -> None:
    path = tmp_path / "ArticleAuthorization.java"
    path.write_text(JAVA_GUARD)
    chunks = parser.get_chunks_for_file(path, path.read_bytes())
    guarded = [
        c
        for c in chunks
        if c["chunk_node_type"] == "method_declaration" and "canDeleteArticle" in c["content"]
    ]
    assert len(guarded) == 1
    assert "PreAuthorize" in guarded[0]["declared_rules"]
    assert "hasRole" in guarded[0]["declared_rules"]

    unguarded = [
        c
        for c in chunks
        if c["chunk_node_type"] == "method_declaration" and "canEditArticle" in c["content"]
    ]
    assert len(unguarded) == 1
    assert not unguarded[0].get("declared_rules")


def test_java_symbol_carries_declared_rules(parser: ASTParser, tmp_path: Path) -> None:
    from src.engine.symbols import SymbolExtractor

    path = tmp_path / "ArticleAuthorization.java"
    path.write_text(JAVA_GUARD)
    symbols = SymbolExtractor(parser).extract_symbols(path, path.read_bytes())
    guarded = [s for s in symbols if s["name"] == "canDeleteArticle"]
    assert len(guarded) == 1
    assert "PreAuthorize" in guarded[0]["declared_rules"]
    assert "isArticleOwner" in guarded[0]["declared_rules"]


def test_python_decorator_rules_captured(parser: ASTParser, tmp_path: Path) -> None:
    path = tmp_path / "service.py"
    path.write_text(PYTHON_DECORATED)
    chunks = parser.get_chunks_for_file(path, path.read_bytes())
    delete = [c for c in chunks if c["content"].startswith("def delete")]
    assert len(delete) == 1
    assert "admin_only" in delete[0]["declared_rules"]
    edit = [c for c in chunks if c["content"].startswith("def edit")]
    assert len(edit) == 1
    assert not edit[0].get("declared_rules")


def test_declared_rules_persisted_by_indexer(indexed_robustness: dict[str, Any]) -> None:
    db = indexed_robustness["db"]
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT file_path, declared_rules FROM code_chunks "
            "WHERE declared_rules IS NOT NULL AND declared_rules != '';"
        ).fetchall()
    assert rows
    guarded_files = {Path(r["file_path"]).name for r in rows}
    assert "ArticleAuthorization.java" in guarded_files
    assert "CommentController.java" in guarded_files
