"""Test suite against the test-repo submodule (Spring Boot Realworld Example App).

Runs the full set of tried searches documented across TEST_REPORT_*.md
to ensure the CLI behaves correctly against a real-world Java codebase.

Usage:
    pytest tests/test_repo/ -v
    pytest tests/test_repo/ -v --keep-index
    pytest tests/test_repo/ -v --keep-index --force-index
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from .conftest import _run_cs

pytestmark = [
    pytest.mark.usefixtures("indexed"),
    pytest.mark.test_repo,
]


def _search_rows(stdout: str) -> list[dict[str, Any]]:
    """Extract the ``results`` rows from a ``search --json`` envelope."""
    payload = json.loads(stdout)
    assert isinstance(payload, dict) and "results" in payload, (
        "search --json must return an envelope object with a 'results' list"
    )
    return payload["results"]


def _assert_symbol_resolved(data: dict[str, Any], expected_name: str) -> None:
    """Assert a symbol lookup resolved to *expected_name*.

    Unambiguous lookups carry the resolved ``symbol``; ambiguous ones carry a
    ``candidates`` list instead of a single ``symbol``.
    """
    assert data.get("found") is True
    symbol = data.get("symbol")
    if symbol is not None:
        assert symbol["name"] == expected_name
        return
    assert data.get("ambiguous") is True, "unresolved lookup without ambiguity flag"
    assert any(c.get("name") == expected_name for c in (data.get("candidates") or []))


# =========================================================================
# Search tests
# =========================================================================


class TestSearchBasic:
    """Basic search queries exercised across all test reports."""

    def test_search_article_service(self, repo_path: Path) -> None:
        result = _run_cs(["search", "article service", "--json", "--limit", "5"], cwd=repo_path)
        assert result.returncode == 0
        assert _search_rows(result.stdout), "Expected results for 'article service'"

    def test_search_user_authentication(self, repo_path: Path) -> None:
        result = _run_cs(["search", "user authentication", "--json", "--limit", "5"], cwd=repo_path)
        assert result.returncode == 0
        assert _search_rows(result.stdout), "Expected results for 'user authentication'"

    def test_search_jwt_token(self, repo_path: Path) -> None:
        result = _run_cs(["search", "jwt token", "--json", "--limit", "5"], cwd=repo_path)
        assert result.returncode == 0
        assert _search_rows(result.stdout), "Expected results for 'jwt token'"

    def test_search_user_registration(self, repo_path: Path) -> None:
        result = _run_cs(["search", "user registration", "--json", "--limit", "5"], cwd=repo_path)
        assert result.returncode == 0
        assert _search_rows(result.stdout), "Expected results for 'user registration'"

    def test_search_repository(self, repo_path: Path) -> None:
        result = _run_cs(["search", "repository", "--json", "--limit", "5"], cwd=repo_path)
        assert result.returncode == 0
        assert _search_rows(result.stdout), "Expected results for 'repository'"

    def test_search_jwtservice(self, repo_path: Path) -> None:
        result = _run_cs(["search", "JwtService", "--json", "--limit", "5"], cwd=repo_path)
        assert result.returncode == 0
        assert _search_rows(result.stdout), "Expected results for 'JwtService'"

    def test_search_default_image(self, repo_path: Path) -> None:
        result = _run_cs(["search", "defaultImage", "--json", "--limit", "5"], cwd=repo_path)
        assert result.returncode == 0
        assert _search_rows(result.stdout), "Expected results for 'defaultImage'"


class TestSearchJsonOutput:
    """Search with JSON output and metadata field verification."""

    def test_search_article_json_limit3(self, repo_path: Path) -> None:
        result = _run_cs(["search", "article", "--json", "--limit", "3"], cwd=repo_path)
        assert result.returncode == 0
        rows = _search_rows(result.stdout)
        assert len(rows) <= 3
        if rows:
            for key in ("chunk_id", "file_path", "score", "content", "bm25_score", "vector_score"):
                assert key in rows[0], f"Missing key '{key}'"

    def test_search_repository_json_metadata(self, repo_path: Path) -> None:
        result = _run_cs(["search", "repository", "--json", "--limit", "5"], cwd=repo_path)
        assert result.returncode == 0
        for r in _search_rows(result.stdout):
            meta_keys = (
                "score",
                "bm25_score",
                "vector_score",
                "is_definition",
                "is_test_file",
                "chunk_type",
                "redacted_count",
                "below_threshold",
                "session_weight",
            )
            for key in meta_keys:
                assert key in r, f"Missing metadata key '{key}'"

    def test_search_score_range(self, repo_path: Path) -> None:
        result = _run_cs(["search", "article", "--json", "--limit", "10"], cwd=repo_path)
        assert result.returncode == 0
        for r in _search_rows(result.stdout):
            assert 0.0 <= r["score"] <= 1.0, f"Score {r['score']} out of range [0,1]"

    def test_search_below_threshold_flag(self, repo_path: Path) -> None:
        result = _run_cs(["search", "article", "--json", "--limit", "10"], cwd=repo_path)
        assert result.returncode == 0
        for r in _search_rows(result.stdout):
            assert "below_threshold" in r
            assert "relevance_threshold_applied" in r


class TestSearchNonsenseQuery:
    """Nonsense queries must return empty results (regression guard)."""

    def test_search_zzzznotexists_returns_empty(self, repo_path: Path) -> None:
        result = _run_cs(["search", "zzzznotexists", "--json"], cwd=repo_path)
        assert result.returncode == 0
        assert _search_rows(result.stdout) == [], "Nonsense query should return no results"


class TestSearchFilters:
    """Language and test-file filtering."""

    def test_search_language_java(self, repo_path: Path) -> None:
        result = _run_cs(
            ["search", "createUser", "--language", "java", "--json", "--limit", "10"],
            cwd=repo_path,
        )
        assert result.returncode == 0
        for r in _search_rows(result.stdout):
            assert r.get("language") == "java", f"Expected java, got {r.get('language')}"

    def test_search_no_include_tests(self, repo_path: Path) -> None:
        result = _run_cs(
            ["search", "article", "--no-include-tests", "--json", "--limit", "10"],
            cwd=repo_path,
        )
        assert result.returncode == 0
        for r in _search_rows(result.stdout):
            assert not r.get("is_test_file"), (
                f"Test file included despite --no-include-tests: {r.get('file_path')}"
            )

    def test_search_include_tests(self, repo_path: Path) -> None:
        result = _run_cs(
            ["search", "article", "--include-tests", "--json", "--limit", "10"],
            cwd=repo_path,
        )
        assert result.returncode == 0
        has_tests = any(r.get("is_test_file") for r in _search_rows(result.stdout))
        assert has_tests, "Test files should appear when include-tests is True"


class TestSearchResourceFiles:
    """Resource file indexing (XML, Properties, Gradle, etc.)."""

    def test_search_mybatis_mapper(self, repo_path: Path) -> None:
        result = _run_cs(["search", "mybatis mapper", "--json", "--limit", "25"], cwd=repo_path)
        assert result.returncode == 0
        xml_files = [
            r for r in _search_rows(result.stdout) if r.get("file_path", "").endswith(".xml")
        ]
        assert xml_files, "Expected XML mapper results for 'mybatis mapper'"

    def test_search_application_properties(self, repo_path: Path) -> None:
        result = _run_cs(
            ["search", "application.properties", "--json", "--limit", "5"],
            cwd=repo_path,
        )
        assert result.returncode == 0
        assert _search_rows(result.stdout), "Expected results for 'application.properties'"

    def test_search_build_gradle(self, repo_path: Path) -> None:
        result = _run_cs(["search", "build.gradle", "--json", "--limit", "25"], cwd=repo_path)
        assert result.returncode == 0
        gradle_files = [
            r for r in _search_rows(result.stdout) if r.get("file_path", "").endswith(".gradle")
        ]
        assert gradle_files, "Expected Gradle results for 'build.gradle'"


class TestSearchUserAuthJWT:
    """The most comprehensive search query from later reports."""

    def test_search_user_authentication_jwt_token(self, repo_path: Path) -> None:
        result = _run_cs(
            ["search", "user authentication JWT token", "--json", "--limit", "10"],
            cwd=repo_path,
        )
        assert result.returncode == 0
        rows = _search_rows(result.stdout)
        assert rows, "Expected results for 'user authentication JWT token'"
        jwt_files = [
            r for r in rows if "Jwt" in r.get("file_path", "") or "jwt" in r.get("file_path", "")
        ]
        assert jwt_files, "Expected JWT-related results for JWT query"

    def test_search_user_auth_jwt_redaction_count(self, repo_path: Path) -> None:
        result = _run_cs(
            ["search", "user authentication JWT token", "--json", "--limit", "10"],
            cwd=repo_path,
        )
        assert result.returncode == 0
        redacted_results = [
            r for r in _search_rows(result.stdout) if r.get("redacted_count", 0) > 0
        ]
        assert redacted_results, "Expected at least one result with redacted secrets"

    def test_search_jwt_secret_properties_redacted(self, repo_path: Path) -> None:
        result = _run_cs(["search", "jwt.secret", "--json", "--limit", "5"], cwd=repo_path)
        assert result.returncode == 0
        for r in _search_rows(result.stdout):
            if "application.properties" in r.get("file_path", ""):
                assert "[REDACTED]" in r.get("content", ""), (
                    "application.properties jwt.secret should be redacted"
                )
                break
        else:
            pytest.fail("application.properties not found for 'jwt.secret' query")


# =========================================================================
# Symbol lookup tests
# =========================================================================


class TestSymbolSimpleName:
    """Symbol lookup by simple (unqualified) name."""

    def test_symbol_article_query_service(self, repo_path: Path) -> None:
        result = _run_cs(["symbol", "ArticleQueryService", "--json"], cwd=repo_path)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data.get("found") is True
        assert data["symbol"]["name"] == "ArticleQueryService"

    def test_symbol_article_api(self, repo_path: Path) -> None:
        result = _run_cs(["symbol", "ArticleApi", "--json"], cwd=repo_path)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data.get("found") is True
        assert data["symbol"]["name"] == "ArticleApi"

    def test_symbol_user_service(self, repo_path: Path) -> None:
        result = _run_cs(["symbol", "UserService", "--json"], cwd=repo_path)
        assert result.returncode == 0
        _assert_symbol_resolved(json.loads(result.stdout), "UserService")

    def test_symbol_user_service_full_source(self, repo_path: Path) -> None:
        result = _run_cs(["symbol", "UserService"], cwd=repo_path)
        assert result.returncode == 0
        assert "UserService" in result.stdout


class TestSymbolConventionalFQN:
    """Symbol lookup by conventional Java dotted FQN."""

    def test_symbol_conventional_class_user_service(self, repo_path: Path) -> None:
        result = _run_cs(
            ["symbol", "io.spring.application.user.UserService", "--json"],
            cwd=repo_path,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data.get("found") is True, "Conventional FQN class lookup failed"
        assert data["symbol"]["name"] == "UserService"

    def test_symbol_conventional_method_with_params(self, repo_path: Path) -> None:
        result = _run_cs(
            ["symbol", "io.spring.core.service.JwtService.toToken(User)", "--json"],
            cwd=repo_path,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data.get("found") is True, "Conventional FQN method (with params) lookup failed"
        _assert_symbol_resolved(data, "toToken")

    def test_symbol_conventional_method_without_params(self, repo_path: Path) -> None:
        result = _run_cs(
            ["symbol", "io.spring.core.service.JwtService.toToken", "--json"],
            cwd=repo_path,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data.get("found") is True, "Bare method lookup resolved to a single overload"
        _assert_symbol_resolved(data, "toToken")

    def test_symbol_conventional_realworld_app(self, repo_path: Path) -> None:
        result = _run_cs(
            ["symbol", "io.spring.RealWorldApplication", "--json"],
            cwd=repo_path,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data.get("found") is True

    def test_symbol_conventional_method_create_user(self, repo_path: Path) -> None:
        result = _run_cs(
            [
                "symbol",
                "io.spring.application.user.UserService.createUser(RegisterParam)",
                "--json",
            ],
            cwd=repo_path,
        )
        assert result.returncode == 0
        _assert_symbol_resolved(json.loads(result.stdout), "createUser")


class TestSymbolNotFound:
    """Symbol lookup for non-existent symbols."""

    def test_symbol_non_existent_class(self, repo_path: Path) -> None:
        result = _run_cs(["symbol", "NonExistentClass", "--json"], cwd=repo_path)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data.get("found") is False

    def test_symbol_not_found_message(self, repo_path: Path) -> None:
        result = _run_cs(["symbol", "NonExistentClass"], cwd=repo_path)
        assert result.returncode == 0
        assert "not found" in result.stdout.lower()


# =========================================================================
# Call graph tests
# =========================================================================


class TestGraphBasic:
    """Call graph traversal (known limitation: cross-file edges empty)."""

    def test_graph_article_api(self, repo_path: Path) -> None:
        result = _run_cs(
            ["graph", "ArticleApi", "--depth", "1", "--direction", "both", "--json"],
            cwd=repo_path,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "symbol" in data
        assert "callers" in data
        assert "callees" in data

    def test_graph_user_service(self, repo_path: Path) -> None:
        result = _run_cs(
            ["graph", "UserService", "--depth", "2", "--direction", "both", "--json"],
            cwd=repo_path,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "symbol" in data

    def test_graph_conventional_fqn_user_service(self, repo_path: Path) -> None:
        result = _run_cs(
            ["graph", "io.spring.application.user.UserService", "--depth", "2", "--json"],
            cwd=repo_path,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "symbol" in data

    def test_graph_conventional_fqn_article_command_service(self, repo_path: Path) -> None:
        result = _run_cs(
            [
                "graph",
                "io.spring.application.article.ArticleCommandService",
                "--depth",
                "2",
                "--json",
            ],
            cwd=repo_path,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "symbol" in data

    def test_graph_not_found(self, repo_path: Path) -> None:
        result = _run_cs(["graph", "nonexistent::ghost", "--json"], cwd=repo_path)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data.get("symbol") is None, "Unknown symbol should resolve to null"
        assert data.get("callers") == []
        assert data.get("callees") == []

    def test_graph_json_structure(self, repo_path: Path) -> None:
        result = _run_cs(
            ["graph", "ArticleApi", "--json"],
            cwd=repo_path,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "symbol" in data
        assert "callers" in data
        assert "callees" in data
        assert "fqn" in data["symbol"]

    def test_graph_direction_callees(self, repo_path: Path) -> None:
        result = _run_cs(
            ["graph", "UserService", "--direction", "callees", "--json"],
            cwd=repo_path,
        )
        assert result.returncode == 0
        json.loads(result.stdout)

    def test_graph_direction_callers(self, repo_path: Path) -> None:
        result = _run_cs(
            ["graph", "UserService", "--direction", "callers", "--json"],
            cwd=repo_path,
        )
        assert result.returncode == 0
        json.loads(result.stdout)
