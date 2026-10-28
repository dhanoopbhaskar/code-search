"""Tests for the ``code-search instructions`` command."""

from __future__ import annotations

import argparse

import pytest

from code_search.cli.instructions import AGENT_INSTRUCTIONS, render_agent_instructions


def test_render_agent_instructions_returns_the_guide() -> None:
    """The renderer returns the complete static guide."""
    assert render_agent_instructions() == AGENT_INSTRUCTIONS
    assert AGENT_INSTRUCTIONS.startswith("# Using code-search with an AI agent")


def test_guide_covers_surfaces_and_safety_checks() -> None:
    """The guide names both surfaces and the trust checks an agent needs."""
    guide = render_agent_instructions()
    for tool in (
        "search",
        "get_symbol_definition",
        "get_call_neighbors",
        "find_related",
        "query_graph",
        "get_graph_schema",
        "code-search doctor",
        "code-search index",
        "vector_health",
        "--mode exhaustive",
        "--content",
        "--include-tests",
    ):
        assert tool in guide


def test_cmd_instructions_prints_without_an_index(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The command prints the guide and succeeds before any index exists."""
    from code_search.cli.main import cmd_instructions

    assert cmd_instructions(argparse.Namespace(verbose=False)) == 0
    captured = capsys.readouterr()
    assert "# Using code-search with an AI agent" in captured.out
    assert "## Typical workflow" in captured.out
    assert captured.err == ""


def test_parser_dispatches_instructions_command() -> None:
    """The argparse tree exposes the command and routes it to the handler."""
    from code_search.cli.main import build_parser, cmd_instructions

    args = build_parser().parse_args(["instructions"])
    assert args.command == "instructions"
    assert args.func is cmd_instructions
