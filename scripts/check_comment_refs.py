#!/usr/bin/env python3
"""Fail when source comments or docstrings reference spec-development artifacts.

The spec artifacts (feature descriptions, user stories, tasks, acceptance
criteria, ``spec.md``/``data-model.md`` and friends) are not bundled or shared
with the code. A reader of the shipped source has no way to look them up, so a
comment must state its actual reason instead of citing an identifier.

Scans ``#`` comments and module/class/function docstrings in ``.py`` files, and
``#`` comments in ``.sh`` files, so ordinary string literals (config keys such
as ``"spec"`` or filename infixes such as ``.spec.``) are never flagged.

Test fixtures under ``tests/fixtures/`` are skipped: their comments are indexed
content, so rewording them would change what the engine indexes.
"""

from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

FORBIDDEN = re.compile(
    r"""
    \b(?:FR|SC|US|AC)-?\d+\b      # requirement / criterion / story ids
    | \bT\d{3}\b                  # task ids
    | \bspec[ _-]\d+\b            # spec 018, spec-025
    | \bresearch\.md\b
    | \bdata-model\b
    | \btasks?\.md\b
    | \bplan\.md\b
    | \bspec\.md\b
    | \bquickstart(?:\.md)?\b
    | \bcontracts/
    | \buser stor(?:y|ies)\b
    | \bacceptance criteri
    | \bfeature[ _-]\d+\b
    | \bconstitution\b
    | §\s*[0-9IVX]
    """,
    re.IGNORECASE | re.VERBOSE,
)


_COMMENT_SUFFIXES = (".py", ".sh")


def _is_ignored(path: Path) -> bool:
    """Return whether *path* is exempt from the check.

    The checker itself is exempt (its own docstring and pattern spell the
    forbidden tokens out), and test fixtures are exempt because their comments
    are indexed content whose wording the engine tests depend on.
    """
    if path.name == Path(__file__).name:
        return True
    return "fixtures" in path.parts and "tests" in path.parts


def _docstring_spans(tree: ast.AST) -> list[tuple[int, int]]:
    """Return the ``(start, end)`` line spans of every docstring in *tree*."""
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                spans.append((first.value.lineno, first.value.end_lineno or first.value.lineno))
    return spans


def _shell_violations(lines: list[str]) -> list[tuple[int, str]]:
    """Return ``(line_number, text)`` for forbidden ``#`` comments in *lines*."""
    findings: list[tuple[int, str]] = []
    for line_number, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith("#") and FORBIDDEN.search(stripped):
            findings.append((line_number, stripped.strip()))
    return findings


def _violations(path: Path) -> list[tuple[int, str]]:
    """Return ``(line_number, text)`` for each forbidden reference in *path*."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()

    if path.suffix == ".sh":
        return sorted(set(_shell_violations(lines)))

    findings: list[tuple[int, str]] = []

    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT and FORBIDDEN.search(token.string):
            findings.append((token.start[0], token.string.strip()))

    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None
    if tree is not None:
        for start, end in _docstring_spans(tree):
            for offset, line in enumerate(lines[start - 1 : end]):
                if FORBIDDEN.search(line):
                    findings.append((start + offset, line.strip()))

    return sorted(set(findings))


def main(argv: list[str]) -> int:
    """Check every ``.py``/``.sh`` file under the given paths (default ``src``)."""
    roots = [Path(arg) for arg in argv[1:]] or [Path("src")]
    failed = False
    for root in roots:
        if root.is_file():
            files = [root]
        else:
            files = sorted(p for suffix in _COMMENT_SUFFIXES for p in root.rglob(f"*{suffix}"))
        for path in files:
            if _is_ignored(path):
                continue
            for line_number, text in _violations(path):
                print(f"{path}:{line_number}: references a spec artifact: {text}")
                failed = True
    if failed:
        print(
            "\nComments and docstrings must state the actual reason; the spec "
            "artifacts are not bundled with the code.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
