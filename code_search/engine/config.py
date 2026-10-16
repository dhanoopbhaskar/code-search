"""Application configuration and file-classification helpers.

The module has three responsibilities:

* :class:`Settings` — an immutable, env-var-driven configuration dataclass
  covering indexing, search, reranking, trust signals, freshness, graph
  traversal, metrics, and the MCP server. Every field reads a ``CODE_SEARCH_*``
  environment variable at construction time.
* :class:`LanguageConfig` — operator-supplied overrides of the built-in
  language definitions (extensions, grammar modules, chunk node types),
  loaded from a JSON file and merged over the defaults.
* Path-classification helpers — decide whether a file is a test file,
  non-canonical code (examples/legacy/generated/mocks), or a main
  source file, from path segments and filename conventions alone.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_language_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load custom language configuration from a JSON file.

    The JSON file should contain a "languages" list, each entry specifying
    name, extensions, grammar_module, and optional overrides. Falls back to
    the path in CODE_SEARCH_LANGUAGE_CONFIG env var or ``language_config.json``.
    """
    config: dict[str, Any] = {"languages": []}
    if config_path is None:
        config_path = Path(os.environ.get("CODE_SEARCH_LANGUAGE_CONFIG", "language_config.json"))
    if config_path.exists():
        try:
            raw = config_path.read_text()
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "languages" in parsed:
                config = parsed
                logger.info("Loaded language config from %s", config_path)
            else:
                logger.warning("Invalid language config format in %s", config_path)
        except Exception as exc:
            logger.warning("Failed to load language config from %s: %s", config_path, exc)
    return config


