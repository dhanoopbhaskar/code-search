from pathlib import Path
from typing import Any

import pytest

from code_search.engine.classification import FileRole, PathClass
from code_search.engine.config import Settings
from code_search.engine.reranking import Reranker, demote_test_file_candidates


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


def test_rerank_score_not_upper_clamped(reranker: Reranker) -> None:
    """Strong scores keep their magnitude instead of saturating at 1.0."""
    results = [
        {
            "chunk_id": 1,
            "file_path": "src/main.py",
            "score": 2.4,
            "is_definition": True,
            "is_test_file": False,
        }
    ]
    reranked = reranker.rerank(results)
    assert reranked[0]["score"] >= 1.0
    assert reranked[0]["score"] != 1.0
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
    from code_search.engine.classification import FileRole

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


def test_identifier_definition_overtakes_usage(reranker: Reranker) -> None:
    """A named identifier's definition outranks a file that only uses it."""
    results = [
        {
            "chunk_id": 10,
            "file_path": "src/conduit.ts",
            "fqn": "src/conduit.ts::render",
            "content": "return baseApiUrl;",
            "score": 1.0,
            "is_definition": False,
            "is_test_file": False,
        },
        {
            "chunk_id": 11,
            "file_path": "src/settings.ts",
            "fqn": "src/settings.ts::baseApiUrl",
            "content": "export const baseApiUrl = 'x';",
            "score": 0.8,
            "is_definition": True,
            "is_test_file": False,
        },
    ]
    reranked = reranker.rerank(results, query_terms=["baseApiUrl"], query="baseApiUrl")
    assert reranked[0]["chunk_id"] == 11


def test_config_key_definition_gets_boost(reranker: Reranker) -> None:
    """A dotted config key lifts the config chunk that defines it."""
    results = [
        {
            "chunk_id": 20,
            "file_path": "src/db.py",
            "fqn": "src/db.py::connect",
            "content": "read database.host",
            "score": 1.0,
            "is_definition": False,
            "is_test_file": False,
        },
        {
            "chunk_id": 21,
            "file_path": "config/application.yml",
            "fqn": "config/application.yml::2",
            "content": "database.host: localhost",
            "score": 1.0,
            "is_definition": False,
            "is_test_file": False,
            "content_type": "config",
        },
    ]
    reranked = reranker.rerank(results, query="database.host")
    assert reranked[0]["chunk_id"] == 21


def test_docs_intent_lifts_prose_over_close_code(reranker: Reranker) -> None:
    """A docs-shaped query lifts prose above a marginally stronger code hit."""
    results = [
        {
            "chunk_id": 30,
            "file_path": "src/deploy.py",
            "fqn": "src/deploy.py::deploy",
            "content": "def deploy(): ...",
            "score": 1.15,
            "is_definition": False,
            "is_test_file": False,
            "content_type": "code",
        },
        {
            "chunk_id": 31,
            "file_path": "README.md",
            "fqn": "README.md::1",
            "content": "How to deploy",
            "score": 1.0,
            "is_definition": False,
            "is_test_file": False,
            "content_type": "docs",
        },
    ]
    reranked = reranker.rerank(results, query="how to deploy")
    assert reranked[0]["chunk_id"] == 31


class _RootRow:
    """Row stub answering ``IndexMetadataStore.get`` for the index root."""

    def __init__(self, root: str) -> None:
        self._root = root

    def fetchone(self) -> dict[str, str] | None:
        return {"value": self._root}


class _RootConnection:
    """Connection stub that reports *root* as the recorded ``index_root``."""

    def __init__(self, root: str) -> None:
        self._root = root

    def execute(self, _sql: str, _params: Any = None) -> _RootRow:
        return _RootRow(self._root)

    def __enter__(self) -> "_RootConnection":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _RootedDB:
    """Fake graph database that only needs to answer the index-root lookup."""

    def __init__(self, root: Path) -> None:
        self._root = str(root)

    def connect(self) -> _RootConnection:
        return _RootConnection(self._root)

    def write_transaction(self) -> _RootConnection:
        return _RootConnection(self._root)


def _docs_pool(root: Path, docs_content: str) -> list[dict[str, Any]]:
    """Build a definition plus a non-definition docs chunk under *root*."""
    article = root / "src" / "Article.java"
    docs = root / "docs" / "DEPLOYMENT.md"
    return [
        {
            "chunk_id": 1,
            "file_path": str(article),
            "fqn": f"{article}::Article",
            "content": "class Article {}",
            "score": 2.0,
            "is_definition": True,
            "is_test_file": False,
            "content_type": "code",
            "file_role": FileRole.CODE,
        },
        {
            "chunk_id": 2,
            "file_path": str(docs),
            "fqn": f"{docs}::## Deployment notes",
            "content": docs_content,
            "score": 1.0,
            "is_definition": False,
            "is_test_file": False,
            "content_type": "docs",
            "file_role": FileRole.DOCS,
        },
    ]


@pytest.mark.parametrize("parent", ["repo", "test_article_documentation"])
def test_usage_penalty_ignores_the_checkout_directory(tmp_path: Path, parent: str) -> None:
    """A checkout directory named after a query term must not demote chunks.

    The usage-penalty haystack includes the chunk FQN, which embeds the
    absolute file path. Matching the concept there made the 0.85 penalty fire
    on every prose chunk when the repository was cloned into a directory such
    as ``test_article_documentation``.
    """
    root = tmp_path / parent / "corpus"
    settings = Settings(context_dir=tmp_path)
    reranker = Reranker(_RootedDB(root), settings=settings)  # type: ignore[arg-type]

    results = _docs_pool(root, "Connection pool settings and timeouts.")
    reranked = reranker.rerank(results, query="article documentation")
    docs = next(r for r in reranked if r["chunk_id"] == 2)

    expected = settings.docs_content_boost * settings.docs_project_boost
    assert docs["score"] == pytest.approx(expected)


def test_usage_penalty_still_applies_to_content_mentions(tmp_path: Path) -> None:
    """A prose chunk that genuinely references the concept is still demoted."""
    root = tmp_path / "repo" / "corpus"
    settings = Settings(context_dir=tmp_path)
    reranker = Reranker(_RootedDB(root), settings=settings)  # type: ignore[arg-type]

    results = _docs_pool(root, "## What happens when an article is saved")
    reranked = reranker.rerank(results, query="article documentation")
    docs = next(r for r in reranked if r["chunk_id"] == 2)

    expected = (
        settings.docs_content_boost
        * settings.docs_project_boost
        * settings.identifier_usage_penalty
    )
    assert docs["score"] == pytest.approx(expected)
