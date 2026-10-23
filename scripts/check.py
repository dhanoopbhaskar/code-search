#!/usr/bin/env python3
"""Run the code quality gate on any operating system.

Mirrors ``scripts/check.sh`` (which remains a thin wrapper) so the same lint,
format, comment-reference, type, and test checks run on Linux, macOS, and
Windows. Arguments after ``--`` are forwarded to pytest.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _tool(name: str) -> list[str]:
    """Return the command that runs *name* in the current interpreter's env.

    Prefers the executable next to the running interpreter (venv installs that
    are not on ``PATH``), then ``PATH``, then the module entry point.
    """
    executable_dir = Path(sys.executable).parent
    for candidate in (executable_dir / name, executable_dir / f"{name}.exe"):
        if candidate.is_file():
            return [str(candidate)]
    found = shutil.which(name)
    if found:
        return [found]
    return [sys.executable, "-m", name]


def _run(label: str, command: list[str]) -> bool:
    """Run *command* from the repository root and report pass/fail."""
    print(f"========== {label} ==========")
    result = subprocess.run(command, cwd=ROOT, check=False)
    print("  PASS" if result.returncode == 0 else "  FAIL")
    print()
    return result.returncode == 0


def _parse_args(argv: list[str]) -> tuple[str, list[str]]:
    """Split the mode flags from arguments forwarded to pytest."""
    if "--" in argv:
        separator = argv.index("--")
        mode_args, pytest_args = argv[:separator], argv[separator + 1 :]
    else:
        mode_args, pytest_args = argv, []

    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--all", action="store_const", dest="mode", const="all")
    modes.add_argument("--lint", action="store_const", dest="mode", const="lint")
    modes.add_argument("--format", action="store_const", dest="mode", const="format")
    modes.add_argument("--typecheck", action="store_const", dest="mode", const="typecheck")
    modes.add_argument("--test", action="store_const", dest="mode", const="test")
    parser.set_defaults(mode="all")
    args = parser.parse_args(mode_args)
    return str(args.mode), pytest_args


def main(argv: list[str] | None = None) -> int:
    """Run the selected checks and return a process exit code."""
    mode, pytest_args = _parse_args(list(sys.argv[1:] if argv is None else argv))

    ruff = _tool("ruff")
    mypy = _tool("mypy")
    checks = {
        "lint": [
            ("ruff check", [*ruff, "check", "code_search/", "tests/"]),
            (
                "ruff format",
                [*ruff, "format", "--check", "code_search/", "tests/"],
            ),
            (
                "comment refs",
                [
                    sys.executable,
                    "scripts/check_comment_refs.py",
                    "code_search/",
                    "tests/",
                    "scripts/",
                ],
            ),
        ],
        "format": [
            ("ruff format", [*ruff, "format", "--check", "code_search/", "tests/"]),
        ],
        "typecheck": [("mypy", [*mypy, "code_search/"])],
        "test": [("pytest", [sys.executable, "-m", "pytest", "tests/", *pytest_args])],
    }
    if mode == "all":
        selected = [*checks["lint"], *checks["typecheck"], *checks["test"]]
    else:
        selected = checks[mode]

    failed = False
    for label, command in selected:
        if not _run(label, command):
            failed = True

    if failed:
        print("Some checks failed.")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