class LanguageConfig:
    """Allows users to extend or override the built-in language definitions.

    Reads a JSON config file and merges it with the default language map so
    that custom extensions, grammar modules, or AST chunk node types can be
    injected without modifying source code.
    """

    def __init__(self, config_path: Path | None = None) -> None:
        """Create a language config loaded from *config_path*.

        Args:
            config_path: Path to the JSON language-config file; defaults to the
                path in the ``CODE_SEARCH_LANGUAGE_CONFIG`` env var, then
                ``language_config.json``, when ``None``.
        """
        self._config = load_language_config(config_path)
        self._merged: dict[str, dict[str, Any]] | None = None

    def merge_with_defaults(
        self, default_languages: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Merge built-in language definitions with user-provided overrides."""
        if self._merged is not None:
            return self._merged
        merged = dict(default_languages)
        for lang_entry in self._config.get("languages", []):
            name = lang_entry.get("name", "")
            if not name:
                continue
            if name in merged:
                merged[name].update(lang_entry)
            else:
                merged[name] = lang_entry
        self._merged = merged
        return merged

    def get_supported_languages(self) -> set[str]:
        """Return the names of all languages after merging with defaults.

        Returns an empty set when :meth:`merge_with_defaults` has not been
        called yet.
        """
        if self._merged is None:
            return set()
        return set(self._merged.keys())

    def get_language_config(self, name: str) -> dict[str, Any] | None:
        """Return the merged configuration dict for *name*.

        Args:
            name: Language name as it appears in the defaults or the config
                file's ``languages`` list.

        Returns:
            The merged per-language dict, or ``None`` when the language is
            unknown or :meth:`merge_with_defaults` has not been called.
        """
        if self._merged is None:
            return None
        return self._merged.get(name)

    def get_extensions_map(self) -> dict[str, str]:
        """Return a mapping of file extension (leading dot) to language name.

        Combines the ``extensions`` lists of every merged language into a
        single lookup table. Returns an empty dict when
        :meth:`merge_with_defaults` has not been called.
        """
        result: dict[str, str] = {}
        if self._merged is None:
            return result
        for name, cfg in self._merged.items():
            for ext in cfg.get("extensions", []):
                result[ext] = name
        return result


# A file is a test ONLY under a recognised test root or a test filename
# convention. A bare ``spec``/``test`` segment in the middle of a
# main-source path is never a test signal.
_TEST_ALWAYS_ROOT_SEGMENTS = frozenset(
    {"__test__", "__tests__", "androidTest", "jvmTest", "integrationTest"}
)
_TEST_ROOT_SEGMENTS = frozenset({"test", "tests", "spec", "specs"})
_MAIN_SOURCE_SEGMENTS = frozenset({"main", "production"})

_TEST_NAME_PREFIXES = ("test_", "spec_")
_TEST_NAME_SUFFIXES = ("_test", "_spec", "_tests", "_specs")
_TEST_NAME_INFIXES = (".test.", ".spec.")
_TEST_CLASS_NAME_TAILS = ("Test", "Tests", "TestCase")
_TEST_CLASS_SUFFIX_EXTENSIONS = frozenset({".java", ".kt", ".swift"})

# Non-canonical code (examples, legacy/compat shims, generated stubs, mocks)
# is down-ranked, never excluded.
_NON_CANONICAL_ROOT_SEGMENTS = frozenset(
    {
        "compat",
        "example",
        "examples",
        "fakes",
        "gen",
        "generated",
        "legacy",
        "mock",
        "mocks",
        "stubs",
        "third_party",
        "vendor",
    }
)
# Package and source-tree segments that indicate a segment is mid-path rather
# than a top-level root (e.g. the ``example`` in ``com.example.qualitydefects``).
_SOURCE_TREE_SEGMENTS = frozenset(
    {
        "app",
        "com",
        "dev",
        "io",
        "java",
        "kotlin",
        "main",
        "net",
        "org",
        "production",
        "src",
        "test",
        "tests",
    }
)
_NON_CANONICAL_NAME_PREFIXES = ("fake_", "generated_", "legacy_", "mock_", "stub_")
_NON_CANONICAL_NAME_SUFFIXES = (
    "_example",
    "_fake",
    "_gen",
    "_generated",
    "_legacy",
    "_mock",
    "_stub",
)
_NON_CANONICAL_NAME_INFIXES = (".example.", ".fake.", ".gen.", ".generated.", ".mock.", ".stub.")
_NON_CANONICAL_CLASS_NAME_TAILS = ("Fake", "Generated", "Legacy", "Mock", "Stub")


def _is_test_root(parts: tuple[str, ...], index: int) -> bool:
    """Return whether the path segment at *index* is a recognised test root."""
    part = parts[index]
    if part in _TEST_ALWAYS_ROOT_SEGMENTS:
        return True
    if part == "test" and index > 0 and parts[index - 1] == "src":
        return True
    if part not in _TEST_ROOT_SEGMENTS:
        return False
    return not any(earlier in _MAIN_SOURCE_SEGMENTS for earlier in parts[:index])


def _is_non_canonical_root(parts: tuple[str, ...], index: int) -> bool:
    """Return whether the path segment at *index* is a non-canonical root.

    Package segments such as ``com.example.qualitydefects`` must not be
    mistaken for an ``examples/`` tree, so a root only counts when it does not
    sit under a source tree or main-source package path.
    """
    part = parts[index]
    if part not in _NON_CANONICAL_ROOT_SEGMENTS:
        return False
    return not any(earlier in _SOURCE_TREE_SEGMENTS for earlier in parts[:index])


def _matches_test_filename(path: Path) -> bool:
    """Return whether *path*'s filename alone signals a test file .

    A filename is a test signal when its stem starts with ``test_``/``spec_``,
    ends with ``_test``/``_spec``/``_tests``/``_specs``, contains a
    ``.test.``/``.spec.`` infix, or — for class-based languages such as Java,
    Kotlin and Swift — its class name ends in ``Test``/``Tests``/``TestCase``.
    """
    stem = path.stem.lower()
    if stem.startswith(_TEST_NAME_PREFIXES) or stem.endswith(_TEST_NAME_SUFFIXES):
        return True
    if any(infix in path.name.lower() for infix in _TEST_NAME_INFIXES):
        return True
    if path.suffix in _TEST_CLASS_SUFFIX_EXTENSIONS:
        return path.stem.endswith(_TEST_CLASS_NAME_TAILS)
    return False


def _matches_non_canonical_filename(path: Path) -> bool:
    """Return whether *path*'s filename alone signals non-canonical code.

    A filename is non-canonical when its stem starts with a marker such as
    ``fake_``/``mock_``, ends with a marker such as ``_example``/``_legacy``,
    contains a ``.gen.``/``.mock.`` infix, or — for class-based languages —
    its class name ends in a tail such as ``Fake``/``Generated``/``Mock``.
    """
    stem = path.stem.lower()
    if stem.startswith(_NON_CANONICAL_NAME_PREFIXES) or stem.endswith(_NON_CANONICAL_NAME_SUFFIXES):
        return True
    if any(infix in path.name.lower() for infix in _NON_CANONICAL_NAME_INFIXES):
        return True
    if path.suffix in _TEST_CLASS_SUFFIX_EXTENSIONS:
        return path.stem.endswith(_NON_CANONICAL_CLASS_NAME_TAILS)
    return False


def _is_test_file(file_path: str | Path) -> bool:
    """Check if a file path belongs to a recognised test root or test filename."""
    path = Path(file_path)
    if _matches_test_filename(path):
        return True
    parts = path.parts
    return any(_is_test_root(parts, index) for index in range(len(parts)))


def _is_non_canonical(file_path: str | Path) -> bool:
    """Check if a file is non-canonical code (examples/legacy/generated/mocks).

    Non-canonical files are down-ranked by the reranker but never excluded.
    """
    path = Path(file_path)
    if _matches_non_canonical_filename(path):
        return True
    parts = path.parts
    return any(_is_non_canonical_root(parts, index) for index in range(len(parts)))


def _is_dts_file(file_path: str | Path) -> bool:
    """Return whether *path* is a TypeScript declaration file (``*.d.ts``).

    ``Path("foo.d.ts").suffix`` is ``.ts`` (the ``.d`` is part of the stem),
    so the check matches the full ``.d.ts`` name suffix. Type-declaration
    files are demoted but never excluded.
    """
    return Path(file_path).name.lower().endswith(".d.ts")


# Multiplicative path penalties stay strictly positive so a
# demoted file remains reachable; this is the floor they clamp to.
_MIN_PENALTY = 1e-6


@dataclass(frozen=True)
class Settings:
    """Immutable, environment-driven application configuration.

    Every field resolves its value from a ``CODE_SEARCH_*`` environment
    variable the first time the class is used (via a ``default_factory``) and
    is immutable afterwards. Construct an instance with :meth:`from_env` for
    pure defaults, :meth:`with_context_dir` when the CLI passes an explicit
    context directory, or a plain dataclass call when a caller wants to
    override individual fields.

    The field groups (core paths, embedding model, search weights, trust
    signals, indexing, watcher, metrics, MCP server, display) mirror the
    functional areas of the engine; each group is documented with an inline
    comment above its fields.
    """

    # --- Core paths ---
    context_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("CODE_SEARCH_CONTEXT_DIR", ".context"))
    )
    log_level: str = field(
        default_factory=lambda: os.environ.get("CODE_SEARCH_LOG_LEVEL", "WARNING")
    )

    # --- Embedding model ---
    embedding_model: str = field(
        default_factory=lambda: os.environ.get("CODE_SEARCH_EMBEDDING_MODEL", "potion-code-16m-32d")
    )
    embedding_dim: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_EMBEDDING_DIM", "32"))
    )
    # Explicit model profile. ``default`` keeps the unchanged model above; the
    # opt-in ``fast`` profile resolves to a separate local model, which produces
    # incompatible vectors and therefore requires a re-index when switched.
    model_profile: str = field(
        default_factory=lambda: os.environ.get("CODE_SEARCH_MODEL_PROFILE", "default")
    )
    fast_embedding_model: str = field(
        default_factory=lambda: os.environ.get("CODE_SEARCH_FAST_EMBEDDING_MODEL", "potion-base-2M")
    )
    fast_embedding_dim: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_FAST_EMBEDDING_DIM", "64"))
    )

    # --- Embedding representation budget ---
    # Maximum characters of the chunk representation (enclosing-context prefix
    # plus chunk content) passed to the semantic model. Enrichment is truncated
    # deterministically to this budget, keeping the chunk's own declaration and
    # body ahead of the optional context.
    embed_text_max_chars: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_EMBED_TEXT_MAX_CHARS", "2000"))
    )

    # --- Relevance threshold ---
    relevance_threshold: float = field(
        default_factory=lambda: max(
            0.0,
            min(1.0, float(os.environ.get("CODE_SEARCH_RELEVANCE_THRESHOLD", "0.05"))),
        )
    )
    # Ranked relevance floor: the top fused score must reach this value or
    # ranked mode returns the honest no-match envelope instead of a fake top-10
    # Aligned with the ``relevance_threshold`` default so a
    # score exactly at the floor uses the low-confidence tier, never no-match.
    ranked_score_floor: float = field(
        default_factory=lambda: max(
            0.0,
            min(1.0, float(os.environ.get("CODE_SEARCH_RANKED_SCORE_FLOOR", "0.05"))),
        )
    )

    # --- Data directory ---
    data_dir: str | None = field(
        default_factory=lambda: os.environ.get("CODE_SEARCH_DATA_DIR") or None
    )

    # --- Model path override ---
    model_path: str | None = field(
        default_factory=lambda: os.environ.get("CODE_SEARCH_MODEL_PATH") or None
    )

    # --- Resource extensions allowlist ---
    resource_extensions: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            ext.strip()
            for ext in os.environ.get(
                "CODE_SEARCH_RESOURCE_EXTENSIONS",
                ".xml,.sql,.properties,.gradle,.yml,.yaml,.json,.toml",
            ).split(",")
            if ext.strip()
        )
    )

    # --- Index content control ---
    index_prose: bool = field(
        default_factory=lambda: (
            os.environ.get("CODE_SEARCH_INDEX_PROSE", "true").lower() in ("true", "1", "yes")
        )
    )

    # --- Content-type classification ---
    # The content axis of an indexed chunk (code|config|docs). Weights are
    # constant-time multipliers applied in ranked fusion; a config-scent query
    # lifts config chunks, an active code-language context demotes
    # config/docs chunks.
    config_content_boost: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_CONFIG_CONTENT_BOOST", "1.35"))
    )
    config_inject_boost: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_CONFIG_INJECT_BOOST", "0.75"))
    )
    config_inject_primary_extra: float = field(
        default_factory=lambda: float(
            os.environ.get("CODE_SEARCH_CONFIG_INJECT_PRIMARY_EXTRA", "0.3")
        )
    )
    docs_content_boost: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_DOCS_CONTENT_BOOST", "1.2"))
    )
    non_code_language_demote: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_NON_CODE_LANGUAGE_DEMOTE", "0.7"))
    )
    config_scent_words: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            word.strip()
            for word in os.environ.get(
                "CODE_SEARCH_CONFIG_SCENT_WORDS",
                "config,configuration,connection,pool,timeout,setting,settings,port,"
                "database,datasource,property,properties,yaml,yml,toml,json,env,"
                "secret,credential,key",
            ).split(",")
            if word.strip()
        )
    )
    # Exhaustive matching mode: ``all_tokens`` (default) requires every query
    # token in each matching line; ``any_token`` retains the old OR semantics
    # but is always labelled as such.
    exhaustive_matching_mode: str = field(
        default_factory=lambda: os.environ.get("CODE_SEARCH_EXHAUSTIVE_MATCHING_MODE", "all_tokens")
    )
    # Borderline filter: when on, low-confidence-band results are dropped from
    # ranked responses instead of being tagged.
    borderline_filter: bool = field(
        default_factory=lambda: (
            os.environ.get("CODE_SEARCH_BORDERLINE_FILTER", "false").lower() in ("true", "1", "yes")
        )
    )
    # Find-related file exclusion: when on (default), the anchor chunk's own
    # file is excluded from neighbors; when off, same-file chunks are
    # down-weighted so cross-file neighbors always outrank them.
    find_related_exclude_file: bool = field(
        default_factory=lambda: (
            os.environ.get("CODE_SEARCH_FIND_RELATED_EXCLUDE_FILE", "true").lower()
            in ("true", "1", "yes")
        )
    )
    find_related_same_file_penalty: float = field(
        default_factory=lambda: float(
            os.environ.get("CODE_SEARCH_FIND_RELATED_SAME_FILE_PENALTY", "0.5")
        )
    )
    # Unresolved-callee capture: when on, callee references that do not resolve
    # to an indexed definition are persisted as ``resolved: false`` edges
    # carrying their raw text instead of being dropped.
    capture_unresolved_callees: bool = field(
        default_factory=lambda: (
            os.environ.get("CODE_SEARCH_CAPTURE_UNRESOLVED_CALLEES", "true").lower()
            in ("true", "1", "yes")
        )
    )
    # On-topic scaffold tokens: a query naming the generic construct itself
    # ("exception", "dto", "model", "bean") lifts the scaffolding demotion so
    # on-topic scaffolding still ranks.
    scaffold_topic_words: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            word.strip()
            for word in os.environ.get(
                "CODE_SEARCH_SCAFFOLD_TOPIC_WORDS",
                "exception,exceptions,dto,dtos,model,models,bean,beans,mapper,assembler,converter",
            ).split(",")
            if word.strip()
        )
    )

    # --- BM25 / search ---
    min_vector_cosine: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_MIN_VECTOR_COSINE", "0.25"))
    )
    bm25_k1: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_BM25_K1", "1.5"))
    )
    bm25_b: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_BM25_B", "0.75"))
    )
    bm25_content_weight: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_BM25_CONTENT_WEIGHT", "1.0"))
    )
    bm25_subwords_weight: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_BM25_SUBWORDS_WEIGHT", "0.6"))
    )
    bm25_fqn_weight: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_BM25_FQN_WEIGHT", "0.5"))
    )
    bm25_path_weight: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_BM25_PATH_WEIGHT", "0.2"))
    )
    bm25_rules_weight: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_BM25_RULES_WEIGHT", "0.4"))
    )
    rrf_k: int = field(default_factory=lambda: int(os.environ.get("CODE_SEARCH_RRF_K", "60")))
    max_results: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_MAX_RESULTS", "50"))
    )
    search_top_k_multiplier: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_TOP_K_MULTIPLIER", "2"))
    )
    search_candidate_pool_min: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_CANDIDATE_POOL_MIN", "40"))
    )
    filter_stopwords: bool = field(
        default_factory=lambda: (
            os.environ.get("CODE_SEARCH_FILTER_STOPWORDS", "false").lower() in ("true", "1", "yes")
        )
    )

    # --- Query-quality gate  ---
    relevance_gate: bool = field(
        default_factory=lambda: (
            os.environ.get("CODE_SEARCH_RELEVANCE_GATE", "true").lower() in ("true", "1", "yes")
        )
    )
    idf_floor: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_IDF_FLOOR", "0.8"))
    )
    informative_tokens_min: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_INFORMATIVE_TOKENS_MIN", "1"))
    )
    concept_signal_min: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_CONCEPT_SIGNAL_MIN", "2"))
    )
    vector_only_cosine_floor: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_VECTOR_ONLY_COSINE_FLOOR", "0.5"))
    )

    # --- Trust signals ---
    exact_token_coverage_min: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_EXACT_TOKEN_COVERAGE_MIN", "0.5"))
    )
    top_vector_floor: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_TOP_VECTOR_FLOOR", "0.5"))
    )
    expansion_file: str = field(
        default_factory=lambda: os.environ.get("CODE_SEARCH_EXPANSION_FILE", "")
    )
    exact_match_boost: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_EXACT_MATCH_BOOST", "0.5"))
    )
    language_scope_mode: str = field(
        default_factory=lambda: os.environ.get("CODE_SEARCH_LANGUAGE_SCOPE_MODE", "demote")
    )
    language_scope_penalty: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_LANGUAGE_SCOPE_PENALTY", "0.5"))
    )

    # --- Rank-class weights ---
    resource_deboost: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_RESOURCE_DEBOOST", "0.35"))
    )
    boilerplate_deboost: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_BOILERPLATE_DEBOOST", "0.65"))
    )
    min_lift: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_MIN_LIFT", "0.05"))
    )
    resource_intent_words: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            word.strip()
            for word in os.environ.get(
                "CODE_SEARCH_RESOURCE_INTENT_WORDS",
                "sql,migration,ddl,config,xml,seed,testdata",
            ).split(",")
            if word.strip()
        )
    )

    # --- Exact pre-check toggle ---
    exact_precheck_tags: str = field(
        default_factory=lambda: os.environ.get("CODE_SEARCH_EXACT_PRECHECK_TAGS", "on")
    )

    # --- Score breakdown flag ---
    score_breakdown: bool = field(
        default_factory=lambda: (
            os.environ.get("CODE_SEARCH_SCORE_BREAKDOWN", "true").lower() in ("true", "1", "yes")
        )
    )
    # Confidence band thresholds: a calibrated score at or above
    # ``confidence_high_floor`` is ``high``; at or above
    # ``confidence_medium_floor`` (but below the high floor) is ``medium``;
    # anything lower is ``low``. Both are clamped to ``[0, 1]`` and the medium
    # floor must stay strictly below the high floor (validated in
    # ``__post_init__``).
    confidence_high_floor: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_CONFIDENCE_HIGH_FLOOR", "0.7"))
    )
    confidence_medium_floor: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_CONFIDENCE_MEDIUM_FLOOR", "0.45"))
    )

    # --- File-level coherence  ---
    coherence_bonus: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_COHERENCE_BONUS", "0.05"))
    )

    # --- Config/DDL scent ---
    config_scent_boost: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_CONFIG_SCENT_BOOST", "1.5"))
    )
    ddl_scent_boost: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_DDL_SCENT_BOOST", "1.8"))
    )

    # --- Symbol suggestions  ---
    suggest_edit_distance: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_SUGGEST_EDIT_DISTANCE", "2"))
    )

    # --- Reranking ---
    definition_boost: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_DEFINITION_BOOST", "1.2"))
    )
    noise_penalty: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_NOISE_PENALTY", "0.5"))
    )
    non_canonical_penalty: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_NON_CANONICAL_PENALTY", "0.25"))
    )

    # --- Session-based personalisation ---
    session_ttl_hours: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_SESSION_TTL_HOURS", "24"))
    )
    decay_constant: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_DECAY_CONSTANT", "0.1"))
    )
    session_write_weight: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_SESSION_WRITE_WEIGHT", "1.0"))
    )
    session_read_weight: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_SESSION_READ_WEIGHT", "0.7"))
    )
    git_timeout: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_GIT_TIMEOUT", "10"))
    )

    # --- Indexing ---
    lock_timeout: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_LOCK_TIMEOUT", "30.0"))
    )
    max_chunk_lines: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_MAX_CHUNK_LINES", "100"))
    )

    # --- File watcher ---
    watch_debounce_seconds: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_WATCH_DEBOUNCE", "1.0"))
    )
    watch_poll_interval: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_WATCH_POLL_INTERVAL", "1.0"))
    )

    # --- Index freshness ---
    # How long a computed freshness signal is cached before the next query
    # recomputes it. ``0`` disables the cache and recomputes on every query.
    freshness_ttl_seconds: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_FRESHNESS_TTL_SECONDS", "5.0"))
    )

    # --- Graph traversal ---
    max_graph_depth: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_MAX_GRAPH_DEPTH", "5"))
    )
    call_graph_limit: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_CALL_GRAPH_LIMIT", "50"))
    )
    max_resolution_candidates: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_MAX_RESOLUTION_CANDIDATES", "10"))
    )

    # --- Metrics ---
    metrics_window_size: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_METRICS_WINDOW_SIZE", "1000"))
    )

    # --- MCP server ---
    find_related_limit: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_FIND_RELATED_LIMIT", "100"))
    )

    # --- Display ---
    query_summary_length: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_QUERY_SUMMARY_LENGTH", "100"))
    )
    snippet_length: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_SNIPPET_LENGTH", "60"))
    )

    # --- Search-quality knobs ---
    chunk_target_chars: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_CHUNK_TARGET_CHARS", "750"))
    )
    chunk_min_chars: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_CHUNK_MIN_CHARS", "50"))
    )
    stem_rescue_boost: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_STEM_RESCUE_BOOST", "1.0"))
    )
    stem_match_boost: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_STEM_MATCH_BOOST", "1.5"))
    )
    alpha_symbol: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_ALPHA_SYMBOL", "0.3"))
    )
    alpha_nl: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_ALPHA_NL", "0.5"))
    )
    stem_min_prefix: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_STEM_MIN_PREFIX", "3"))
    )
    nl_boost_max: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_NL_BOOST_MAX", "1.0"))
    )
    nl_boost_keywords_min: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_NL_BOOST_KEYWORDS_MIN", "2"))
    )
    embedded_symbol_boost: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_EMBEDDED_SYMBOL_BOOST", "0.5"))
    )
    dts_penalty: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_DTS_PENALTY", "0.7"))
    )
    barrel_penalty: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_BARREL_PENALTY", "0.5"))
    )

    # --- Match-boost layer ---
    # Additive, bounded ranking adjustment layered on the fused score when the
    # query exactly names an indexed file, filename stem, symbol, or FQN (or
    # proportionally matches a file stem / parent-directory term). The per-tier
    # weights are multipliers of the current pool maximum; ``match_boost_cap``
    # bounds the total per-chunk boost. ``generic_stems`` dampens ubiquitous
    # file stems so a generic filename match cannot crown every ``config``/
    # ``main``/``index`` file.
    match_boost_enabled: bool = field(
        default_factory=lambda: (
            os.environ.get("CODE_SEARCH_MATCH_BOOST_ENABLED", "true").lower()
            in ("true", "1", "yes")
        )
    )
    match_boost_cap: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_MATCH_BOOST_CAP", "2.0"))
    )
    match_boost_exact_fqn: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_MATCH_BOOST_EXACT_FQN", "2.0"))
    )
    match_boost_exact_symbol: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_MATCH_BOOST_EXACT_SYMBOL", "1.5"))
    )
    match_boost_exact_filename: float = field(
        default_factory=lambda: float(
            os.environ.get("CODE_SEARCH_MATCH_BOOST_EXACT_FILENAME", "1.5")
        )
    )
    match_boost_stem: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_MATCH_BOOST_STEM", "0.5"))
    )
    generic_stems: frozenset[str] = field(
        default_factory=lambda: frozenset(
            word.strip()
            for word in os.environ.get(
                "CODE_SEARCH_MATCH_BOOST_GENERIC_STEMS",
                "main,index,util,utils,config,settings,test,app,base,common,core,data,"
                "model,service,controller,handler,manager,factory,helper,types,constants,init",
            ).split(",")
            if word.strip()
        )
    )

    # --- Query intent scope inference ---
    # When enabled, a documentation-shaped query with no explicit ``content``
    # scope may be re-run under the ``all`` scope if the default scope returns
    # no results, and the response reports the scope decision. Disabling it
    # restores single-pass, pre-inference behaviour.
    intent_scope_enabled: bool = field(
        default_factory=lambda: (
            os.environ.get("CODE_SEARCH_INTENT_SCOPE_ENABLED", "true").lower()
            in ("true", "1", "yes")
        )
    )

    # --- Rescue ladder ---
    # Tiers run below an empty ranked path: T1 relaxes the query-quality gate
    # (fewer informative tokens, no relevance threshold), T2 does a literal
    # case-insensitive substring scan of content/fqn. Each tier has a toggle.
    rescue_t1_enabled: bool = field(
        default_factory=lambda: (
            os.environ.get("CODE_SEARCH_RESCUE_T1_ENABLED", "true").lower() in ("true", "1", "yes")
        )
    )
    rescue_t1_informative_tokens_min: int = field(
        default_factory=lambda: int(
            os.environ.get("CODE_SEARCH_RESCUE_T1_INFORMATIVE_TOKENS_MIN", "1")
        )
    )
    rescue_t1_concept_signal_min: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_RESCUE_T1_CONCEPT_SIGNAL_MIN", "1"))
    )
    rescue_t1_relevance_threshold: float = field(
        default_factory=lambda: float(
            os.environ.get("CODE_SEARCH_RESCUE_T1_RELEVANCE_THRESHOLD", "0.0")
        )
    )
    rescue_literal_enabled: bool = field(
        default_factory=lambda: (
            os.environ.get("CODE_SEARCH_RESCUE_LITERAL_ENABLED", "true").lower()
            in ("true", "1", "yes")
        )
    )

    # --- Definition-owner / model-file reranking ---
    # A definition-intent query ("definition of X", "where is X declared")
    # boosts the owner symbol's definition chunk; a behavior-intent query
    # ("how is X used") penalises model/DTO/assembler/exception plumbing files.
    definition_owner_boost: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_DEFINITION_OWNER_BOOST", "1.5"))
    )
    model_file_penalty: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_MODEL_FILE_PENALTY", "0.6"))
    )
    definition_intent_words: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            word.strip()
            for word in os.environ.get(
                "CODE_SEARCH_DEFINITION_INTENT_WORDS",
                "definition,define,defines,declaration,declare,declares,owner",
            ).split(",")
            if word.strip()
        )
    )
    behavior_intent_words: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            word.strip()
            for word in os.environ.get(
                "CODE_SEARCH_BEHAVIOR_INTENT_WORDS",
                "how,does,what,behavior,use,uses,used,usage,call,calls,invoke,invokes",
            ).split(",")
            if word.strip()
        )
    )

    # --- Declared-rule boost ---
    # Queries that ask for annotated/guarded behavior ("who is allowed to
    # delete a comment") get a boost for chunks whose declared_rules column
    # mentions the queried rule, plus an exact-precheck LIKE arm.
    declared_rule_boost: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_DECLARED_RULE_BOOST", "1.5"))
    )
    declared_rule_intent_words: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            word.strip()
            for word in os.environ.get(
                "CODE_SEARCH_DECLARED_RULE_INTENT_WORDS",
                "annotation,annotated,rule,rules,decorator,decorated,authorize,authorized,"
                "guarded,guard,allowed,permission,own,owns,owner,allowed to",
            ).split(",")
            if word.strip()
        )
    )

    # --- Infra demotion ---
    # A code-language query demotes infra/resource files (Dockerfile,
    # docker-compose, deployment manifests) below code; the relaxed weight
    # applies when no explicit language or inferred language is active.
    infra_deboost: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_INFRA_DEBOOST", "0.35"))
    )
    infra_deboost_relaxed: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_INFRA_DEBOOST_RELAXED", "0.5"))
    )

    # --- Intent vocabularies ---
    # Authorization-intent words detect access-restriction and validation
    # questions ("restrict", "who can", "access control", "permission",
    # "authorize", "validate", "login", "request body") and fire the
    # definition/annotation boost on authorization-relevant code.
    authorization_intent_words: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            word.strip()
            for word in os.environ.get(
                "CODE_SEARCH_AUTHORIZATION_INTENT_WORDS",
                "restrict,restriction,restricted,authorize,authorization,authorized,permission,"
                "permissions,access,control,role,roles,secure,security,guard,guarded,allowed,"
                "ownership,owns,owned,validate,validation,valid,validated,login,authenticate,"
                "authentication,request,body",
            ).split(",")
            if word.strip()
        )
    )
    # DDL-intent words detect table/schema-creation questions ("schema",
    # "create table", "column", "alter", "ddl", "table") and boost config
    # chunks carrying a schema/DDL shape.
    ddl_intent_words: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            word.strip()
            for word in os.environ.get(
                "CODE_SEARCH_DDL_INTENT_WORDS",
                "schema,schemas,table,tables,column,columns,ddl,create table,alter,constraint",
            ).split(",")
            if word.strip()
        )
    )
    # Migration-intent words detect migration questions ("migration", "flyway",
    # "add column", "alter table", "schema version") and boost `.sql` migration
    # chunks.
    migration_intent_words: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            word.strip()
            for word in os.environ.get(
                "CODE_SEARCH_MIGRATION_INTENT_WORDS",
                "migration,migrations,flyway,add column,alter table,schema version,seed,seed data",
            ).split(",")
            if word.strip()
        )
    )
    # Report/analysis artifact path segments (repo-local ``reports/``/
    # ``analysis/`` directories) tagged ``FileRole.ANALYSIS`` and demoted so
    # they never outrank shipped content; ambiguous paths default to their
    # content-type role.
    analysis_artifact_paths: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            segment.strip()
            for segment in os.environ.get(
                "CODE_SEARCH_ANALYSIS_ARTIFACT_PATHS", "reports,analysis,benchmarks"
            ).split(",")
            if segment.strip()
        )
    )
    # Find-related boilerplate exclusion: when on (default), boilerplate-shape
    # neighbors (MODEL/DTO/ASSEMBLER/EXCEPTION) are excluded for a
    # non-boilerplate anchor; when off, they are down-weighted instead.
    find_related_exclude_boilerplate: bool = field(
        default_factory=lambda: (
            os.environ.get("CODE_SEARCH_FIND_RELATED_EXCLUDE_BOILERPLATE", "true").lower()
            in ("true", "1", "yes")
        )
    )

    # --- Find-related semantic relevance ---
    # Defaults tuned against tests/evaluation/find_related_eval.py: the
    # call-graph signal is the most precise functional signal, so it is
    # weighted highest; the semantic blend favors semantic signals over raw
    # vector similarity.
    # Weight for package overlap signal (Jaccard similarity of path segments)
    find_related_weight_package: float = field(
        default_factory=lambda: float(
            os.environ.get("CODE_SEARCH_FIND_RELATED_WEIGHT_PACKAGE", "0.2")
        )
    )
    # Weight for type sharing signal (normalized signature overlap)
    find_related_weight_type: float = field(
        default_factory=lambda: float(os.environ.get("CODE_SEARCH_FIND_RELATED_WEIGHT_TYPE", "0.2"))
    )
    # Weight for call graph proximity signal (inverse shortest path distance)
    find_related_weight_call_graph: float = field(
        default_factory=lambda: float(
            os.environ.get("CODE_SEARCH_FIND_RELATED_WEIGHT_CALL_GRAPH", "0.6")
        )
    )
    # Semantic blend factor (alpha): 0.0 = pure vector, 1.0 = pure semantic
    find_related_semantic_blend: float = field(
        default_factory=lambda: float(
            os.environ.get("CODE_SEARCH_FIND_RELATED_SEMANTIC_BLEND", "0.8")
        )
    )

    # --- Exhaustive mode ---
    # A line-oriented, case-sensitive-per-setting scan of indexed files used
    # to answer exact-count queries ("count @Transactional") with a complete
    # match set instead of a truncated ranking.
    exhaustive_enabled: bool = field(
        default_factory=lambda: (
            os.environ.get("CODE_SEARCH_EXHAUSTIVE_ENABLED", "true").lower() in ("true", "1", "yes")
        )
    )
    exhaustive_max_lines: int = field(
        default_factory=lambda: int(os.environ.get("CODE_SEARCH_EXHAUSTIVE_MAX_LINES", "1000"))
    )
    exhaustive_case_sensitive: bool = field(
        default_factory=lambda: (
            os.environ.get("CODE_SEARCH_EXHAUSTIVE_CASE_SENSITIVE", "true").lower()
            in ("true", "1", "yes")
        )
    )

    # --- Enumerate mode ---
    # "list all controllers" collects the named symbol kind across the index
    # with an honest complete/excluded report instead of a truncated ranking.
    enumerate_enabled: bool = field(
        default_factory=lambda: (
            os.environ.get("CODE_SEARCH_ENUMERATE_ENABLED", "true").lower() in ("true", "1", "yes")
        )
    )
    enumeration_intent_words: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            word.strip()
            for word in os.environ.get(
                "CODE_SEARCH_ENUMERATION_INTENT_WORDS",
                "all,every,list,enumerate,count,which files,how many",
            ).split(",")
            if word.strip()
        )
    )

    def __post_init__(self) -> None:
        """Clamp the env-tunable knobs into their valid ranges.

        Uses ``object.__setattr__`` because the dataclass is frozen; values
        outside a range silently clamp to the nearest bound rather than
        raising. ``relevance_threshold`` and the blending alphas clamp to
        ``[0.0, 1.0]``, the multiplicative penalties to ``(0.0, 1.0]`` (a
        positive floor keeps demoted files reachable), the additive boosts
        stay non-negative, and the chunk/prefix sizes floor at ``1``.
        """
        for name, lower, upper in (
            ("relevance_threshold", 0.0, 1.0),
            ("ranked_score_floor", 0.0, 1.0),
            ("alpha_symbol", 0.0, 1.0),
            ("alpha_nl", 0.0, 1.0),
            ("dts_penalty", _MIN_PENALTY, 1.0),
            ("barrel_penalty", _MIN_PENALTY, 1.0),
            ("stem_rescue_boost", 0.0, float("inf")),
            ("stem_match_boost", 0.0, float("inf")),
            ("nl_boost_max", 0.0, float("inf")),
            ("embedded_symbol_boost", 0.0, float("inf")),
            ("definition_owner_boost", 0.0, float("inf")),
            ("declared_rule_boost", 0.0, float("inf")),
            ("model_file_penalty", _MIN_PENALTY, 1.0),
            ("infra_deboost", _MIN_PENALTY, 1.0),
            ("infra_deboost_relaxed", _MIN_PENALTY, 1.0),
            ("config_content_boost", 0.0, float("inf")),
            ("docs_content_boost", 0.0, float("inf")),
            ("non_code_language_demote", _MIN_PENALTY, 1.0),
            ("find_related_same_file_penalty", _MIN_PENALTY, 1.0),
            ("find_related_weight_package", 0.0, 1.0),
            ("find_related_weight_type", 0.0, 1.0),
            ("find_related_weight_call_graph", 0.0, 1.0),
            ("find_related_semantic_blend", 0.0, 1.0),
            ("confidence_high_floor", 0.0, 1.0),
            ("confidence_medium_floor", 0.0, 1.0),
            ("match_boost_cap", 0.0, float("inf")),
            ("match_boost_exact_fqn", 0.0, float("inf")),
            ("match_boost_exact_symbol", 0.0, float("inf")),
            ("match_boost_exact_filename", 0.0, float("inf")),
            ("match_boost_stem", 0.0, float("inf")),
        ):
            value = getattr(self, name)
            clamped = max(lower, min(upper, value))
            if clamped != value:
                object.__setattr__(self, name, clamped)
        normalized_stems = frozenset(
            str(word).strip().lower() for word in self.generic_stems if str(word).strip()
        )
        if normalized_stems != self.generic_stems:
            object.__setattr__(self, "generic_stems", normalized_stems)
        if self.confidence_medium_floor >= self.confidence_high_floor:
            raise ValueError(
                "confidence_medium_floor must be strictly below confidence_high_floor "
                f"(got {self.confidence_medium_floor} >= {self.confidence_high_floor})"
            )
        target = max(1, self.chunk_target_chars)
        if target != self.chunk_target_chars:
            object.__setattr__(self, "chunk_target_chars", target)
        chunk_min = max(1, self.chunk_min_chars)
        if chunk_min >= target:
            chunk_min = max(1, target - 1)
        if chunk_min != self.chunk_min_chars:
            object.__setattr__(self, "chunk_min_chars", chunk_min)
        if self.stem_min_prefix < 1:
            object.__setattr__(self, "stem_min_prefix", 1)
        if self.nl_boost_keywords_min < 1:
            object.__setattr__(self, "nl_boost_keywords_min", 1)
        for name in (
            "rescue_t1_informative_tokens_min",
            "rescue_t1_concept_signal_min",
            "exhaustive_max_lines",
            "max_resolution_candidates",
            "embed_text_max_chars",
        ):
            value = getattr(self, name)
            if value < 1:
                object.__setattr__(self, name, 1)
        if self.exhaustive_matching_mode not in ("all_tokens", "any_token", "literal"):
            object.__setattr__(self, "exhaustive_matching_mode", "all_tokens")

        # Validate find-related semantic weights sum to 1.0
        weight_sum = (
            self.find_related_weight_package
            + self.find_related_weight_type
            + self.find_related_weight_call_graph
        )
        # Normalize weights to sum to 1.0
        if abs(weight_sum - 1.0) > 1e-6 and weight_sum > 0:
            object.__setattr__(
                self, "find_related_weight_package", self.find_related_weight_package / weight_sum
            )
            object.__setattr__(
                self, "find_related_weight_type", self.find_related_weight_type / weight_sum
            )
            object.__setattr__(
                self,
                "find_related_weight_call_graph",
                self.find_related_weight_call_graph / weight_sum,
            )

    @classmethod
    def from_env(cls) -> Settings:
        """Build ``Settings`` from ``CODE_SEARCH_*`` environment variables.

        Returns:
            A fresh instance with every field resolved from the environment
            (or its built-in default when the variable is unset).
        """
        return cls()

    def resolve_embedding_profile(self) -> tuple[str, int]:
        """Resolve the selected model profile to an ``(embedding_model, dim)`` pair.

        ``default`` keeps the unchanged model; ``fast`` resolves to the
        configured fast pair. The fast pair must be a local model directory
        (air-gap); switching profiles requires a re-index because the persisted
        vectors are model-specific.

        Returns:
            The ``(embedding_model, embedding_dim)`` pair for the active profile.

        Raises:
            ValueError: When ``model_profile`` is not ``default`` or ``fast``.
        """
        if self.model_profile == "default":
            return self.embedding_model, self.embedding_dim
        if self.model_profile == "fast":
            return self.fast_embedding_model, self.fast_embedding_dim
        raise ValueError(
            f"Unknown CODE_SEARCH_MODEL_PROFILE {self.model_profile!r}; "
            "expected 'default' or 'fast'."
        )

    @classmethod
    def with_context_dir(cls, context_dir: Path | None) -> Settings:
        """Build ``Settings`` with an explicit context directory override.

        When *context_dir* is provided and differs from the
        ``CODE_SEARCH_CONTEXT_DIR`` environment variable, a warning is logged
        to note that the CLI value wins.

        Args:
            context_dir: Absolute or relative path to use as the context
                directory, or ``None`` to fall back to environment defaults.

        Returns:
            A new ``Settings`` instance, or plain environment defaults when
            *context_dir* is ``None``.
        """
        if context_dir is None:
            return cls()
        env_dir = os.environ.get("CODE_SEARCH_CONTEXT_DIR")
        if env_dir is not None and str(context_dir) != env_dir:
            logger.warning(
                "CLI --context-dir '%s' overrides CODE_SEARCH_CONTEXT_DIR='%s'",
                context_dir,
                env_dir,
            )
        return cls(context_dir=context_dir)

    def resolve_context_dir(self) -> Path:
        """Return the absolute, created context directory path.

        Creates the configured ``context_dir`` (including parents) when it
        does not exist, then resolves symlinks and ``.``/``..`` segments.

        Returns:
            The canonical absolute path of the context directory.
        """
        path = self.context_dir
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()
