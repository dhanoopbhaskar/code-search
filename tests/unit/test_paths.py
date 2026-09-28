"""Unit tests for ``src/engine/paths.py``.

``normalize_indexed_path`` maps a caller-supplied absolute or project-relative
path onto the indexed repo root; ``resolve_stored_path`` maps a normalized
candidate back to the stored ``code_chunks.file_path`` spelling so symlink /
case variants hit the same indexed location.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.engine.paths import normalize_indexed_path, resolve_stored_path


def _build_sqlite(tmp_path: Path, stored_paths: list[str]) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE code_chunks (id INTEGER PRIMARY KEY, file_path TEXT, content TEXT);")
    for i, p in enumerate(stored_paths):
        conn.execute(
            "INSERT INTO code_chunks (id, file_path, content) VALUES (?, ?, ?);",
            (i, p, "def x(): pass"),
        )
    conn.commit()
    return conn


def _fs_is_case_insensitive(path: Path) -> bool:
    probe = path / "caseprobe.tmp"
    probe.write_text("x")
    case_insensitive = (path / "CASEPROBE.tmp").exists()
    probe.unlink(missing_ok=True)
    return case_insensitive


def test_absolute_path_is_kept(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    target = root / "src" / "a" / "b.java"
    target.parent.mkdir(parents=True)
    target.write_text("class B {}")
    result = normalize_indexed_path(str(target), root)
    assert result == target.resolve()


def test_relative_path_joined_to_index_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    target = root / "src" / "a" / "b.java"
    target.parent.mkdir(parents=True)
    target.write_text("class B {}")
    result = normalize_indexed_path("src/a/b.java", root)
    assert result == target.resolve()


def test_dot_and_dotdot_collapsed(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    target = root / "src" / "a" / "b.java"
    target.parent.mkdir(parents=True)
    target.write_text("class B {}")
    result = normalize_indexed_path("./src/a/../a/b.java", root)
    assert result == target.resolve()


def test_root_escape_returns_none(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "src").mkdir()
    assert normalize_indexed_path("../../etc/passwd", root) is None


def test_symlink_variant_resolves(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "real.py").write_text("def real(): pass")
    (root / "link.py").symlink_to(root / "src" / "real.py")
    result = normalize_indexed_path("link.py", root)
    assert result == (root / "src" / "real.py").resolve()


def test_case_variant_resolves_on_case_insensitive_fs(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "AuthService.java").write_text("class AuthService {}")
    if not _fs_is_case_insensitive(root):
        pytest.skip("case-insensitive filesystem required")
    result = normalize_indexed_path("src/authservice.java", root)
    assert result == (root / "src" / "AuthService.java").resolve()


def test_resolve_stored_path_exact_match(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    target = root / "src" / "a.py"
    target.parent.mkdir(parents=True)
    target.write_text("def a(): pass")
    conn = _build_sqlite(tmp_path, [str(target.resolve())])
    candidate = normalize_indexed_path("src/a.py", root)
    assert candidate is not None
    assert resolve_stored_path(candidate, conn) == str(target.resolve())


def test_resolve_stored_path_symlink_fallback(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    real = root / "src" / "real.py"
    real.write_text("def real(): pass")
    link = root / "src" / "link.py"
    link.symlink_to(real)
    stored = str(link)
    conn = _build_sqlite(tmp_path, [stored])
    candidate = normalize_indexed_path("src/real.py", root)
    assert candidate is not None
    assert resolve_stored_path(candidate, conn) == stored


def test_resolve_stored_path_case_fallback_on_case_insensitive_fs(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    target = root / "src" / "AuthService.java"
    target.write_text("class AuthService {}")
    if not _fs_is_case_insensitive(root):
        pytest.skip("case-insensitive filesystem required")
    stored = str(target.resolve())
    conn = _build_sqlite(tmp_path, [stored])
    candidate = normalize_indexed_path("src/authservice.java", root)
    assert candidate is not None
    assert resolve_stored_path(candidate, conn) == stored


def test_resolve_stored_path_no_match_returns_none(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    target = root / "src" / "a.py"
    target.parent.mkdir(parents=True)
    target.write_text("def a(): pass")
    conn = _build_sqlite(tmp_path, [str(root / "src" / "other.py")])
    candidate = normalize_indexed_path("src/a.py", root)
    assert candidate is not None
    assert resolve_stored_path(candidate, conn) is None
