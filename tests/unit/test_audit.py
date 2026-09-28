from __future__ import annotations

from pathlib import Path

import pytest

from src.engine.audit import AuditDatabase


@pytest.fixture
def audit_db(tmp_path: Path) -> AuditDatabase:
    db = AuditDatabase(tmp_path / "audit.db")
    db.initialize()
    return db


def test_write_entry(audit_db: AuditDatabase) -> None:
    entry_id = audit_db.write_entry(
        query_type="search",
        query_summary="test query",
        result_count=5,
        duration_ms=100,
        redacted_count=2,
    )
    assert entry_id is not None
    assert isinstance(entry_id, int)


def test_write_entry_invalid_type(audit_db: AuditDatabase) -> None:
    with pytest.raises(ValueError, match="Invalid query_type"):
        audit_db.write_entry(query_type="invalid_type")


def test_count_entries_empty(audit_db: AuditDatabase) -> None:
    count = audit_db.count_entries()
    assert count == 0


def test_count_entries(audit_db: AuditDatabase) -> None:
    audit_db.write_entry(query_type="search")
    audit_db.write_entry(query_type="get_symbol_definition")
    count = audit_db.count_entries()
    assert count == 2


def test_count_by_type(audit_db: AuditDatabase) -> None:
    audit_db.write_entry(query_type="search")
    audit_db.write_entry(query_type="search")
    audit_db.write_entry(query_type="get_symbol_definition")
    search_count = audit_db.count_entries(query_type="search")
    assert search_count == 2
    sym_count = audit_db.count_entries(query_type="get_symbol_definition")
    assert sym_count == 1
    other_count = audit_db.count_entries(query_type="find_related")
    assert other_count == 0


def test_get_entries_empty(audit_db: AuditDatabase) -> None:
    entries = audit_db.get_entries()
    assert entries == []


def test_get_entries(audit_db: AuditDatabase) -> None:
    for i in range(5):
        audit_db.write_entry(
            query_type="search",
            query_summary=f"query_{i}",
            result_count=i,
        )
    entries = audit_db.get_entries()
    assert len(entries) == 5
    assert entries[0]["query_summary"] == "query_4"


def test_get_entries_limit_offset(audit_db: AuditDatabase) -> None:
    for i in range(10):
        audit_db.write_entry(query_type="search", query_summary=f"q_{i}")
    page = audit_db.get_entries(limit=3, offset=0)
    assert len(page) == 3
    page2 = audit_db.get_entries(limit=3, offset=3)
    assert len(page2) == 3
    assert page[0]["id"] != page2[0]["id"]


def test_get_entries_filtered_by_type(audit_db: AuditDatabase) -> None:
    audit_db.write_entry(query_type="search", query_summary="s1")
    audit_db.write_entry(query_type="get_call_neighbors", query_summary="g1")
    audit_db.write_entry(query_type="search", query_summary="s2")
    search_entries = audit_db.get_entries(query_type="search")
    assert len(search_entries) == 2
    for e in search_entries:
        assert e["query_type"] == "search"


def test_entry_structure(audit_db: AuditDatabase) -> None:
    audit_db.write_entry(
        query_type="search",
        query_summary="test query",
        result_count=5,
        duration_ms=100,
        redacted_count=2,
    )
    entries = audit_db.get_entries()
    assert len(entries) == 1
    e = entries[0]
    assert e["query_type"] == "search"
    assert e["query_summary"] == "test query"
    assert e["result_count"] == 5
    assert e["duration_ms"] == 100
    assert e["redacted_count"] == 2
    assert e["timestamp"] is not None


def test_write_entry_defaults(audit_db: AuditDatabase) -> None:
    entry_id = audit_db.write_entry(query_type="search")
    assert entry_id is not None
    entries = audit_db.get_entries()
    assert len(entries) == 1
    assert entries[0]["result_count"] == 0
    assert entries[0]["duration_ms"] == 0
    assert entries[0]["redacted_count"] == 0
    assert entries[0]["query_summary"] is None


def test_append_only_no_update(audit_db: AuditDatabase) -> None:
    entry_id = audit_db.write_entry(query_type="search")
    assert entry_id is not None
    with pytest.raises(Exception, match="append-only"), audit_db.write_transaction() as conn:
        conn.execute(
            "UPDATE audit_log_entries SET result_count = 999 WHERE id = ?;",
            (entry_id,),
        )


def test_append_only_no_delete(audit_db: AuditDatabase) -> None:
    entry_id = audit_db.write_entry(query_type="search")
    assert entry_id is not None
    with pytest.raises(Exception, match="append-only"), audit_db.write_transaction() as conn:
        conn.execute(
            "DELETE FROM audit_log_entries WHERE id = ?;",
            (entry_id,),
        )


def test_concurrent_write_safety(audit_db: AuditDatabase) -> None:
    import threading

    errors: list[Exception] = []

    def writer(count: int) -> None:
        for i in range(count):
            try:
                audit_db.write_entry(query_type="search", query_summary=f"thread_{i}")
            except Exception as e:
                errors.append(e)

    threads = [threading.Thread(target=writer, args=(20,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Concurrent write errors: {errors}"
    assert audit_db.count_entries() == 80


def test_close(audit_db: AuditDatabase) -> None:
    audit_db.write_entry(query_type="search")
    audit_db.close()
    audit_db.write_entry(query_type="search")
    assert audit_db.count_entries() == 2
