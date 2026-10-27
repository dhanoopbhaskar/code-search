"""Ranking must not depend on where the repository is checked out.

The keyword index deliberately excludes the absolute file path from the scored
text: FTS5 length normalisation counts every token in a row, so a checkout
directory named after a query term used to reweight every chunk. Path lookup
has its own index (`paths_fts`), which these tests also keep honest.
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
    # Warm the model so both runs take the same ranked path.
    comps["search"].search("warm", limit=1)
    return comps


@pytest.mark.parametrize("query", ["article documentation", "how do comments get created"])
def test_ranking_ignores_the_checkout_path(tmp_path: Path, query: str) -> None:
    """The same corpus ranks identically under query-like ancestor directories."""
    rankings: dict[str, list[str]] = {}
    for name in ("test_baseline_repo", "test_article_documentation"):
        repo = tmp_path / name / "corpus"
        repo.parent.mkdir()
        comps = _index(repo)
        envelope = comps["search"].search(query, limit=10)
        rankings[name] = [
            Path(result["file_path"]).relative_to(repo).as_posix() for result in envelope["results"]
        ]

    assert rankings["test_baseline_repo"] == rankings["test_article_documentation"]


def test_exact_filename_query_still_resolves(tmp_path: Path) -> None:
    """Moving paths out of the scored index keeps exact filename lookup working."""
    repo = tmp_path / "corpus"
    comps = _index(repo)

    envelope = comps["search"].search("DEPLOYMENT.md", limit=10)

    assert any(
        Path(result["file_path"]).as_posix().endswith("docs/DEPLOYMENT.md")
        for result in envelope["results"]
    )
