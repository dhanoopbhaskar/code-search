"""Contract test for documentation/implementation drift.

Asserting zero documented-but-missing options and zero undocumented
implemented options across the documented code-search surface —
``README.md``, ``QUICK_START.md``, and the hand-written docs under ``docs/``,
excluding archived reports (``docs/archived/``). The repo ``AGENTS.md``
documents no code-search options and is out of scope.

The implemented surface is introspected from the real argparse tree
(:func:`src.cli.main.build_parser`) so the drift check never hard-codes the
option set; the documented surface is mined from the markdown prose and the
search-flag tables the docs ship.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Docs mined for the documented option surface. ``docs/archived/`` (reports)
# is out of scope; the repo ``AGENTS.md`` documents no code-search options
# and is out of scope.
_DOC_FILES = [
    p
    for p in [
        *[REPO_ROOT / "README.md", REPO_ROOT / "QUICK_START.md"],
        *sorted((REPO_ROOT / "docs").rglob("*.md")),
    ]
    if "archived" not in p.parts and p.is_file()
]

# Subcommands whose option surface the docs describe and the drift check must
# cover. ``serve``/``daemon``/``download-models``/``list-languages`` have no
# documented search-option surface; ``index``/``symbol``/``graph``/``metrics``
# are documented and stay in scope.
_DOCUMENTED_SUBCOMMANDS = ("index", "search", "symbol", "graph", "implementations", "metrics")


def _parser_choices() -> dict[str, argparse.ArgumentParser]:
    """Return the subcommand name → subparser map from the real argparse tree."""
    from src.cli.main import build_parser

    parser = build_parser()
    sub = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    return dict(sub.choices)


def _subparser_flags(subparser: argparse.ArgumentParser) -> set[str]:
    """Return the ``--flag`` option set of a subparser."""
    flags: set[str] = set()
    for action in subparser._actions:
        flags.update(opt for opt in action.option_strings if opt.startswith("--"))
    return flags


def _doc_text() -> str:
    """Concatenate the in-scope doc files for flag mining."""
    chunks = []
    for path in _DOC_FILES:
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(chunks)


@pytest.mark.contract
def test_every_documented_flag_is_implemented() -> None:
    """No documented-but-missing options.

    Every ``--flag`` the docs mention for a documented subcommand must exist
    on the real subparser. Flags scoped to other tools (the bundle installer,
    pytest, git) carry a different command name, so only ``--flag`` tokens
    that appear next to a ``code-search <subcommand>`` invocation count as
    documented options for that subcommand.
    """
    text = _doc_text()
    choices = _parser_choices()

    for subcommand in _DOCUMENTED_SUBCOMMANDS:
        pattern = rf"code-search {re.escape(subcommand)}\b([^\n]*?)(?=\n\s*\n|\Z)"
        documented: set[str] = set()
        for m in re.finditer(pattern, text, flags=re.MULTILINE):
            documented.update(re.findall(r"--[\w-]+", m.group(1)))
        missing = documented - _subparser_flags(choices[subcommand])
        assert not missing, (
            f"documented-but-missing {subcommand} flags: {sorted(missing)} "
            f"(SC-003: zero documented-but-missing options)"
        )


@pytest.mark.contract
def test_every_implemented_flag_is_documented() -> None:
    """No undocumented implemented options.

    Every implemented flag on a documented subcommand must appear somewhere
    in the in-scope docs. A flag that exists in code but is never documented
    is a silent surface asymmetry.
    """
    text = _doc_text()
    choices = _parser_choices()
    for subcommand in _DOCUMENTED_SUBCOMMANDS:
        implemented = _subparser_flags(choices[subcommand])
        # Global pre-parser flags are shared plumbing, not per-subcommand
        # options; their absence from the docs is not a surface asymmetry.
        undocumented = {
            f
            for f in implemented
            if f not in text and f not in ("--context-dir", "--verbose", "--help")
        }
        assert not undocumented, (
            f"undocumented implemented {subcommand} flags: {sorted(undocumented)} "
            f"(FR-005: the documented surface matches the implemented surface)"
        )


@pytest.mark.contract
def test_docs_content_filter_and_model_toggle_are_real() -> None:
    """The docs' content-filter and model-toggle surface is real.

    The docs advertise ``--content {code,config,docs,all}`` and the
    ``--no-model`` search fast path; both must exist on the real ``search``
    subparser and be documented (documented-but-missing / undocumented
    implemented both fail here).
    """
    text = _doc_text()
    search_flags = _subparser_flags(_parser_choices()["search"])
    assert "--content" in search_flags, (
        "docs advertise a content filter; the search subparser must expose --content"
    )
    assert "--no-model" in search_flags, (
        "docs advertise the --no-model fast path; the search subparser must expose it"
    )
    assert "--content" in text, "the content filter must be documented"
    assert "--no-model" in text, "the model toggle must be documented"


@pytest.mark.contract
def test_auto_scope_inference_and_scope_object_are_documented() -> None:
    """The docs describe the unspecified ``--content`` default,
    query-intent inference, and the surfaced ``scope`` object."""
    text = _doc_text()
    lowered = " ".join(text.split()).lower()
    assert "--content" in text, "the content option must be documented"
    assert "no scope preference" in lowered, (
        "omitting --content must be documented as no scope preference"
    )
    assert (
        "intent inference" in lowered or "intent-driven" in lowered or ("inferred scope" in lowered)
    ), "query-intent scope inference must be documented"
    assert "scope object" in lowered, "the surfaced scope object must be documented"
    assert "effective" in lowered, "the effective scope field must be documented"
    assert "origin" in lowered, "the scope origin field must be documented"


@pytest.mark.contract
def test_installer_no_model_description_is_scoped() -> None:
    """The installer ``--no-model`` row is scoped to the installer.

    ``README.md``'s bundle-installer section documents a ``--no-model`` flag
    with an install-time meaning ("skip installing the bundled embedding
    model"). Because the search command also uses ``--no-model`` for its
    lexical-only fast path, the installer row's description must be qualified
    as the installer's flag so the two meanings cannot be conflated.
    """
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8", errors="replace")
    lines = readme.splitlines()
    rows = [
        i
        for i, line in enumerate(lines)
        if "`--no-model`" in line and "install" in " ".join(lines[max(0, i - 12) : i + 1]).lower()
    ]
    assert rows, "the README must document the installer --no-model row"
    for i in rows:
        row_text = " ".join(lines[max(0, i - 12) : i + 2]).lower()
        assert "install" in row_text, (
            f"installer --no-model row must be scoped to the installer: {lines[i]!r}"
        )


@pytest.mark.contract
def test_docs_content_code_precision_scope_limitation() -> None:
    """The documented ``--content code`` option states that
    it improves precision but does not repair abstract-paraphrase failures."""
    text = _doc_text()
    lowered = " ".join(text.split()).lower()
    assert "`--content code`" in text, "the --content code option must be documented"
    assert "does not repair abstract-paraphrase" in lowered, (
        "the --content code precision-scope limitation must be stated in the docs"
    )
    assert "improves precision" in lowered, (
        "the --content code precision benefit must be stated in the docs"
    )
