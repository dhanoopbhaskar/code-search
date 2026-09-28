import json

import pytest

from src.engine.metrics import MetricsCollector


@pytest.mark.integration
def test_metrics_json_format() -> None:
    mc = MetricsCollector()
    mc.record_query(100.0)
    mc.record_query(200.0)
    mc.record_redaction(3)
    snap = mc.get_metrics_snapshot()
    json_str = json.dumps(snap, indent=2, default=str)
    parsed = json.loads(json_str)
    assert "latency_ms" in parsed
    assert "total_queries" in parsed
    assert "total_redactions" in parsed
    assert parsed["total_queries"] == 2
    assert parsed["total_redactions"] == 3
