"""Labelled ground truth for the confidence calibration evaluation.

Each :class:`GroundTruthCase` pairs a query with the primary definition it
should surface and the relevance labels the calibration harness scores against.
The set is drawn from two in-repo fixtures so the CI gate stays hermetic:

- ``tests/fixtures/quality_defects/`` — the reported ``AuthController.authenticate``
  case and the ``AuthService`` definition it calls.
- ``tests/fixtures/relevance/`` — the article-domain definitions
  (``ArticleService``/``ArticleController``/``ArticleRepository`` and the
  ``Article``/``Comment`` models) plus ``CommentService``.

The external ``ArticleController.save`` case from the report is not present in
the in-repo fixtures; it is covered by the harness ``--repo`` mode over the
``realworld-springboot`` checkout, with ``ArticleController.getArticle`` standing
in as the equivalent fixture-backed controller endpoint for the hermetic gate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GroundTruthCase:
    """One labelled query-to-expected-definition pair.

    Attributes:
        query: The query text submitted to the engine.
        expected_fqn: The expected primary definition (``Class.member`` form).
        expected_file: A path fragment used to locate the expected result.
        must_be_high: Whether the expected definition MUST be reported ``high``.
            True only for primary-definition cases; peripheral/reference and
            ambiguous-name cases set it False so they do not inflate recall.
        relevant_patterns: Path/fqn fragments marking a result as relevant.
        irrelevant_patterns: Path/fqn fragments marking a result as irrelevant.
    """

    query: str
    expected_fqn: str
    expected_file: str
    must_be_high: bool
    relevant_patterns: tuple[str, ...] = ()
    irrelevant_patterns: tuple[str, ...] = ()


GROUND_TRUTH_CASES: tuple[GroundTruthCase, ...] = (
    # --- Primary definitions (must be high) -------------------------------------
    GroundTruthCase(
        query="AuthController.authenticate",
        expected_fqn="AuthController.authenticate",
        expected_file="qualitydefects/auth/AuthController.java",
        must_be_high=True,
        relevant_patterns=("auth/AuthController.java", "auth/AuthService.java"),
    ),
    GroundTruthCase(
        query="ArticleController.getArticle",
        expected_fqn="ArticleController.getArticle",
        expected_file="article/ArticleController.java",
        must_be_high=True,
        relevant_patterns=("article/ArticleController.java", "article/ArticleService.java"),
    ),
    GroundTruthCase(
        query="ArticleService.createComment",
        expected_fqn="ArticleService.createComment",
        expected_file="article/ArticleService.java",
        must_be_high=True,
        relevant_patterns=(
            "article/ArticleService.java",
            "article/ArticleController.java",
            "article/Comment.java",
        ),
    ),
    GroundTruthCase(
        query="ArticleService.getArticle",
        expected_fqn="ArticleService.getArticle",
        expected_file="article/ArticleService.java",
        must_be_high=True,
        relevant_patterns=("article/ArticleService.java", "article/ArticleController.java"),
    ),
    GroundTruthCase(
        query="ArticleService.deleteArticle",
        expected_fqn="ArticleService.deleteArticle",
        expected_file="article/ArticleService.java",
        must_be_high=True,
        relevant_patterns=("article/ArticleService.java", "article/ArticleController.java"),
    ),
    GroundTruthCase(
        query="ArticleRepository.findById",
        expected_fqn="ArticleRepository.findById",
        expected_file="article/ArticleRepository.java",
        must_be_high=True,
        relevant_patterns=("article/ArticleRepository.java", "article/ArticleService.java"),
    ),
    GroundTruthCase(
        query="AuthService",
        expected_fqn="AuthService",
        expected_file="qualitydefects/auth/AuthService.java",
        must_be_high=True,
        relevant_patterns=(
            "auth/AuthService.java",
            "auth/AuthController.java",
            "AuthServiceTest.java",
        ),
    ),
    GroundTruthCase(
        query="AuthController",
        expected_fqn="AuthController",
        expected_file="qualitydefects/auth/AuthController.java",
        must_be_high=True,
        relevant_patterns=("auth/AuthController.java", "auth/AuthService.java"),
    ),
    GroundTruthCase(
        query="CommentService",
        expected_fqn="CommentService",
        expected_file="article/CommentService.java",
        must_be_high=True,
        relevant_patterns=("article/CommentService.java", "article/Comment.java"),
    ),
    GroundTruthCase(
        query="SecurityConfig",
        expected_fqn="SecurityConfig",
        expected_file="article/SecurityConfig.java",
        must_be_high=True,
        relevant_patterns=("article/SecurityConfig.java",),
    ),
    GroundTruthCase(
        query="DirectoryWalker",
        expected_fqn="DirectoryWalker",
        expected_file="qualitydefects/util/DirectoryWalker.java",
        must_be_high=True,
        relevant_patterns=("util/DirectoryWalker.java",),
    ),
    GroundTruthCase(
        query="AuthService.authenticate",
        expected_fqn="AuthService.authenticate",
        expected_file="qualitydefects/auth/AuthService.java",
        must_be_high=True,
        relevant_patterns=("auth/AuthService.java", "auth/AuthController.java"),
    ),
    GroundTruthCase(
        query="ArticleController.createComment",
        expected_fqn="ArticleController.createComment",
        expected_file="article/ArticleController.java",
        must_be_high=True,
        relevant_patterns=("article/ArticleController.java", "article/ArticleService.java"),
    ),
    # --- Peripheral / ambiguous cases (must NOT be high) ------------------------
    GroundTruthCase(
        query="Article",
        expected_fqn="Article",
        expected_file="article/Article.java",
        must_be_high=False,
        relevant_patterns=("article/Article.java", "article/ArticleRepository.java"),
    ),
    GroundTruthCase(
        query="Comment",
        expected_fqn="Comment",
        expected_file="article/Comment.java",
        must_be_high=False,
        relevant_patterns=("article/Comment.java", "article/CommentService.java"),
    ),
    GroundTruthCase(
        query="save",
        expected_fqn="save",
        expected_file="",
        must_be_high=False,
        relevant_patterns=("article/CommentService.java", "article/ArticleRepository.java"),
    ),
    GroundTruthCase(
        query="validate login credentials",
        expected_fqn="AuthService.authenticate",
        expected_file="qualitydefects/auth/AuthService.java",
        must_be_high=False,
        relevant_patterns=("auth/AuthController.java", "auth/AuthService.java"),
    ),
)


def case_queries() -> tuple[str, ...]:
    """Return the ground-truth query texts in declaration order."""
    return tuple(case.query for case in GROUND_TRUTH_CASES)
