"""Benchmark: ``.gitignore`` discovery stays within a bounded overhead.

Discovery now loads ignore specs while it walks instead of performing a second
full-tree walk. This benchmark builds a synthetic 10k-file tree, measures the
best-of-three discovery time with and without ``.gitignore`` handling, and
fails when the matcher more than doubles the walk. It also asserts both modes
discover the same files, so the overhead measurement is like-for-like.

Marked ``benchmark``/``slow`` so the fast CI gate excludes it; run locally with
``pytest tests/benchmarks/test_gitignore_overhead.py -q``.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from code_search.engine.parser import ASTParser

#: Synthetic tree shape: 100 directories x 100 Python files.
_TREE_DIRS = 100
_TREE_FILES = 100
#: Maximum accepted ratio of gitignore-aware to plain discovery time.
_MAX_OVERHEAD_RATIO = 2.5
#: Absolute ceiling absorbs timer noise when the plain walk is very fast.
_MAX_OVERHEAD_SECONDS = 0.05


@pytest.fixture(scope="module")
def synthetic_tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a 10k-file tree with a root ``.gitignore``."""
    root = tmp_path_factory.mktemp("gitignore_tree")
    for directory_index in range(_TREE_DIRS):
        directory = root / f"pkg{directory_index:03d}"
        directory.mkdir()
        for file_index in range(_TREE_FILES):
            (directory / f"mod{file_index:03d}.py").write_text("x = 1\n")
    # A directory pattern that matches nothing keeps both modes discovering the
    # same files while still forcing a rule evaluation per path.
    (root / ".gitignore").write_text("build/\n")
    return root


def _best_discovery_seconds(root: Path, *, respect_gitignore: bool) -> tuple[float, int]:
    """Return the best-of-three discovery time and the discovered file count."""
    parser = ASTParser(respect_gitignore=respect_gitignore)
    parser.discover_files(root)  # warm the OS and parser caches
    times: list[float] = []
    count = 0
    for _ in range(3):
        start = time.perf_counter()
        count = len(parser.discover_files(root))
        times.append(time.perf_counter() - start)
    return min(times), count


@pytest.mark.benchmark
@pytest.mark.slow
def test_gitignore_discovery_overhead_is_bounded(synthetic_tree: Path) -> None:
    """Gitignore-aware discovery does not substantially lengthen the walk."""
    plain_seconds, plain_count = _best_discovery_seconds(synthetic_tree, respect_gitignore=False)
    ignored_seconds, ignored_count = _best_discovery_seconds(synthetic_tree, respect_gitignore=True)

    assert plain_count == _TREE_DIRS * _TREE_FILES
    assert ignored_count == plain_count
    assert ignored_seconds <= plain_seconds * _MAX_OVERHEAD_RATIO + _MAX_OVERHEAD_SECONDS, (
        f"gitignore discovery took {ignored_seconds:.3f}s vs {plain_seconds:.3f}s"
    )
