from typing import Any

import pytest

from src.engine.classification import PathClass
from src.engine.reranking import Reranker, demote_test_file_candidates


class FakeConnection:
    def execute(self, _sql: str, _params: Any = None) -> list[dict[str, Any]]:
        return []

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[dict[str, Any]]:
        return []

    def __enter__(self) -> "FakeConnection":
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


def test_rerank_empty(reranker: Reranker) -> None:
    assert reranker.rerank([]) == []


def test_rerank_definition_boost(reranker: Reranker) -> None:
    results = [
        {
            "chunk_id": 1,
            "file_path": "src/main.py",
            "score": 0.5,
            "is_definition": True,
            "is_test_file": False,
        }
    ]
    reranked = reranker.rerank(results)
    assert reranked[0]["score"] > 0.5


def test_rerank_noise_penalty(reranker: Reranker) -> None:
    results = [
        {
            "chunk_id": 2,
            "file_path": "tests/test_main.py",
            "score": 0.5,
            "is_definition": False,
            "is_test_file": True,
        }
    ]
    reranked = reranker.rerank(results)
    assert reranked[0]["score"] < 0.5


def test_rerank_non_canonical_penalty(reranker: Reranker) -> None:
    results = [
        {
            "chunk_id": 5,
            "file_path": "generated/ArticleStub.java",
            "score": 0.5,
            "is_definition": False,
            "is_test_file": False,
            "is_non_canonical": True,
        }
    ]
    reranked = reranker.rerank(results)
    assert reranked[0]["score"] < 0.5


def test_rerank_non_canonical_penalty_stronger_than_test(reranker: Reranker) -> None:
    test_chunk = {
        "chunk_id": 6,
        "file_path": "tests/test_main.py",
        "score": 0.5,
        "is_definition": False,
        "is_test_file": True,
    }
    nc_chunk = {
        "chunk_id": 7,
        "file_path": "generated/ArticleStub.java",
        "score": 0.5,
        "is_definition": False,
        "is_test_file": False,
        "is_non_canonical": True,
    }
    reranked = reranker.rerank([test_chunk, nc_chunk])
    by_id = {r["chunk_id"]: r["score"] for r in reranked}
    assert by_id[7] < by_id[6]


def test_rerank_definition_and_test(reranker: Reranker) -> None:
    results = [
        {
            "chunk_id": 3,
            "file_path": "tests/test_main.py",
            "score": 0.5,
            "is_definition": True,
            "is_test_file": True,
        }
    ]
    reranked = reranker.rerank(results)
    expected = 0.5 * 1.2 * 0.5
    assert abs(reranked[0]["score"] - expected) < 0.01


def test_rerank_sorts_by_score(reranker: Reranker) -> None:
    results = [
        {
            "chunk_id": 1,
            "file_path": "a.py",
            "score": 0.3,
            "is_definition": False,
            "is_test_file": False,
        },
        {
            "chunk_id": 2,
            "file_path": "b.py",
            "score": 0.9,
            "is_definition": False,
            "is_test_file": False,
        },
        {
            "chunk_id": 3,
            "file_path": "c.py",
            "score": 0.6,
            "is_definition": False,
            "is_test_file": False,
        },
    ]
    reranked = reranker.rerank(results)
    assert reranked[0]["chunk_id"] == 2
    assert reranked[1]["chunk_id"] == 3
    assert reranked[2]["chunk_id"] == 1


def test_rerank_score_clamped(reranker: Reranker) -> None:
    results = [
        {
            "chunk_id": 1,
            "file_path": "src/main.py",
            "score": 0.9,
            "is_definition": True,
            "is_test_file": False,
        }
    ]
    reranked = reranker.rerank(results)
    assert reranked[0]["score"] <= 1.0
    assert reranked[0]["score"] >= 0.0


def test_rerank_no_definition_no_test(reranker: Reranker) -> None:
    results = [
        {
            "chunk_id": 4,
            "file_path": "src/utils.py",
            "score": 0.5,
            "is_definition": False,
            "is_test_file": False,
        }
    ]
    reranked = reranker.rerank(results)
    assert abs(reranked[0]["score"] - 0.5) < 0.01


def test_rerank_dts_penalty(reranker: Reranker) -> None:
    results = [
        {
            "chunk_id": 8,
            "file_path": "types/foo.d.ts",
            "score": 0.5,
            "is_definition": False,
            "is_test_file": False,
            "path_class": PathClass.DTS,
        }
    ]
    reranked = reranker.rerank(results)
    assert abs(reranked[0]["score"] - 0.5 * 0.7) < 0.01
    assert reranked[0]["score"] < 0.5


def test_rerank_barrel_penalty(reranker: Reranker) -> None:
    results = [
        {
            "chunk_id": 9,
            "file_path": "pkg/__init__.py",
            "score": 0.5,
            "is_definition": False,
            "is_test_file": False,
            "path_class": PathClass.BARREL,
        }
    ]
    reranked = reranker.rerank(results)
    assert abs(reranked[0]["score"] - 0.5 * 0.5) < 0.01
    assert reranked[0]["score"] < 0.5


