"""Labelled multi-hop questions for the graph-query evaluation.

Each case names a natural-language question and the symbol chain a correct
graph answer must contain. Chain identity is the trailing symbol name (the
part after ``::``), so the labels do not depend on absolute fixture paths.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MultiHopCase:
    """A multi-hop question and its ground-truth symbol chain."""

    question: str
    chain: tuple[str, ...]
    seed_hint: str


MULTIHOP_CASES: tuple[MultiHopCase, ...] = (
    MultiHopCase(
        question="how does favoriting an article flow from the controller to the repository",
        chain=(
            "ArticleController.favoriteArticle",
            "ArticleService.favorite",
            "ArticleRepository.save",
        ),
        seed_hint="ArticleController",
    ),
    MultiHopCase(
        question="trace the article favorite request from the web controller to storage",
        chain=(
            "ArticleController.favoriteArticle",
            "ArticleService.favorite",
            "ArticleRepository.save",
        ),
        seed_hint="ArticleController",
    ),
    MultiHopCase(
        question="where does ArticleService call the article repository",
        chain=("ArticleService.favorite", "ArticleRepository.save"),
        seed_hint="ArticleService",
    ),
    MultiHopCase(
        question="who calls ArticleRepository save",
        chain=("ArticleService.favorite", "ArticleRepository.save"),
        seed_hint="ArticleRepository.save",
    ),
    MultiHopCase(
        question="which implementation saves a favorite article",
        chain=("JdbcArticleRepository.save", "ArticleRepository.save"),
        seed_hint="JdbcArticleRepository",
    ),
)


def _normalized(fqn: str) -> str:
    """Strip a parameter list from an FQN for suffix matching."""
    return fqn.split("(", 1)[0]


def chain_is_present(chain: tuple[str, ...], fqns: list[str]) -> bool:
    """Return whether every chain member appears in *fqns* (suffix match)."""
    normalized = [_normalized(fqn) for fqn in fqns]
    return all(
        any(fqn.endswith(f"::{name}") or fqn.endswith(name) for fqn in normalized) for name in chain
    )
