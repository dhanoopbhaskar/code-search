"""Tests for domain expansion packs and repository-local vocabulary."""

from __future__ import annotations

import json
from pathlib import Path

from code_search.engine.config import Settings
from code_search.engine.expansions import ExpansionTable


def test_builtin_domain_packs_expand_commerce_vocabulary() -> None:
    """Common commerce prose reaches its code vocabulary."""
    table = ExpansionTable()
    assert "payment" in table.expand("checkout")
    assert "coupon" in table.expand("discount")
    assert "shipment" in table.expand("fulfillment")


def test_short_common_words_do_not_pull_a_domain_pack() -> None:
    """A prefix overlap of more than two characters is not a typo match."""
    table = ExpansionTable()
    assert "checkout" not in table.matched_phrases(
        "check if the article title or slug is already taken"
    )


def test_typo_prefix_matching_still_works() -> None:
    """The original short-typo tolerance is preserved."""
    table = ExpansionTable()
    assert "cors" in table.expand("cros origin")


def test_repo_local_expansion_pack_is_discovered(tmp_path: Path) -> None:
    """A repository can ship its own vocabulary next to ``.context``."""
    repo = tmp_path / "repo"
    context = repo / ".context"
    context.mkdir(parents=True)
    pack = repo / ".code-search"
    pack.mkdir()
    (pack / "expansions.json").write_text(
        json.dumps({"expansions": {"widget": ["gadget"]}}), encoding="utf-8"
    )

    settings = Settings.with_context_dir(context).with_repo_expansions()

    assert settings.expansion_file == str(pack / "expansions.json")


def test_explicit_expansion_file_wins_over_the_repo_pack(tmp_path: Path) -> None:
    """An operator-supplied expansion file is never overridden."""
    repo = tmp_path / "repo"
    context = repo / ".context"
    context.mkdir(parents=True)
    pack = repo / ".code-search"
    pack.mkdir()
    (pack / "expansions.json").write_text("{}", encoding="utf-8")

    settings = Settings(context_dir=context, expansion_file="/explicit/pack.json")
    assert settings.with_repo_expansions().expansion_file == "/explicit/pack.json"
