"""Unit tests for ``src.engine.classification.file_role``.

The role classification drives the declared-rule boost and the infra/plumbing
demotions, so the path-shape resolver is pinned down here independently of the
indexed integration tests.
"""

from __future__ import annotations

import pytest

from src.engine.classification import FileRole, file_role


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/main/java/com/example/article/ArticleController.java", FileRole.CODE),
        ("src/main/java/com/example/article/ArticleService.java", FileRole.CODE),
        ("src/main/java/com/example/article/model/Article.java", FileRole.MODEL),
        ("src/main/java/com/example/user/model/User.java", FileRole.MODEL),
        ("src/main/java/com/example/article/dto/ArticleDto.java", FileRole.DTO),
        ("src/main/java/com/example/user/dto/UserDto.java", FileRole.DTO),
        ("src/main/java/com/example/article/assembler/ArticleAssembler.java", FileRole.ASSEMBLER),
        (
            "src/main/java/com/example/article/exception/ArticleNotFoundException.java",
            FileRole.EXCEPTION,
        ),
        ("src/main/java/com/example/user/exception/UserNotFoundException.java", FileRole.EXCEPTION),
        ("docker-compose.yml", FileRole.INFRA),
        ("Dockerfile", FileRole.INFRA),
        ("Makefile", FileRole.INFRA),
        ("deploy/k8s/service.yaml", FileRole.INFRA),
        ("pom.xml", FileRole.INFRA),
        ("src/main/resources/application.yml", FileRole.CONFIG),
        ("scripts/seed.sql", FileRole.CONFIG),
        ("src/main/java/com/example/security/CheckSecurity.java", FileRole.CODE),
        ("README.md", FileRole.DOCS),
        ("docs/OPERATIONS.md", FileRole.DOCS),
        ("guides/setup.markdown", FileRole.DOCS),
        ("guides/setup.adoc", FileRole.DOCS),
        ("docs/notes.txt", FileRole.DOCS),
        ("reports/code-search-vs-grep.md", FileRole.ANALYSIS),
        ("analysis/perf-review.md", FileRole.ANALYSIS),
        ("benchmarks/summary.md", FileRole.ANALYSIS),
        ("reports/code-search-vs-grep.md", FileRole.ANALYSIS),
        ("docs/reports/analysis.md", FileRole.ANALYSIS),
    ],
)
def test_file_role(path: str, expected: FileRole) -> None:
    assert file_role(path) == expected


def test_infra_precedence_over_resource_extension() -> None:
    assert file_role("docker-compose.yml") == FileRole.INFRA


def test_docs_content_type_precedence_over_path_shape() -> None:
    """A prose file never falls through to CODE/plumbing — ``content_type``
    wins over path-shape rules (the ``file_role``/``content_type`` parity)."""
    assert file_role("src/model/README.md") == FileRole.DOCS
    assert file_role("src/exception/report.txt") == FileRole.DOCS


def test_analysis_configurable_paths_extension() -> None:
    """The ``CODE_SEARCH_ANALYSIS_ARTIFACT_PATHS`` escape hatch extends the
    built-in artifact segments."""
    assert file_role("private/audit-notes.md") == FileRole.DOCS
    assert file_role("private/audit-notes.md", analysis_paths={"private"}) == FileRole.ANALYSIS


def test_ambiguous_analysis_md_defaults_to_docs_role() -> None:
    """A stray analysis-style ``.md`` outside a configured artifact directory
    keeps its content-type role (inclusion, not exclusion)."""
    assert file_role("analysis.md") == FileRole.DOCS
