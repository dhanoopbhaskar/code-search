"""Unit tests for the static ExpansionTable.

Tests are written FIRST against the expansion table contract:
two-way acronym/phrase keys, case-insensitive match, built-in seeded defaults,
optional ``CODE_SEARCH_EXPANSION_FILE`` merge, and a no-op for empty config.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def table() -> object:
    from src.engine.expansions import ExpansionTable

    return ExpansionTable(config_path="")


def test_builtin_defaults_load(table: object) -> None:
    """Seeded report-verified pairs are present after construction."""
    assert table.expand("cors") == {"cors", "cross origin", "cross-origin"}
    assert "cors" in table.expand("cross origin")
    assert table.expand("feed") == {"feed", "getFeedByUser"}
    assert "favorite" in table.expand("favorited")
    assert "EmailTakenException" in table.expand("email taken")
    assert "EmailTakenException" in table.expand("email exists")


def test_two_way_acronym_phrase_keys(table: object) -> None:
    """Acronym <-> phrase expansion is symmetric."""
    assert "cors" in table.expand("cross origin")
    assert "cross origin" in table.expand("cors")


def test_case_insensitive_match(table: object) -> None:
    """Query-side matching is case-insensitive (incl. a typo)."""
    assert "cors" in table.expand("Cross Origin")
    assert "cors" in table.expand("CROS ORIGIN")
    assert "cors" in table.expand("cros origin")


def test_expanded_text_produces_extra_terms(table: object) -> None:
    """expanded_text appends expansion terms to the original query text."""
    text = table.expanded_text("configure cross origin requests from a browser")
    assert "cors" in text.lower()
    assert "cross origin" in text.lower()


def test_empty_config_is_noop(tmp_path: Path) -> None:
    """An empty/``""`` expansion file leaves built-in defaults active."""
    from src.engine.expansions import ExpansionTable

    t = ExpansionTable(config_path="")
    assert t.expand("cors") == {"cors", "cross origin", "cross-origin"}

    empty_file = tmp_path / "empty.json"
    empty_file.write_text("{}")
    t2 = ExpansionTable(config_path=str(empty_file))
    assert t2.expand("cors") == {"cors", "cross origin", "cross-origin"}


def test_genuinely_absent_acronym_unchanged(table: object) -> None:
    """An acronym with no expansion entry is passed through unchanged."""
    assert table.expand("websocket") == {"websocket"}


def test_expansion_file_merge_over_defaults(tmp_path: Path) -> None:
    """CODE_SEARCH_EXPANSION_FILE entries merge over (and extend) defaults."""
    from src.engine.expansions import ExpansionTable

    cfg = tmp_path / "expansions.json"
    cfg.write_text('{"expansions": {"websocket": ["ws"]}}')
    t = ExpansionTable(config_path=str(cfg))
    assert t.expand("websocket") == {"websocket", "ws"}
    assert t.expand("cors") == {"cors", "cross origin", "cross-origin"}
