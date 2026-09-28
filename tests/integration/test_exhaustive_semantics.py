"""Exhaustive-mode literal semantics.

The exhaustive over-counting defect is OR-token line matching: a line matches
when *any* query token is a substring, so counts inflate an order of magnitude
over the ground-truth grep oracle (9 and 146 vs 1 and 5). This suite pins the
fix: default exhaustive matching is all-query-tokens-per-line (AND), quoted
phrases keep true literal-substring matching, regex metacharacters are treated
as literal text, and every result set carries a ``matching_semantics`` label so
an ``any_token`` set is never presented as an exact literal count.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from src.engine.config import Settings
from src.engine.paths import normalize_indexed_path
from src.engine.search import HybridSearch


def _rg_member_set(files: list[Path], term: str) -> set[tuple[str, int]]:
    """Ground-truth literal oracle: (resolved_path, line_number) pairs.

    ``rg -F -n`` treats *term* as a fixed string (regex metacharacters are
    literal) and reports one ``path:line`` per matching line — the same count
    contract the exhaustive envelope promises.
    """
    proc = subprocess.run(
        ["rg", "-F", "-n", "--", term, *[str(p) for p in files]],
        capture_output=True,
        text=True,
    )
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"rg failed for {term!r}: {proc.stderr}")
    hits: set[tuple[str, int]] = set()
    for line in proc.stdout.splitlines():
        path, lineno, _rest = line.split(":", 2)
        hits.add((str(Path(path).resolve()), int(lineno)))
    return hits


def _indexed_files(fixture: dict[str, Any]) -> list[Path]:
    """Resolve the index-tracked file set to disk (the exhaustive scan surface)."""
    with fixture["db"].connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT file_path FROM file_checksums ORDER BY file_path;"
        ).fetchall()
    stored_root = fixture["meta"].get("index_root")
    index_root = Path(stored_root) if stored_root else None
    resolved: list[Path] = []
    for row in rows:
        p = (
            normalize_indexed_path(row["file_path"], index_root)
            if index_root
            else Path(row["file_path"])
        )
        if p is not None and p.is_file():
            resolved.append(p)
    return resolved


def _envelope_member_set(envelope: dict[str, Any], fixture: dict[str, Any]) -> set[tuple[str, int]]:
    """Normalize an exhaustive envelope's results to (resolved_path, line)."""
    stored_root = fixture["meta"].get("index_root")
    index_root = Path(stored_root) if stored_root else None
    hits: set[tuple[str, int]] = set()
    for r in envelope["results"]:
        p = (
            normalize_indexed_path(r["file_path"], index_root)
            if index_root
            else Path(r["file_path"])
        )
        hits.add((str(p.resolve()), int(r["line_number"])))
    return hits


def _any_token_search(fixture: dict[str, Any]) -> HybridSearch:
    """A search bound to the fixture index with any-token matching mode."""
    settings = Settings(context_dir=fixture["context_dir"], exhaustive_matching_mode="any_token")
    return HybridSearch(fixture["db"], fixture["vector_index"], fixture["embedding_gen"], settings)


@pytest.fixture
def any_token_search(indexed_transparency: dict[str, Any]) -> HybridSearch:
    return _any_token_search(indexed_transparency)


def test_exhaustive_literal_counts_match_rg_oracle(indexed_transparency: dict[str, Any]) -> None:
    """Exhaustive count and member set equal the rg oracle per literal.

    Runs with ``content="all"`` so the scan surface equals the full-file
    ``rg`` surface (the default scope is code-focused, which excludes docs).
    """
    files = _indexed_files(indexed_transparency)
    assert files, "fixture index tracked no files"
    search: HybridSearch = indexed_transparency["search"]
    for literal in (
        "spring.datasource.hikari",
        "maximum-pool-size",
        "connection-timeout",
        "repository.save",
        "save(Article",
    ):
        envelope = search.search(f'"{literal}"', limit=200, mode="exhaustive", content="all")
        assert envelope["mode"] == "exhaustive"
        assert envelope["total_count"] == len(_rg_member_set(files, literal)), (
            f"count for {literal!r}: exhaustive {envelope['total_count']} != rg oracle"
        )
        assert _envelope_member_set(envelope, indexed_transparency) == _rg_member_set(
            files, literal
        ), f"member set mismatch for {literal!r}"
        assert envelope["complete"] is True


def test_default_matching_is_all_tokens_and(indexed_transparency: dict[str, Any]) -> None:
    """Default exhaustive matching requires every query token per line.

    ``content="all"`` so the docs line that contains all three tokens
    (``## Database connection pool settings``) stays in the scan surface.
    """
    search: HybridSearch = indexed_transparency["search"]
    envelope = search.search(
        "connection pool settings", limit=200, mode="exhaustive", content="all"
    )
    assert envelope["mode"] == "exhaustive"
    assert envelope["total_count"] >= 1
    for r in envelope["results"]:
        lowered = r["line_content"].lower()
        for token in ("connection", "pool", "settings"):
            assert token in lowered, (
                f"line {r['file_path']}:{r['line_number']} lacks token {token!r}: "
                f"{r['line_content']!r}"
            )
    assert envelope["matching_semantics"] == "all_tokens"


