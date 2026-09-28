"""Unit tests for the serving-path modules (index change + model status).

Pins the index-change envelope logic and the model warm/cold
report against the contract schemas, with a fake metadata store
so no database is required.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.engine.index_metadata import IndexMetadata, IndexStatus
from src.engine.index_service import IndexChangeDetector
from src.engine.model_status import ModelState, report_model_status


class _FakeMetadataStore:
    def __init__(self, last_indexed_at: str | None) -> None:
        self._value = last_indexed_at

    def get(self, key: str) -> str | None:
        if key == "last_indexed_at":
            return self._value
        return None


def _iso(ts: datetime) -> str:
    return ts.isoformat().replace("+00:00", "Z")


class TestIndexChangeDetector:
    def test_from_metadata_store_seeds_loaded_mtime(self) -> None:
        loaded = _iso(datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC))
        detector = IndexChangeDetector.from_metadata_store(_FakeMetadataStore(loaded))
        result = detector.detect_index_change(datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC))
        assert result["has_changed"] is False
        assert result["envelope"] is None

    def test_rebuild_changes_mtime_and_surfaces_envelope(self) -> None:
        loaded = _iso(datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC))
        detector = IndexChangeDetector.from_metadata_store(_FakeMetadataStore(loaded))
        rebuilt = datetime(2026, 8, 24, 13, 0, 0, tzinfo=UTC)
        result = detector.detect_index_change(rebuilt)
        assert result["has_changed"] is True
        assert result["new_status"] is IndexStatus.STALE
        assert result["envelope"] == "index changed — restart required"

    def test_unindexed_metadata_has_no_spurious_change(self) -> None:
        detector = IndexChangeDetector.from_metadata_store(_FakeMetadataStore(None))
        result = detector.detect_index_change(None)
        assert result["has_changed"] is False
        assert result["envelope"] is None

    def test_detector_uses_explicit_metadata(self) -> None:
        meta = IndexMetadata(mtime=datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC))
        detector = IndexChangeDetector(metadata=meta)
        new_mtime = datetime(2026, 8, 24, 12, 30, 0, tzinfo=UTC)
        assert detector.detect_index_change(new_mtime)["has_changed"] is True


class TestReportModelStatus:
    def test_first_request_is_initializing(self) -> None:
        report = report_model_status(
            query_time_ms=1700,
            warmup_time_ms=1600,
            embedding_time_ms=50,
            ranking_time_ms=40,
            io_time_ms=10,
            is_first_request=True,
        )
        assert report["state"] is ModelState.INITIALIZING
        assert report["is_first_request"] is True
        breakdown = report["latency_breakdown"]
        assert (
            breakdown["cold_start"]
            + breakdown["embedding"]
            + breakdown["ranking"]
            + breakdown["io"]
            == 1700
        )

    def test_warmup_reports_cold(self) -> None:
        report = report_model_status(
            query_time_ms=100,
            warmup_time_ms=60,
            embedding_time_ms=20,
            ranking_time_ms=15,
            io_time_ms=5,
            is_first_request=False,
        )
        assert report["state"] is ModelState.COLD

    def test_warm_model_reports_warm(self) -> None:
        report = report_model_status(
            query_time_ms=40,
            warmup_time_ms=0,
            embedding_time_ms=15,
            ranking_time_ms=20,
            io_time_ms=5,
            is_first_request=False,
        )
        assert report["state"] is ModelState.WARM
        assert report["latency_breakdown"]["cold_start"] == 0

    def test_latency_breakdown_sums_to_query_time(self) -> None:
        for query_time in (57, 1700, 15):
            report = report_model_status(
                query_time_ms=query_time,
                warmup_time_ms=3,
                embedding_time_ms=1,
                ranking_time_ms=2,
                io_time_ms=1,
                is_first_request=False,
            )
            breakdown = report["latency_breakdown"]
            total = (
                breakdown["cold_start"]
                + breakdown["embedding"]
                + breakdown["ranking"]
                + breakdown["io"]
            )
            assert total == query_time
