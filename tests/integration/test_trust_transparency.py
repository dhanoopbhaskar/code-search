"""Every response carries trust guidance and timing.

Asserts that every ``confidence_band: "low"`` result carries
``borderline: true``; ``CODE_SEARCH_BORDERLINE_FILTER=1``
excludes low-band results; every envelope carries ``query_time_ms``;
high-confidence results are never tagged; and
envelope ``query_time_ms`` equals the audit-recorded duration, both recording
the engine's per-request timer.
"""

from __future__ import annotations

from typing import Any

import pytest

CONFIG_SCENT_QUERY = "database connection pool settings"


@pytest.mark.integration
@pytest.mark.slow
def test_low_band_results_carry_borderline_true(
    indexed_transparency: dict[str, Any],
) -> None:
    """Every low-confidence-band result carries
    ``borderline: true``; higher bands carry ``borderline: false`` and the
    field is always present.
    """
    envelope = indexed_transparency["search"].search(CONFIG_SCENT_QUERY, limit=10)
    results = envelope["results"]
    assert results, "expected results to inspect for borderline tagging"
    for result in results:
        assert "borderline" in result, "borderline field must always be present"
        band = result["confidence_band"]
        if band == "low":
            assert result["borderline"] is True, f"low-band result missing tag: {result['fqn']}"
        else:
            assert result["borderline"] is False, f"non-low result wrongly tagged: {result['fqn']}"


@pytest.mark.integration
@pytest.mark.slow
def test_high_confidence_results_never_tagged_borderline(
    indexed_transparency: dict[str, Any],
) -> None:
    """A high-confidence result is never tagged borderline."""
    envelope = indexed_transparency["search"].search(CONFIG_SCENT_QUERY, limit=10)
    for result in envelope["results"]:
        if result["confidence_band"] == "high":
            assert result["borderline"] is False


@pytest.mark.integration
@pytest.mark.slow
def test_borderline_filter_excludes_low_band_results(tmp_path: Any) -> None:
    """With ``CODE_SEARCH_BORDERLINE_FILTER=1`` low-band results are dropped
    from ranked responses entirely.
    """
    import shutil

    from tests.conftest import FIXTURES_DIR, _indexed_components

    repo = tmp_path / "transparency_repo"
    shutil.copytree(FIXTURES_DIR / "transparency", repo)
    comps = _indexed_components(
        repo,
        repo / ".context",
        settings_kwargs={"index_prose": True, "borderline_filter": True},
    )
    envelope = comps["search"].search(CONFIG_SCENT_QUERY, limit=10)
    for result in envelope["results"]:
        assert result["confidence_band"] != "low", (
            f"low-band result leaked through borderline filter: {result['fqn']}"
        )


@pytest.mark.integration
@pytest.mark.slow
def test_every_envelope_carries_query_time_ms(
    indexed_transparency: dict[str, Any],
) -> None:
    """Every envelope carries ``query_time_ms`` — ranked
    and no-match paths alike.
    """
    search = indexed_transparency["search"]
    ranked = search.search(CONFIG_SCENT_QUERY, limit=10)
    assert "query_time_ms" in ranked, "ranked envelope missing query_time_ms"
    assert isinstance(ranked["query_time_ms"], (int, float))
    assert ranked["query_time_ms"] >= 0

    no_match = search.search("zzzznonexistentquerytoken", limit=10)
    assert "query_time_ms" in no_match, "no-match envelope missing query_time_ms"


@pytest.mark.integration
@pytest.mark.slow
def test_envelope_query_time_matches_audit_recorded_duration(
    indexed_transparency: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The envelope ``query_time_ms`` equals the audit-recorded
    duration — both record the engine's per-request timer.
    """
    import argparse
    import json

    from src.cli.main import cmd_search
    from src.engine.audit import AuditDatabase

    context_dir = indexed_transparency["context_dir"]
    args = argparse.Namespace(
        command="search",
        query=CONFIG_SCENT_QUERY,
        limit=10,
        language=None,
        include_tests=True,
        mode="ranked",
        content="all",
        json=True,
        no_model=False,
        verbose=False,
        context_dir=str(context_dir),
    )
    rc = cmd_search(args)
    assert rc == 0, "CLI search should succeed"
    captured = capsys.readouterr()
    envelope = json.loads(captured.out)
    assert "query_time_ms" in envelope

    audit = AuditDatabase(context_dir / "audit.db")
    audit.initialize()
    rows = audit.get_entries(query_type="search", limit=5)
    assert rows, "expected an audit record for the search"
    latest = rows[0]
    assert abs(float(latest["duration_ms"]) - float(envelope["query_time_ms"])) < 2.0, (
        f"envelope {envelope['query_time_ms']}ms != audit {latest['duration_ms']}ms"
    )