def test_rerank_path_class_none_unchanged(reranker: Reranker) -> None:
    results = [
        {
            "chunk_id": 10,
            "file_path": "src/foo.ts",
            "score": 0.5,
            "is_definition": False,
            "is_test_file": False,
            "path_class": PathClass.CANONICAL,
        }
    ]
    reranked = reranker.rerank(results)
    assert abs(reranked[0]["score"] - 0.5) < 0.01


def test_demote_test_file_candidates_scales_test_scores(penalty: float = 0.5) -> None:
    """A test-file demotion is applied inside the candidate pool
    (pre-fusion) for natural-language production queries.

    The helper must scale test-file chunk scores by ``noise_penalty`` in both
    ranked lists so keyword-dense test classes cannot outrank production code
    on density alone, while leaving production chunks untouched.
    """
    bm25 = [(1, 0.9), (2, 0.8), (3, 0.7)]  # 2 = test-file chunk
    vector = [(3, 0.6), (2, 0.5), (1, 0.4)]
    demoted_bm25, demoted_vector = demote_test_file_candidates(
        bm25, vector, test_chunk_ids={2}, penalty=penalty
    )
    by_id = {cid: sc for cid, sc in demoted_bm25}
    assert by_id[2] == pytest.approx(0.8 * penalty)
    assert by_id[1] == 0.9
    assert by_id[3] == 0.7
    by_id_v = {cid: sc for cid, sc in demoted_vector}
    assert by_id_v[2] == pytest.approx(0.5 * penalty)
    assert by_id_v[1] == 0.4
    assert by_id_v[3] == 0.6


def test_demote_test_file_candidates_leaves_production_lists_unchanged() -> None:
    """When no chunk is a test file, the candidate pool passes
    through untouched."""
    bm25 = [(1, 0.9), (2, 0.8)]
    vector = [(2, 0.5), (1, 0.4)]
    demoted_bm25, demoted_vector = demote_test_file_candidates(
        bm25, vector, test_chunk_ids=set(), penalty=0.5
    )
    assert demoted_bm25 == bm25
    assert demoted_vector == vector


def test_reconcile_definition_owner_infra_file(reranker: Reranker) -> None:
    """A definition-owner chunk keeps its boost even when its
    file classifies as infra, so the canonical answer still outranks a
    same-scored reference on a code file."""
    from src.engine.classification import FileRole

    owner = {
        "chunk_id": 1,
        "file_path": "docker-compose.yml",
        "score": 0.5,
        "is_definition": True,
        "is_test_file": False,
        "fqn": "::compose.service.delete",
        "file_role": FileRole.INFRA,
    }
    reference = {
        "chunk_id": 2,
        "file_path": "src/main.py",
        "score": 0.5,
        "is_definition": False,
        "is_test_file": False,
        "file_role": FileRole.CODE,
    }
    reranked = reranker.rerank(
        [reference, owner], query_terms=["delete"], query="definition of delete"
    )
    assert reranked[0]["chunk_id"] == 1
    assert reranked[0]["score"] > reranked[1]["score"]


def test_query_intents_detect_authorization() -> None:
    """An authorization question fires the authorization intent
    flag, driving the definition/annotation boost."""
    reranker = Reranker(FakeDB())  # type: ignore[arg-type]
    _, _, _, auth = reranker._query_intents("restrict which users can modify a resource")
    assert auth is True
    _, _, _, auth2 = reranker._query_intents("access control permission check")
    assert auth2 is True
    _, _, _, auth3 = reranker._query_intents("how is the article stored")
    assert auth3 is False


def test_authorization_intent_boosts_guarded_definition(reranker: Reranker) -> None:
    """Under authorization intent, the definition/annotation chunk of
    authorization-relevant code receives the owner boost."""
    results = [
        {
            "chunk_id": 1,
            "file_path": "src/main/java/com/example/article/ArticleService.java",
            "fqn": "com.example.ArticleService.deleteArticle",
            "score": 0.4,
            "is_definition": True,
            "declared_rules": "@PreAuthorize(hasRole('ADMIN'))",
            "is_test_file": False,
            "file_role": "code",
        }
    ]
    reranked = reranker.rerank(results, query="who is allowed to delete an article")
    assert reranked[0]["score"] > 0.4, "auth-guarded definition must be boosted"


def test_authorization_intent_does_not_boost_unrelated_reference(reranker: Reranker) -> None:
    """A reference-only chunk that does not match the query fragments is
    not crowned by the authorization boost."""
    results = [
        {
            "chunk_id": 1,
            "file_path": "src/main/java/com/example/article/ArticleService.java",
            "fqn": "com.example.ArticleService.getArticle",
            "score": 0.4,
            "is_definition": True,
            "is_test_file": False,
            "file_role": "code",
        }
    ]
    reranked = reranker.rerank(results, query="who is allowed to delete an article")
    # The definition boost still applies (generic), but not the auth owner boost
    # for a chunk that has no auth-guard/query match.
    assert reranked[0]["score"] > 0.4
