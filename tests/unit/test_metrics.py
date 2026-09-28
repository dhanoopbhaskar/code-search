from src.engine.metrics import MetricsCollector


def test_metrics_empty() -> None:
    m = MetricsCollector()
    stats = m.get_latency_stats()
    assert stats["p50"] == 0.0
    assert stats["p95"] == 0.0
    assert stats["p99"] == 0.0


def test_metrics_single_query() -> None:
    m = MetricsCollector()
    m.record_query(100.0)
    stats = m.get_latency_stats()
    assert stats["p50"] == 100.0
    assert stats["p95"] == 100.0
    assert stats["p99"] == 100.0


def test_metrics_multiple_queries() -> None:
    m = MetricsCollector()
    for i in range(1, 101):
        m.record_query(float(i))
    stats = m.get_latency_stats()
    assert stats["p50"] == 51.0
    assert stats["p95"] == 96.0
    assert stats["p99"] == 100.0


def test_metrics_redaction_count() -> None:
    m = MetricsCollector()
    m.record_redaction(5)
    m.record_redaction(3)
    assert m.get_total_redactions() == 8


def test_metrics_total_queries() -> None:
    m = MetricsCollector()
    assert m.get_total_queries() == 0
    m.record_query(10.0)
    m.record_query(20.0)
    assert m.get_total_queries() == 2


def test_metrics_snapshot() -> None:
    m = MetricsCollector()
    m.record_query(150.0)
    m.record_query(250.0)
    m.record_redaction(2)
    snap = m.get_metrics_snapshot()
    assert snap["total_queries"] == 2
    assert snap["total_redactions"] == 2
    assert "latency_ms" in snap


def test_metrics_reset() -> None:
    m = MetricsCollector()
    m.record_query(100.0)
    m.record_redaction(1)
    m.reset()
    assert m.get_total_queries() == 0
    assert m.get_total_redactions() == 0
    assert m.get_latency_stats()["p50"] == 0.0


def test_metrics_percentile_edge_cases() -> None:
    m = MetricsCollector()
    assert m.get_percentile([], 50) == 0.0
    assert m.get_percentile([1.0], 50) == 1.0
    assert m.get_percentile([1.0, 2.0, 3.0], 100) == 3.0
    assert m.get_percentile([1.0, 2.0, 3.0], 0) == 1.0


def test_metrics_thread_safety() -> None:
    import concurrent.futures

    m = MetricsCollector()

    def record(n: int) -> None:
        for _ in range(n):
            m.record_query(10.0)
            m.record_redaction(1)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(record, 100) for _ in range(4)]
        concurrent.futures.wait(futures)
    assert m.get_total_queries() == 400
    assert m.get_total_redactions() == 400


def test_metrics_window_size() -> None:
    from dataclasses import replace

    from src.engine.config import Settings

    m = MetricsCollector(settings=replace(Settings(), metrics_window_size=5))
    for i in range(10):
        m.record_query(float(i))
    assert m.get_total_queries() == 10
    stats = m.get_latency_stats()
    assert stats["p99"] > 0.0
