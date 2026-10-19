"""Unit tests for conservative query-term normalization."""

from __future__ import annotations

from code_search.engine.query_terms import collapse_terms, morphological_variants


def test_morphological_variants_bridges_gerunds() -> None:
    assert morphological_variants("following") == ["following", "follow"]
    assert morphological_variants("favoriting") == ["favoriting", "favorit", "favorite"]
    assert morphological_variants("creating") == ["creating", "creat", "create"]


def test_morphological_variants_bridges_past_tense_and_plurals() -> None:
    assert morphological_variants("registered") == ["registered", "register"]
    assert morphological_variants("favorites") == ["favorites", "favorit", "favorite"]
    assert morphological_variants("queries") == ["queries", "query", "queri", "querie"]


def test_morphological_variants_leaves_identifiers_untouched() -> None:
    assert morphological_variants("isTokenValid") == ["isTokenValid"]
    assert morphological_variants("user") == ["user"]


def test_collapse_terms_picks_one_representative_per_concept() -> None:
    assert collapse_terms(["following", "follow", "user", "work"]) == [
        "follow",
        "user",
        "work",
    ]


def test_collapse_terms_prefers_exact_vocabulary_form() -> None:
    assert collapse_terms(["favoriting", "favorit", "favorite"], preferred={"favorite"}) == [
        "favorite"
    ]
