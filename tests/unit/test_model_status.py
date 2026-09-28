"""Unit tests for the additive ``warmup_state`` on the model-status report."""

from __future__ import annotations

from src.engine.model_status import report_model_status


def test_warmup_state_is_additive_key() -> None:
    report = report_model_status(
        query_time_ms=20,
        warmup_time_ms=0,
        embedding_time_ms=0,
        ranking_time_ms=20,
        io_time_ms=0,
        is_first_request=True,
        warmup_state="warming",
    )
    assert report["warmup_state"] == "warming"
    assert report["state"] == "initializing"


def test_report_omits_warmup_state_when_not_supplied() -> None:
    report = report_model_status(
        query_time_ms=10,
        warmup_time_ms=0,
        embedding_time_ms=5,
        ranking_time_ms=3,
        io_time_ms=2,
        is_first_request=False,
    )
    assert "warmup_state" not in report


def test_latency_invariant_preserved_with_warmup_state() -> None:
    report = report_model_status(
        query_time_ms=100,
        warmup_time_ms=0,
        embedding_time_ms=0,
        ranking_time_ms=100,
        io_time_ms=0,
        is_first_request=True,
        warmup_state="warming",
    )
    breakdown = report["latency_breakdown"]
    assert (
        breakdown["cold_start"] + breakdown["embedding"] + breakdown["ranking"] + breakdown["io"]
        == 100
    )
    assert breakdown["cold_start"] == 0


def test_existing_fields_preserved() -> None:
    report = report_model_status(
        query_time_ms=50,
        warmup_time_ms=10,
        embedding_time_ms=20,
        ranking_time_ms=15,
        io_time_ms=5,
        is_first_request=False,
        warmup_state="warm",
    )
    assert report["state"] == "cold"
    assert report["warmup_time_ms"] == 10
    assert report["is_first_request"] is False
    breakdown = report["latency_breakdown"]
    total = breakdown["cold_start"] + breakdown["embedding"]
    assert total + breakdown["ranking"] + breakdown["io"] == 50
