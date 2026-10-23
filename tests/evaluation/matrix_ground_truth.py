"""Repository matrix and labelled queries for the cross-repository evaluation.

The matrix mirrors the repository types in the improvement spec so a ranking
change is judged on several languages and layouts instead of a single corpus.
Each entry points at a hermetic fixture under ``tests/fixtures/`` (or an
optional external checkout) and declares the languages it exercises. Entries
whose fixtures are added by a later phase are marked ``pending`` and skipped.

Every query carries a category from :data:`CATEGORIES`. Positive queries name
the acceptable result files and optional graded alternatives; negative queries
name no result and record whether the engine abstained or returned weak
results. The harness in ``matrix_eval.py`` consumes these labels.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Query categories required by the evaluation matrix.
CATEGORIES = (
    "exact_symbol",
    "nl_implementation",
    "documentation",
    "configuration",
    "test_shaped",
    "behavior_with_test",
    "negative",
    "caller_graph",
)


@dataclass(frozen=True)
class MatrixRepo:
    """One repository in the evaluation matrix.

    Attributes:
        id: Stable identifier used to join queries to the repository.
        label: Human-readable description of the repository type.
        fixture: Fixture directory under ``tests/fixtures/``; ``None`` when the
            entry is pending or supplied as an external checkout.
        languages: Languages the entry is expected to exercise.
        tier: ``core``, ``optional``, ``resource``, ``unsupported``, or
            ``pending``.
        pending: When true the fixture does not exist yet and the harness
            skips the entry.
        notes: Provenance or coverage note echoed into the report.
    """

    id: str
    label: str
    fixture: str | None
    languages: tuple[str, ...]
    tier: str = "core"
    pending: bool = False
    notes: str = ""


@dataclass(frozen=True)
class MatrixQuery:
    """One labelled query evaluated against a matrix repository.

    Attributes:
        repo_id: The :class:`MatrixRepo` this query belongs to.
        query: Query text submitted to the search surface.
        category: One of :data:`CATEGORIES`.
        expected_files: Path fragments that satisfy the query.
        expected_fqn: Optional symbol name that must also appear.
        grades: Optional ``(path fragment, gain)`` pairs for graded NDCG.
            When empty, the first expected file gets gain 2 and the remaining
            expected files get gain 1.
        content_scope: Optional content scope passed to ``search``.
        expect_weak: True for negative queries; a weak or empty response is
            the correct outcome.
        top_k: Rank ceiling for the primary expected result.
        notes: Optional rationale echoed into the per-query record.
    """

    repo_id: str
    query: str
    category: str
    expected_files: tuple[str, ...] = ()
    expected_fqn: str | None = None
    grades: tuple[tuple[str, int], ...] = ()
    content_scope: str | None = None
    expect_weak: bool = False
    top_k: int = 3
    notes: str = ""


#: Repository entries. Go, Rust, Swift, PHP, and an Angular fixture are added
#: in the language-coverage phase; they stay visible as ``pending`` so the
#: matrix reports the gap instead of silently shrinking.
MATRIX_REPOS: tuple[MatrixRepo, ...] = (
    MatrixRepo(
        id="java-tests",
        label="Java with canonical tests",
        fixture="quality_defects",
        languages=("java",),
        notes="JUnit-style test file plus same-name production symbols",
    ),
    MatrixRepo(
        id="java-docs",
        label="Java with documentation and configuration",
        fixture="relevance",
        languages=("java", "sql", "properties"),
        notes="README, Flyway SQL migration, and application.properties",
    ),
    MatrixRepo(
        id="typescript-react",
        label="TypeScript/React application",
        fixture="tsreact",
        languages=("typescript",),
        notes="TSX components, barrel export, JSON configuration",
    ),
    MatrixRepo(
        id="python",
        label="Python service with a test module",
        fixture="ambiguous_symbols",
        languages=("python",),
        notes="Duplicate method names across production and test modules",
    ),
    MatrixRepo(
        id="kotlin-csharp-cpp",
        label="Kotlin, C#, and C/C++ implementations",
        fixture="implementations",
        languages=("kotlin", "c_sharp", "cpp", "java"),
        notes="Interface/implementation shapes in four compiled languages",
    ),
    MatrixRepo(
        id="mixed-monorepo",
        label="Mixed-language monorepo",
        fixture="semantic_vector_multilang",
        languages=("java", "typescript", "python", "c_sharp", "cpp"),
        notes="Same service concept implemented in five languages plus docs/config",
    ),
    MatrixRepo(
        id="non-git",
        label="Non-Git directory",
        fixture="relevance",
        languages=("java",),
        notes="Fixture copy has no .git directory",
    ),
    MatrixRepo(
        id="unsupported-languages",
        label="Repository with unsupported languages",
        fixture="unsupported_languages",
        languages=(),
        tier="unsupported",
        notes="Scala, Dart, HTML, and Protobuf must be skipped by discovery",
    ),
    MatrixRepo(
        id="go",
        label="Go repository",
        fixture=None,
        languages=("go",),
        tier="pending",
        pending=True,
        notes="Fixture lands with the language-coverage phase",
    ),
    MatrixRepo(
        id="rust",
        label="Rust repository",
        fixture=None,
        languages=("rust",),
        tier="pending",
        pending=True,
        notes="Optional [lang] extra; fixture lands with the language-coverage phase",
    ),
    MatrixRepo(
        id="swift",
        label="Swift repository",
        fixture=None,
        languages=("swift",),
        tier="pending",
        pending=True,
        notes="Optional [lang] extra; fixture lands with the language-coverage phase",
    ),
    MatrixRepo(
        id="php",
        label="PHP repository",
        fixture=None,
        languages=("php",),
        tier="pending",
        pending=True,
        notes="Optional [lang] extra; fixture lands with the language-coverage phase",
    ),
    MatrixRepo(
        id="angular",
        label="TypeScript/Angular application",
        fixture=None,
        languages=("typescript",),
        tier="pending",
        pending=True,
        notes="Angular-specific fixture is deferred; tsreact covers TSX today",
    ),
)


#: Labelled queries grouped by repository. Categories that a fixture cannot
#: answer (for example documentation in a code-only fixture) are omitted
#: rather than labelled with an arbitrary expected file.
MATRIX_QUERIES: tuple[MatrixQuery, ...] = (
    # --- Java with canonical tests ---
    MatrixQuery(
        "java-tests",
        "AuthService",
        "exact_symbol",
        expected_files=("auth/AuthService.java",),
        expected_fqn="AuthService",
        top_k=1,
    ),
    MatrixQuery(
        "java-tests",
        "authenticate a user with a username and password",
        "nl_implementation",
        expected_files=("auth/AuthService.java",),
    ),
    MatrixQuery(
        "java-tests",
        "AuthServiceTest",
        "test_shaped",
        expected_files=("AuthServiceTest.java",),
        top_k=1,
    ),
    MatrixQuery(
        "java-tests",
        "test the login flow for an invalid password",
        "behavior_with_test",
        expected_files=("auth/AuthService.java",),
        notes="Behavior query containing 'test'; it must not relax the test penalty",
    ),
    MatrixQuery(
        "java-tests",
        "sourdough starter hydration schedule",
        "negative",
        expect_weak=True,
    ),
    MatrixQuery(
        "java-tests",
        "who calls authenticate",
        "caller_graph",
        expected_files=("auth/AuthController.java",),
    ),
    # --- Java with documentation and configuration ---
    MatrixQuery(
        "java-docs",
        "ArticleService",
        "exact_symbol",
        expected_files=("article/ArticleService.java",),
        expected_fqn="ArticleService",
        top_k=1,
    ),
    MatrixQuery(
        "java-docs",
        "create a comment on an article",
        "nl_implementation",
        expected_files=("article/ArticleService.java",),
    ),
    MatrixQuery(
        "java-docs",
        "how comments get created",
        "documentation",
        expected_files=("docs/README.md",),
        content_scope="docs",
        top_k=2,
    ),
    MatrixQuery(
        "java-docs",
        "database connection URL",
        "configuration",
        expected_files=("application.properties",),
        expected_fqn=None,
        content_scope="config",
        top_k=2,
    ),
    MatrixQuery(
        "java-docs",
        "test the article deletion flow",
        "behavior_with_test",
        expected_files=("article/ArticleService.java",),
    ),
    MatrixQuery(
        "java-docs",
        "quantum annealing kubernetes operator in Haskell",
        "negative",
        expect_weak=True,
    ),
    MatrixQuery(
        "java-docs",
        "who calls createComment",
        "caller_graph",
        expected_files=("article/ArticleController.java",),
    ),
    # --- TypeScript/React ---
    MatrixQuery(
        "typescript-react",
        "loadViaParam",
        "exact_symbol",
        expected_files=("services/ArticleService.ts",),
        expected_fqn="loadViaParam",
        top_k=1,
    ),
    MatrixQuery(
        "typescript-react",
        "load articles from the API",
        "nl_implementation",
        expected_files=("store/articlesSlice.ts",),
    ),
    MatrixQuery(
        "typescript-react",
        "articles are loaded and rendered",
        "documentation",
        expected_files=("README.md",),
        content_scope="docs",
        top_k=2,
    ),
    MatrixQuery(
        "typescript-react",
        "path alias for source imports",
        "configuration",
        expected_files=("tsconfig.json",),
        content_scope="config",
        top_k=2,
    ),
    MatrixQuery(
        "typescript-react",
        "test the article loading flow",
        "behavior_with_test",
        expected_files=("store/articlesSlice.ts",),
    ),
    MatrixQuery(
        "typescript-react",
        "sourdough starter hydration schedule",
        "negative",
        expect_weak=True,
    ),
    MatrixQuery(
        "typescript-react",
        "who calls loadArticles",
        "caller_graph",
        expected_files=("features/ArticleList.tsx",),
    ),
    # --- Python with a test module ---
    MatrixQuery(
        "python",
        "ArticleService.getBySlug",
        "exact_symbol",
        expected_files=("service.py",),
        expected_fqn="ArticleService.getBySlug",
        top_k=1,
    ),
    MatrixQuery(
        "python",
        "register a new user account",
        "nl_implementation",
        expected_files=("service.py",),
    ),
    MatrixQuery(
        "python",
        "TestViews",
        "test_shaped",
        expected_files=("test_views.py",),
        top_k=1,
    ),
    MatrixQuery(
        "python",
        "test the article service save behavior",
        "behavior_with_test",
        expected_files=("service.py",),
    ),
    MatrixQuery(
        "python",
        "sourdough starter hydration schedule",
        "negative",
        expect_weak=True,
    ),
    MatrixQuery(
        "python",
        "who calls getBySlug",
        "caller_graph",
        expected_files=("controller.py",),
    ),
    # --- Kotlin, C#, and C/C++ ---
    MatrixQuery(
        "kotlin-csharp-cpp",
        "CalculatorImpl",
        "exact_symbol",
        expected_files=("java/Shapes.java",),
        expected_fqn="CalculatorImpl",
        top_k=1,
    ),
    MatrixQuery(
        "kotlin-csharp-cpp",
        "Kotlin class implementing the Animal interface",
        "nl_implementation",
        expected_files=("kotlin/Shapes.kt",),
    ),
    MatrixQuery(
        "kotlin-csharp-cpp",
        "C# class implementing the Animal interface",
        "nl_implementation",
        expected_files=("csharp/Shapes.cs",),
    ),
    MatrixQuery(
        "kotlin-csharp-cpp",
        "C++ class overriding virtual speak",
        "nl_implementation",
        expected_files=("cpp/shapes.cpp",),
    ),
    MatrixQuery(
        "kotlin-csharp-cpp",
        "sourdough starter hydration schedule",
        "negative",
        expect_weak=True,
    ),
    # --- Mixed-language monorepo ---
    MatrixQuery(
        "mixed-monorepo",
        "OrderService",
        "exact_symbol",
        expected_files=("OrderService.java",),
        grades=(
            ("OrderService.java", 2),
            ("OrderService.ts", 1),
            ("OrderService.cs", 1),
            ("service.py", 1),
        ),
        top_k=3,
    ),
    MatrixQuery(
        "mixed-monorepo",
        "persist and retrieve orders for the storefront",
        "nl_implementation",
        expected_files=("OrderService.java",),
        grades=(("OrderService.java", 2), ("OrderService.ts", 1), ("service.py", 1)),
    ),
    MatrixQuery(
        "mixed-monorepo",
        "Order Service Guide",
        "documentation",
        expected_files=("docs/README.md",),
        content_scope="docs",
        top_k=2,
    ),
    MatrixQuery(
        "mixed-monorepo",
        "database connection for orders",
        "configuration",
        expected_files=("application.properties",),
        content_scope="config",
        top_k=2,
    ),
    MatrixQuery(
        "mixed-monorepo",
        "test order persistence",
        "behavior_with_test",
        expected_files=("OrderService.java",),
        grades=(("OrderService.java", 2), ("service.py", 1)),
    ),
    MatrixQuery(
        "mixed-monorepo",
        "sourdough starter hydration schedule",
        "negative",
        expect_weak=True,
    ),
    # --- Non-Git directory ---
    MatrixQuery(
        "non-git",
        "ArticleService",
        "exact_symbol",
        expected_files=("article/ArticleService.java",),
        expected_fqn="ArticleService",
        top_k=1,
    ),
    MatrixQuery(
        "non-git",
        "create a comment on an article",
        "nl_implementation",
        expected_files=("article/ArticleService.java",),
    ),
    MatrixQuery(
        "non-git",
        "test the article deletion flow",
        "behavior_with_test",
        expected_files=("article/ArticleService.java",),
    ),
    MatrixQuery(
        "non-git",
        "sourdough starter hydration schedule",
        "negative",
        expect_weak=True,
    ),
)


def repos() -> tuple[MatrixRepo, ...]:
    """Return every matrix repository entry."""
    return MATRIX_REPOS


def active_repos() -> tuple[MatrixRepo, ...]:
    """Return the entries whose fixtures exist and are not pending."""
    return tuple(repo for repo in MATRIX_REPOS if not repo.pending and repo.fixture)


def queries_for(repo_id: str) -> tuple[MatrixQuery, ...]:
    """Return the labelled queries for *repo_id*."""
    return tuple(query for query in MATRIX_QUERIES if query.repo_id == repo_id)
