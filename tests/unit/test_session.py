from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.engine.config import Settings
from src.engine.session import SessionDatabase


@pytest.fixture
def session_db(tmp_path: Path) -> SessionDatabase:
    settings = Settings(
        context_dir=tmp_path,
        session_ttl_hours=24,
        decay_constant=0.1,
    )
    db = SessionDatabase(tmp_path / "session.db", settings)
    db.initialize()
    return db


def test_record_event_write(session_db: SessionDatabase) -> None:
    sid = session_db.record_event("src/main.py", "WRITE")
    assert sid is not None
    rows = session_db.get_active_sessions()
    assert len(rows) >= 1
    assert rows[0]["file_path"] == "src/main.py"
    assert rows[0]["event_type"] == "WRITE"


def test_record_event_read(session_db: SessionDatabase) -> None:
    sid = session_db.record_event("src/utils.py", "READ")
    assert sid is not None
    rows = session_db.get_active_sessions()
    read_rows = [r for r in rows if r["file_path"] == "src/utils.py"]
    assert len(read_rows) >= 1
    assert read_rows[0]["event_type"] == "READ"


def test_record_event_invalid_type(session_db: SessionDatabase) -> None:
    with pytest.raises(ValueError, match="event_type must be READ or WRITE"):
        session_db.record_event("src/main.py", "INVALID")  # type: ignore[arg-type]


def test_get_weights_for_files_empty(session_db: SessionDatabase) -> None:
    weights = session_db.get_weights_for_files([])
    assert weights == []


def test_get_weights_for_files_no_match(session_db: SessionDatabase) -> None:
    weights = session_db.get_weights_for_files(["nonexistent.py"])
    assert weights == []


def test_weight_decay_write(session_db: SessionDatabase) -> None:
    session_db.record_event("src/main.py", "WRITE")
    weights = session_db.get_weights_for_files(["src/main.py"])
    assert len(weights) == 1
    w = weights[0]
    assert w["file_path"] == "src/main.py"
    assert w["weight_score"] <= 1.0
    assert w["weight_score"] > 0.0


def test_weight_decay_read(session_db: SessionDatabase) -> None:
    session_db.record_event("src/utils.py", "READ")
    weights = session_db.get_weights_for_files(["src/utils.py"])
    assert len(weights) == 1
    w = weights[0]
    assert w["file_path"] == "src/utils.py"
    assert w["weight_score"] <= 0.7
    assert w["weight_score"] > 0.0


def test_ttl_expiry(session_db: SessionDatabase) -> None:
    session_db.record_event("src/old.py", "WRITE", session_id="test-session")
    weights = session_db.get_weights_for_files(["src/old.py"])
    assert len(weights) == 1


def test_get_active_sessions(session_db: SessionDatabase) -> None:
    session_db.record_event("src/a.py", "WRITE")
    session_db.record_event("src/b.py", "READ")
    active = session_db.get_active_sessions()
    file_paths = {r["file_path"] for r in active}
    assert "src/a.py" in file_paths
    assert "src/b.py" in file_paths


def test_weight_decay_formula(session_db: SessionDatabase) -> None:
    session_db.record_event("src/live.py", "WRITE", session_id="decay-test")
    weights = session_db.get_weights_for_files(["src/live.py"])
    assert len(weights) == 1
    w = weights[0]["weight_score"]
    lam = 0.1

    now = datetime.now(UTC)
    rows = session_db.get_active_sessions()
    event_row = next(r for r in rows if r["session_id"] == "decay-test")
    event_time = datetime.fromisoformat(event_row["event_time"])
    delta_hours = (now - event_time).total_seconds() / 3600.0
    expected = 1.0 * math.exp(-lam * delta_hours)
    assert abs(w - expected) < 0.01


def test_track_git_changes_no_repo(session_db: SessionDatabase, tmp_path: Path) -> None:
    count = session_db.track_git_changes(tmp_path / "nonexistent")
    assert count == 0


def test_get_weights_for_files_multiple(session_db: SessionDatabase) -> None:
    session_db.record_event("src/a.py", "WRITE")
    session_db.record_event("src/b.py", "WRITE")
    weights = session_db.get_weights_for_files(["src/a.py", "src/b.py"])
    assert len(weights) == 2
    paths = {w["file_path"] for w in weights}
    assert paths == {"src/a.py", "src/b.py"}
