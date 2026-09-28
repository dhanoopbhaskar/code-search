"""Unit tests for intent-based reranker boosts and penalties.

Pins the query-intent signals added to ``Reranker.rerank``: the
definition-owner boost surfaces the owning symbol's definition chunk under
definition-intent queries, and the model-file penalty demotes
model/DTO/assembler/exception plumbing under behavior-intent queries.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.engine.reranking import Reranker


class FakeConnection:
    def execute(self, _sql: str, _params: Any = None) -> list[dict[str, Any]]:
        return []

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[dict[str, Any]]:
        return []

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class FakeDB:
    def connect(self) -> FakeConnection:
        return FakeConnection()

    def write_transaction(self) -> FakeConnection:
        return FakeConnection()


@pytest.fixture
def reranker() -> Reranker:
    return Reranker(FakeDB())  # type: ignore[arg-type]


def _result(chunk_id: int, file_path: str, score: float = 0.5, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "chunk_id": chunk_id,
        "file_path": file_path,
        "score": score,
        "is_definition": False,
        "is_test_file": False,
        "is_non_canonical": False,
    }
    base.update(extra)
    return base


def test_definition_owner_boost_surfaces_owner(
    reranker: Reranker,
) -> None:
    """Under a definition-intent query, the queried symbol's
    definition chunk outranks an unrelated definition chunk."""
    owner = _result(
        1, "src/service.py", score=0.5, is_definition=True, fqn="::ArticleService.delete"
    )
    other = _result(2, "src/other.py", score=0.5, is_definition=True, fqn="::Unrelated.doThing")
    reranked = reranker.rerank([other, owner], query_terms=["delete"], query="definition of delete")
    assert reranked[0]["chunk_id"] == 1
    assert reranked[0]["score"] > reranked[1]["score"]


def test_model_file_penalty_under_behavior_intent(
    reranker: Reranker,
) -> None:
    """Under a behavior-intent query, a model file is demoted
    below a same-scored code file."""
    from src.engine.classification import FileRole

    code = _result(1, "src/service.py", score=0.5, file_role=FileRole.CODE)
    model = _result(2, "src/model.py", score=0.5, file_role=FileRole.MODEL)
    reranked = reranker.rerank([model, code], query="what happens when a user is used")
    assert reranked[0]["chunk_id"] == 1
    assert reranked[0]["score"] > reranked[1]["score"]


def test_no_penalty_without_behavior_intent(
    reranker: Reranker,
) -> None:
    """A non-behavior query leaves the model file untouched at equal score."""
    from src.engine.classification import FileRole

    model = _result(1, "src/model.py", score=0.5, file_role=FileRole.MODEL)
    reranked = reranker.rerank([model], query="model class")
    assert reranked[0]["score"] == 0.5


def test_intent_is_inert_without_query(
    reranker: Reranker,
) -> None:
    """Passing no query means no intent is detected, so the owner boost never
    fires and equal definitions stay at equal score."""
    owner = _result(
        1, "src/service.py", score=0.5, is_definition=True, fqn="::ArticleService.delete"
    )
    other = _result(2, "src/other.py", score=0.5, is_definition=True, fqn="::Unrelated.doThing")
    reranked = reranker.rerank([owner, other], query_terms=None)
    assert reranked[0]["score"] == reranked[1]["score"]
