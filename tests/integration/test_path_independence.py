"""Ranking must not depend on where the repository is checked out.

Two signal families used to read the stored absolute path: FTS5 length
normalisation, which counted every token of ``file_path``/``fqn``, and the
re-ranker's path-shape heuristics (usage penalty, docs/config tiers, module
cohesion, vendor/minified demotion). A checkout directory named after a query
term therefore reweighted chunks that had nothing to do with the query.

These tests index the same corpus under a neutral and a query-shaped ancestor
directory and require identical rankings *and* scores, on both the lexical and
the hybrid path. Path lookup has its own index (``paths_fts``), which the last
test keeps honest.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import FIXTURES_DIR, _indexed_components


def _index(repo: Path) -> dict[str, Any]:
    """Index the transparency corpus at *repo* and return its components."""
    shutil.copytree(FIXTURES_DIR / "transparency", repo)
    comps = _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})
    # Warm the model so the hybrid run has a dense arm to fuse.
    comps["search"].search("warm", limit=1)
    return comps


def _ranking(comps: dict[str, Any], query: str, *, no_model: bool) -> list[tuple[str, float]]:
    """Return ``(relative path, score)`` pairs for *query* best-first."""
    from code_search.engine.search import HybridSearch

    search = comps["search"]
    if no_model:
        search = HybridSearch(
            comps["db"],
            comps["vector_index"],
            comps["embedding_gen"],
            comps["settings"],
            no_model=True,
        )
    envelope = search.search(query, limit=10, content="all")
    root: Path = comps["repo"]
    return [
        (Path(result["file_path"]).relative_to(root).as_posix(), round(float(result["score"]), 6))
        for result in envelope["results"]
    ]


#: Ancestor directory names that used to reweight the corpus: two carrying the
#: query terms, and two that are themselves classification vocabulary
#: (``vendor`` → non-canonical/third-party, ``tests`` → test file).
_LAYOUTS = ("test_baseline_repo", "test_article_documentation", "vendor", "tests")


@pytest.mark.parametrize("no_model", [False, True], ids=["hybrid", "lexical"])
@pytest.mark.parametrize("query", ["article documentation", "deployment"])
def test_ranking_ignores_the_checkout_path(tmp_path: Path, query: str, no_model: bool) -> None:
    """The same corpus ranks identically under path-shaped ancestor directories.

    Scores are compared, not just ordering: the re-ranker's penalties are
    multiplicative, so a path leak rescaled every result while leaving the
    order intact for some queries.
    """
    baseline: list[tuple[str, float]] | None = None
    for name in _LAYOUTS:
        repo = tmp_path / name / "corpus"
        repo.parent.mkdir()
        comps = _index(repo)
        ranking = _ranking(comps, query, no_model=no_model)
        if baseline is None:
            baseline = ranking
        else:
            assert ranking == baseline, f"ranking changed under {name}/"


def test_exact_filename_query_still_resolves(tmp_path: Path) -> None:
    """Moving paths out of the scored index keeps exact filename lookup working."""
    repo = tmp_path / "corpus"
    comps = _index(repo)

    envelope = comps["search"].search("DEPLOYMENT.md", limit=10)

    assert any(
        Path(result["file_path"]).as_posix().endswith("docs/DEPLOYMENT.md")
        for result in envelope["results"]
    )
