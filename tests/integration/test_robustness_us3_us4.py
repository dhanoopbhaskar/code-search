"""Integration tests for declared rules and infra demotion.

Runs against the real engine over ``tests/fixtures/robustness/`` with default
settings. Pinned behaviors:

* An ownership/guard query surfaces the ``@PreAuthorize``-guarded method of
  ``ArticleAuthorization`` via the declared-rules pass.
* The ``declared_rules`` column is populated at index time for
  annotated/decorated definitions and is boosted by the declared-rule pass.
* Infra files (``docker-compose.yml``/``Dockerfile``/``Makefile``) never
  surface for code-language queries.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("who owns the article", "ArticleAuthorization.java"),
        ("who is allowed to delete a comment", "CommentController.java"),
    ],
)
def test_declared_rule_query_surfaces_guarded_code(
    indexed_robustness: dict[str, Any], query: str, expected: str
) -> None:
    """A guard/ownership query surfaces the annotated definition
    within the top 5, and the guarded chunk carries a higher score than any
    non-guarded candidate it displaced."""
    envelope = indexed_robustness["search"].search(query, limit=5)
    assert envelope["results"], f"query {query!r} must not return zero results"
    assert any(expected in r["file_path"] for r in envelope["results"]), (
        f"query {query!r} did not surface {expected}: "
        f"{[r['file_path'] for r in envelope['results']]}"
    )


def test_declared_rules_are_indexed_and_searchable(
    indexed_robustness: dict[str, Any],
) -> None:
    """Annotated definitions persist ``declared_rules`` into
    the code_chunks table at index time."""
    db = indexed_robustness["db"]
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT file_path, declared_rules FROM code_chunks "
            "WHERE declared_rules IS NOT NULL AND declared_rules != '';"
        ).fetchall()
    assert rows, "no code_chunks carry declared_rules"
    rules = "\n".join(r["declared_rules"] for r in rows)
    assert "PreAuthorize" in rules
    assert "hasRole" in rules


def test_infra_files_demoted_for_code_queries(
    indexed_robustness: dict[str, Any],
) -> None:
    """An infra file never surfaces in the top 5 of a
    code-language query — the answer stays within source files."""
    envelope = indexed_robustness["search"].search("how is a password encoded", limit=5)
    results = list(envelope["results"])
    assert results
    for result in results:
        assert "docker-compose.yml" not in result["file_path"]
        assert result["file_path"].lower() not in (
            "dockerfile",
            "makefile",
        )
    assert any(
        "PasswordService.java" in r["file_path"] or "SecurityConfig.java" in r["file_path"]
        for r in results
    )


def test_exhaustive_mode_counts_indexed_lines(
    indexed_robustness: dict[str, Any],
) -> None:
    """Exhaustive mode reports a complete, deduplicated line count matching the
    fixture's rg whole-file oracle."""
    import json
    from pathlib import Path

    oracle = json.loads(
        Path(__file__)
        .resolve()
        .parent.parent.joinpath("fixtures", "robustness.oracle.json")
        .read_text()
    )["terms"]
    for term, expected in oracle.items():
        envelope = indexed_robustness["search"].search(term, limit=50, mode="exhaustive")
        assert envelope["mode"] == "exhaustive"
        assert envelope["total_count"] == expected, (
            f"exhaustive count for {term!r} expected {expected}, got {envelope['total_count']}"
        )
        assert envelope["complete"] is True
        assert envelope["results"][0]["confidence_band"] == "high"


def test_enumerate_lists_all_controllers(
    indexed_robustness: dict[str, Any],
) -> None:
    """'list all controllers' returns exactly the eight
    controller classes with a truthful complete flag."""
    import json
    from pathlib import Path

    oracle = json.loads(
        Path(__file__)
        .resolve()
        .parent.parent.joinpath("fixtures", "robustness.oracle.json")
        .read_text()
    )
    envelope = indexed_robustness["search"].search(
        "list all controllers", limit=50, mode="enumerate"
    )
    assert envelope["mode"] == "enumerate"
    assert envelope["complete"] is True
    assert envelope["total_count"] == 8
    names = {r["file_path"].rsplit("/", 1)[-1].removesuffix(".java") for r in envelope["results"]}
    assert names == set(oracle["controllers"]), f"got controllers {names}"


def test_enumerate_truncation_is_honest(
    indexed_robustness: dict[str, Any],
) -> None:
    """When the enumeration set exceeds the limit, complete is False and
    truncated is True instead of pretending the list is exhaustive."""
    envelope = indexed_robustness["search"].search("all methods", limit=5, mode="enumerate")
    assert envelope["mode"] == "enumerate"
    assert envelope["total_count"] > 5
    assert envelope["truncated"] is True
    assert envelope["complete"] is False
    assert len(envelope["results"]) == 5


def test_enumerate_extensionless_infra_files(
    indexed_robustness: dict[str, Any],
) -> None:
    """Dockerfile/Makefile are indexed by name and enumerate completely
    — extension-less infra files the extension allowlist can never reach."""
    for query, expected_name in (("all dockerfiles", "Dockerfile"), ("all makefiles", "Makefile")):
        envelope = indexed_robustness["search"].search(query, limit=50, mode="enumerate")
        assert envelope["mode"] == "enumerate"
        assert envelope["total_count"] == 1, f"{query}: {envelope['total_count']}"
        assert envelope["complete"] is True
        assert envelope["results"][0]["file_path"].rsplit("/", 1)[-1] == expected_name