def test_quoted_phrase_is_literal_substring(indexed_transparency: dict[str, Any]) -> None:
    """A quoted phrase matches as one contiguous substring, not word-wise."""
    search: HybridSearch = indexed_transparency["search"]
    envelope = search.search(
        '"spring.datasource.hikari.maximum-pool-size=10"', limit=50, mode="exhaustive"
    )
    assert envelope["total_count"] == 1
    hit = envelope["results"][0]
    assert "maximum-pool-size=10" in hit["line_content"]
    assert envelope["matching_semantics"] == "literal"


def test_regex_metacharacters_are_literal(indexed_transparency: dict[str, Any]) -> None:
    """Spec edge case: dots/parens in a literal are text, never a pattern."""
    search: HybridSearch = indexed_transparency["search"]
    files = _indexed_files(indexed_transparency)
    for literal in ("spring.datasource.hikari.maximum-pool-size=10", "save(Article"):
        envelope = search.search(f'"{literal}"', limit=50, mode="exhaustive", content="all")
        assert _envelope_member_set(envelope, indexed_transparency) == _rg_member_set(
            files, literal
        ), f"metacharacter literal {literal!r} treated as a pattern"


def test_any_token_set_is_labeled_not_exact(
    indexed_transparency: dict[str, Any], any_token_search: HybridSearch
) -> None:
    """An OR-token result set is labeled and never shown as an exact count."""
    envelope = any_token_search.search("connection pool settings", limit=200, mode="exhaustive")
    assert envelope["mode"] == "exhaustive"
    assert envelope["matching_semantics"] == "any_token"
    assert envelope["total_count"] >= 1
    assert envelope["explanation"] is None or "exact" not in str(envelope["explanation"]).lower()


def test_default_envelope_carries_matching_semantics(indexed_transparency: dict[str, Any]) -> None:
    """Every exhaustive envelope labels its matching contract."""
    search: HybridSearch = indexed_transparency["search"]
    for query in ("spring.datasource", "connection timeout", '"server.port"'):
        envelope = search.search(query, limit=50, mode="exhaustive")
        assert envelope["matching_semantics"] in ("literal", "all_tokens", "any_token"), (
            f"{query!r} missing a matching_semantics label"
        )


def test_ranked_envelope_carries_matching_semantics(indexed_transparency: dict[str, Any]) -> None:
    """The ranked envelope also declares its matching contract."""
    search: HybridSearch = indexed_transparency["search"]
    envelope = search.search("connection pool settings", limit=10, mode="ranked")
    assert envelope["matching_semantics"] in ("literal", "all_tokens", "any_token")


def test_per_request_literal_selection_matches_oracle(
    indexed_transparency: dict[str, Any],
) -> None:
    """``matching=\"literal\"`` selects the verbatim substring mode per request
    and the count matches the ground-truth oracle."""
    files = _indexed_files(indexed_transparency)
    search: HybridSearch = indexed_transparency["search"]
    for literal in ("spring.datasource.hikari", "repository.save"):
        envelope = search.search(
            literal, limit=200, mode="exhaustive", matching="literal", content="all"
        )
        assert envelope["matching_semantics"] == "literal"
        assert envelope["total_count"] == len(_rg_member_set(files, literal)), (
            f"literal count for {literal!r} != rg oracle"
        )


def test_per_request_all_tokens_labeled(indexed_transparency: dict[str, Any]) -> None:
    """An AND-token set requested via ``matching=\"all_tokens\"`` is labeled
    ``all_tokens`` — never presented as an exact phrase count."""
    search: HybridSearch = indexed_transparency["search"]
    envelope = search.search(
        "connection pool settings",
        limit=200,
        mode="exhaustive",
        matching="all_tokens",
        content="all",
    )
    assert envelope["matching_semantics"] == "all_tokens"
    assert envelope["total_count"] >= 1


def test_literal_treats_regex_metacharacters_as_text(
    indexed_transparency: dict[str, Any],
) -> None:
    """Regex metacharacters (``.``, ``(``) are literal text in literal mode."""
    files = _indexed_files(indexed_transparency)
    search: HybridSearch = indexed_transparency["search"]
    envelope = search.search(
        "spring.datasource.hikari.maximum-pool-size=10",
        limit=50,
        mode="exhaustive",
        matching="literal",
        content="all",
    )
    assert _envelope_member_set(envelope, indexed_transparency) == _rg_member_set(
        files, "spring.datasource.hikari.maximum-pool-size=10"
    ), "regex metacharacters treated as a pattern in literal mode"


def test_literal_no_substring_match_returns_zero_cleanly(
    indexed_transparency: dict[str, Any],
) -> None:
    """A literal with no substring match returns 0 while the AND-token mode
    returns its own labeled count."""
    search: HybridSearch = indexed_transparency["search"]
    env_literal = search.search(
        "saveNonExistentMethodName", limit=50, mode="exhaustive", matching="literal"
    )
    assert env_literal["total_count"] == 0
    assert env_literal["matching_semantics"] == "literal"
    env_all = search.search(
        "saveNonExistentMethodName", limit=50, mode="exhaustive", matching="all_tokens"
    )
    assert env_all["matching_semantics"] == "all_tokens"


def test_matching_ignored_outside_exhaustive(indexed_transparency: dict[str, Any]) -> None:
    """``matching`` applies only in exhaustive mode; ranked ignores it."""
    search: HybridSearch = indexed_transparency["search"]
    envelope = search.search(
        "connection pool settings", limit=10, mode="ranked", matching="literal"
    )
    assert envelope["mode"] == "ranked"
    assert envelope["matching_semantics"] == "all_tokens"
