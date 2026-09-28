"""Labelled ranking cases for the filename/exact-match evaluation harness.

Cases are drawn from the hermetic ``tests/fixtures/relevance/`` corpus so the
CI gate is deterministic and fast. Each case names a query, the expected file
fragment (and symbol FQN for symbol cases), the active content scope, and the
expected rank ceiling.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Category vocabulary for a labelled case.
CATEGORIES = ("filename", "symbol", "general")


@dataclass(frozen=True)
class RankingCase:
    """One labelled evaluation entry.

    Attributes:
        query: Query text submitted to the engine.
        expected_file: Path fragment locating the expected result.
        expected_fqn: Expected symbol short name (for symbol cases), else ``None``.
        category: ``filename`` | ``symbol`` | ``general``.
        content_scope: Content scope active for the case (``docs``/``all``/...).
        top_k: Expected rank ceiling (1 for exact, 3 for descriptive).
    """

    query: str
    expected_file: str
    expected_fqn: str | None = None
    category: str = "general"
    content_scope: str | None = None
    top_k: int = 3


#: The labelled set. Filename cases must have ``top_k in {1, 3}``; symbol cases
#: must name ``expected_fqn``.
GROUND_TRUTH_CASES: tuple[RankingCase, ...] = (
    # --- exact filename ---
    RankingCase("README", "docs/README.md", category="filename", content_scope="docs", top_k=1),
    RankingCase("README", "docs/README.md", category="filename", content_scope="all", top_k=1),
    RankingCase(
        "OPERATIONS", "docs/OPERATIONS.md", category="filename", content_scope="docs", top_k=1
    ),
    RankingCase("SecurityConfig", "SecurityConfig.java", category="filename", top_k=1),
    # --- exact symbol / FQN ---
    RankingCase(
        "ArticleService",
        "ArticleService.java",
        expected_fqn="ArticleService",
        category="symbol",
        top_k=1,
    ),
    RankingCase(
        "ArticleController",
        "ArticleController.java",
        expected_fqn="ArticleController",
        category="symbol",
        top_k=1,
    ),
    RankingCase(
        "CommentService",
        "CommentService.java",
        expected_fqn="CommentService",
        category="symbol",
        top_k=1,
    ),
    RankingCase(
        "ArticleRepository",
        "ArticleRepository.java",
        expected_fqn="ArticleRepository",
        category="symbol",
        top_k=1,
    ),
    RankingCase(
        "ArticleService.getArticle",
        "ArticleService.java",
        expected_fqn="getArticle",
        category="symbol",
        top_k=1,
    ),
    # --- general concept queries ---
    RankingCase(
        "where is the article schema defined",
        "V1__create_articles_table.sql",
        category="general",
        top_k=3,
    ),
    RankingCase(
        "article not found error",
        "ArticleNotFoundException.java",
        category="general",
        top_k=3,
    ),
    RankingCase(
        "spring security rules",
        "SecurityConfig.java",
        category="general",
        top_k=3,
    ),
)


#: The case drawn from the hermetic ``spring_boot_main`` fixture: a
#: descriptive query must return the Spring Boot entry point at rank 1.
SPRING_BOOT_MAIN_CASES: tuple[RankingCase, ...] = (
    RankingCase(
        "spring boot main application",
        "RealWorldApplication.java",
        expected_fqn="RealWorldApplication",
        category="general",
        top_k=1,
    ),
)


@dataclass(frozen=True)
class ResolutionCase:
    """One labelled partial-name resolution entry.

    Attributes:
        fixture: The hermetic fixture the case is drawn from
            (``transparency``, ``overload_symbols``, or ``deprecated_symbols``).
        query: The partial reference submitted to ``resolve_name``.
        category: ``partial`` (unique-resolution) or ``overload`` (multi-match).
        expected_primary: Substring of the expected top-ranked declaration FQN.
        expected_order: Substrings of every expected candidate FQN, in order;
            empty when only the primary declaration is labelled.
    """

    fixture: str
    query: str
    category: str
    expected_primary: str
    expected_order: tuple[str, ...] = ()


#: Labelled partial-name resolution cases. ``partial`` cases must resolve to
#: exactly one declaration; ``overload`` cases must return a ranked list whose
#: first candidate is ``expected_primary``. Fixes the resolution denominator.
RESOLUTION_CASES: tuple[ResolutionCase, ...] = (
    # --- transparency: unique-resolution partials ---
    ResolutionCase("transparency", "delete", "partial", "::ArticleService.delete(long)"),
    ResolutionCase(
        "transparency", "ArticleService.delete", "partial", "::ArticleService.delete(long)"
    ),
    ResolutionCase(
        "transparency",
        "article.ArticleService.delete",
        "partial",
        "::ArticleService.delete(long)",
    ),
    ResolutionCase("transparency", "Article", "partial", "domain/Article.java::Article"),
    ResolutionCase("transparency", "setPublished", "partial", "::Article.setPublished(boolean)"),
    ResolutionCase("transparency", "isPublished", "partial", "::Article.isPublished"),
    ResolutionCase("transparency", "published", "partial", "::Article.published"),
    ResolutionCase(
        "transparency", "ArticleService.repository", "partial", "::ArticleService.repository"
    ),
    ResolutionCase(
        "transparency",
        "ArticleRepository",
        "partial",
        "repository/ArticleRepository.java::ArticleRepository",
    ),
    ResolutionCase("transparency", "deleteById", "partial", "::ArticleRepository.deleteById(long)"),
    # --- overload_symbols: unique-resolution partials ---
    ResolutionCase(
        "overload_symbols",
        "TokenService.generateToken(Map<String,Object>,String)",
        "partial",
        "generateToken(Map<String, Object>,String)",
    ),
    ResolutionCase("overload_symbols", "getId", "partial", "::Article.getId"),
    ResolutionCase("overload_symbols", "getUsername", "partial", "::Profile.getUsername"),
    ResolutionCase(
        "overload_symbols", "update", "partial", "::ArticleController.update(Article,Profile)"
    ),
    ResolutionCase(
        "overload_symbols",
        "profileFavorited",
        "partial",
        "::ArticleService.profileFavorited(Profile)",
    ),
    # --- deprecated_symbols: unique-resolution partials ---
    ResolutionCase(
        "deprecated_symbols",
        "LegacyService.process(int)",
        "partial",
        "::LegacyService.process(int)",
    ),
    ResolutionCase(
        "deprecated_symbols",
        "FullyDeprecatedService.run(String)",
        "partial",
        "::FullyDeprecatedService.run(String)",
    ),
    # --- transparency: multi-match overloads ---
    ResolutionCase(
        "transparency",
        "save",
        "overload",
        "::ArticleService.save(Article,boolean)",
        ("::ArticleService.save(Article,boolean)", "::ArticleService.save(Article)"),
    ),
    ResolutionCase(
        "transparency",
        "ArticleService.save",
        "overload",
        "::ArticleService.save(Article,boolean)",
        ("::ArticleService.save(Article,boolean)", "::ArticleService.save(Article)"),
    ),
    # --- overload_symbols: multi-match overloads ---
    ResolutionCase(
        "overload_symbols",
        "generateToken",
        "overload",
        "generateToken(Map<String, Object>,String)",
        ("generateToken(Map<String, Object>,String)", "generateToken(String)"),
    ),
    ResolutionCase(
        "overload_symbols",
        "ArticleService.save",
        "overload",
        "::ArticleService.save(Article,Profile,List<Tag>)",
        (
            "::ArticleService.save(Article,Profile,List<Tag>)",
            "::ArticleService.save(Article)",
        ),
    ),
    ResolutionCase(
        "overload_symbols",
        "save",
        "overload",
        "service/ArticleService.java::ArticleService.save(Article,Profile,List<Tag>)",
        (
            "service/ArticleService.java::ArticleService.save(Article,Profile,List<Tag>)",
            "web/ArticleController.java::ArticleController.save(Article,Profile,List<Tag>)",
            "repository/ArticleRepository.java::ArticleRepository.save(Article)",
            "service/ArticleService.java::ArticleService.save(Article)",
        ),
    ),
    # --- deprecated_symbols: multi-match overloads ---
    ResolutionCase(
        "deprecated_symbols",
        "LegacyService.process",
        "overload",
        "::LegacyService.process(int)",
        ("::LegacyService.process(int)", "::LegacyService.process(String)"),
    ),
    ResolutionCase(
        "deprecated_symbols",
        "FullyDeprecatedService.run",
        "overload",
        "::FullyDeprecatedService.run(String)",
        ("::FullyDeprecatedService.run(String)", "::FullyDeprecatedService.run(int)"),
    ),
    ResolutionCase(
        "deprecated_symbols",
        "process",
        "overload",
        "::LegacyService.process(int)",
        ("::LegacyService.process(int)", "::LegacyService.process(String)"),
    ),
    ResolutionCase(
        "deprecated_symbols",
        "run",
        "overload",
        "::FullyDeprecatedService.run(String)",
        ("::FullyDeprecatedService.run(String)", "::FullyDeprecatedService.run(int)"),
    ),
)
