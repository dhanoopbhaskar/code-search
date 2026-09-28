"""File-class classification shared by the ranking passes.

Every consumer that adjusts a chunk by the shape of its containing file
resolves the file into one of the :class:`PathClass` members here, so the
classification vocabulary and the DB-backed barrel decision live in exactly one
place instead of diverging per dispatch site.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from pathlib import Path
from typing import Any

from src.engine.config import _is_dts_file, _is_non_canonical, _is_test_file

logger = logging.getLogger(__name__)

# Pure re-export surfaces count as barrels only under these filenames; the
# index-backed "zero definition chunks" check (performed in :class:`PathClass`)
# then decides whether the file actually re-exports rather than defines.
_BARREL_NAMES = frozenset({"__init__.py", "package-info.java"})


class FileRole(StrEnum):
    """The file-role classification used by behavior/definition reranking.

    ``MODEL``/``DTO``/``ASSEMBLER``/``EXCEPTION`` cover data-flow plumbing
    files demoted under behavior-intent queries; ``INFRA`` covers deployment
    and container files demoted under code-language queries; ``CONFIG`` covers
    configuration and schema files boosted for config/DDL-scent queries;
    ``RESOURCE`` covers non-code data files (XML/JSON/YAML/TOML/...);
    ``DOCS`` covers prose chunks (content_type ``docs``); ``ANALYSIS``
    covers repo-local report/analysis artifacts demoted below shipped content.
    ``CODE`` is the default for everything else.
    """

    CODE = "code"
    MODEL = "model"
    DTO = "dto"
    ASSEMBLER = "assembler"
    EXCEPTION = "exception"
    INFRA = "infra"
    CONFIG = "config"
    RESOURCE = "resource"
    DOCS = "docs"
    ANALYSIS = "analysis"


# Infra filename signals take precedence over the resource extension so
# ``docker-compose.yml`` classifies as infra, not resource.
_INFRA_NAME_PREFIXES = ("docker", "dockerfile", "docker-compose", "k8s", "compose")
_INFRA_NAME_TAILS = ("dockerfile", "makefile")
_INFRA_SEGMENTS = frozenset(
    {"deploy", "deployment", "infra", "infrastructure", "k8s", "kubernetes"}
)

# Source-code extensions. A path segment like ``infra``/``deploy`` only
# classifies a file as infra when it is not source code (a Dockerfile next to
# ``k8s`` manifests, not a Java adapter living in an ``infra`` package).
_CODE_EXTENSIONS = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".go",
        ".h",
        ".hpp",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".kts",
        ".m",
        ".mm",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".scala",
        ".swift",
        ".ts",
        ".tsx",
    }
)

# Data-flow plumbing segments: a package directory or filename sub-word
# carrying one of these classifies the file as model/dto/assembler/exception.
_MODEL_SEGMENTS = frozenset({"model", "entity", "entities", "models"})
_DTO_SEGMENTS = frozenset({"dto", "dtos", "vo", "viewmodel", "request", "response"})
_ASSEMBLER_SEGMENTS = frozenset({"assembler", "assemblers", "mapper", "mappers", "converter"})
_EXCEPTION_SEGMENTS = frozenset({"exception", "exceptions", "error", "errors"})

# Report/analysis artifact path segments: repo-local
# analysis/report files tagged ``FileRole.ANALYSIS`` and demoted below shipped
# content. The configurable ``CODE_SEARCH_ANALYSIS_ARTIFACT_PATHS`` escape
# hatch extends this built-in set at the call site.
_ANALYSIS_SEGMENTS = frozenset({"reports", "analysis", "benchmarks"})


class ContentType(StrEnum):
    """The content axis of an indexed chunk.

    ``CODE`` is language-parseable source; ``CONFIG`` is configuration and
    resource data (properties/YAML/TOML/JSON/XML/``.conf``/``.gradle``/
    env-style); ``DOCS`` is prose (markdown/``.rst``/``.txt``). The enum is
    shared by the indexer (stamping at index time), the query-time ranking
    weight lookup, and the content-type filter, so every consumer agrees on
    one vocabulary.
    """

    CODE = "code"
    CONFIG = "config"
    DOCS = "docs"


# Config-file extensions. ``.sql`` reclassifies to config so schema/migration
# chunks route through the config content filter, config-scent boost, and
# config-inject pass.
_CONFIG_EXTENSIONS = frozenset(
    {
        ".properties",
        ".yml",
        ".yaml",
        ".toml",
        ".json",
        ".xml",
        ".sql",
        ".conf",
        ".cfg",
        ".ini",
        ".env",
        ".gradle",
    }
)

# Prose/doc-file extensions.
_DOCS_EXTENSIONS = frozenset({".md", ".markdown", ".rst", ".txt", ".adoc"})


def content_type(file_path: str | Path) -> ContentType:
    """Classify *file_path* into its content axis: code, config, or docs.

    Config extensions and env-style filenames classify as ``config`` regardless
    of how the file was parsed (AST or raw-text fallback); docs extensions
    classify as ``docs``; everything else defaults to ``code``. A file whose
    extension is ambiguous is classified by its dominant convention — the
    extension vocabulary above is the single source of truth, shared by the
    indexer and any query-time re-check.

    Args:
        file_path: The stored file path of the chunk's containing file.

    Returns:
        The resolved :class:`ContentType`.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()
    name = path.name.lower()
    if suffix in _DOCS_EXTENSIONS:
        return ContentType.DOCS
    if suffix in _CONFIG_EXTENSIONS:
        return ContentType.CONFIG
    if name.startswith(".env") or name == "environment":
        return ContentType.CONFIG
    return ContentType.CODE


def file_role(file_path: str | Path, analysis_paths: set[str] | None = None) -> FileRole:
    """Resolve *file_path*'s role from path and filename signals alone.

    The filename is checked first for infra signals, then each path segment's
    decomposed sub-words are matched against the plumbing vocabularies. The
    role is a pure path-shape signal — no database access — so it stays cheap
    for every candidate chunk.

    ``content_type`` takes precedence over path-shape rules: a prose file
    (``content_type == "docs"``) always resolves ``DOCS`` so ``file_role`` and
    ``content_type`` agree and a filter on either field drops prose.
    Repo-local report/analysis files (a path segment in ``reports``,
    ``analysis``, ``benchmarks``, or the caller-supplied *analysis_paths*
    extension set) resolve ``ANALYSIS`` — a within-docs and within-code
    demotion signal.

    Args:
        file_path: The stored file path of the candidate chunk.
        analysis_paths: Optional extension of the built-in analysis artifact
            path-segment set (``CODE_SEARCH_ANALYSIS_ARTIFACT_PATHS``); when
            ``None``, only the built-in conventions apply.

    Returns:
        The resolved :class:`FileRole`.
    """
    path = Path(file_path)
    name = path.name.lower()
    stem = path.stem.lower()
    parts = list(path.parts)
    analysis = set(_ANALYSIS_SEGMENTS) | set(analysis_paths or ())
    # Repo-local report/analysis artifacts resolve ``ANALYSIS`` before the
    # content-type branch so a report ``.md`` inside a configured artifact
    # directory is demoted within the docs pool too (never outranking real
    # docs). The convention is directory-based: only a path *segment* in a
    # configured artifact directory tags the file, so a stray ``analysis.md``
    # at the repo root keeps its content-type role (inclusion).
    if any(segment in analysis for segment in parts):
        return FileRole.ANALYSIS
    if content_type(path) is ContentType.DOCS:
        return FileRole.DOCS
    if name.startswith(_INFRA_NAME_PREFIXES) or stem.endswith(_INFRA_NAME_TAILS):
        return FileRole.INFRA
    # Shell scripts are repo tooling (``wait-for-it.sh``, ``deploy.sh``), not
    # canonical source — they are demoted for code queries but stay reachable
    # when their content carries the answer (relative re-ranking).
    if path.suffix.lower() == ".sh":
        return FileRole.INFRA
    if path.suffix.lower() not in _CODE_EXTENSIONS:
        for segment in parts:
            if segment in _INFRA_SEGMENTS:
                return FileRole.INFRA
    # Known build/tooling filenames that are always infra regardless of extension
    _infra_filenames = frozenset(
        {
            "package-lock.json",
            "pom.xml",
            "maven-wrapper.properties",
            "docker-compose.yml",
        }
    )
    if name in _infra_filenames:
        return FileRole.INFRA

    words: set[str] = set()
    for segment in (stem, *parts):
        words.update(_segment_words(segment))
    if words & _MODEL_SEGMENTS:
        return FileRole.MODEL
    if words & _DTO_SEGMENTS:
        return FileRole.DTO
    if words & _ASSEMBLER_SEGMENTS:
        return FileRole.ASSEMBLER
    if words & _EXCEPTION_SEGMENTS:
        return FileRole.EXCEPTION
    if path.suffix.lower() in {
        ".xml",
        ".sql",
        ".properties",
        ".gradle",
        ".yml",
        ".yaml",
        ".json",
        ".toml",
    }:
        return FileRole.CONFIG
    return FileRole.CODE


def _segment_words(segment: str) -> set[str]:
    """Decompose a single path segment into lowercased sub-words."""
    import re

    return {w for w in re.split(r"[._\-]+", segment) if w}


class PathClass(StrEnum):
    """The single representation of a file's rank-relevant classification.

    Members order the demotion severity; ``TEST`` and ``NON_CANONICAL`` are
    pure path-shape signals while ``DTS`` and ``BARREL`` additionally consult
    the index. ``CANONICAL`` is the default for everything else.
    """

    CANONICAL = "canonical"
    TEST = "test"
    NON_CANONICAL = "non_canonical"
    DTS = "dts"
    BARREL = "barrel"

    @classmethod
    def of(cls, db: Any, file_path: str | Path) -> PathClass:
        """Classify *file_path* into a :class:`PathClass` member.

        Test-root and non-canonical path shapes resolve without any database
        access; the TypeScript declaration check is a filename predicate; the
        barrel check queries the index for definition chunks and raises when
        the database is unavailable rather than silently demoting or passing
        the file through undemoted.

        Args:
            db: A database exposing ``connect()`` over ``code_chunks``.
            file_path: The stored file path of the candidate chunk.

        Returns:
            The resolved :class:`PathClass` for *file_path*.
        """
        if _is_test_file(file_path):
            return cls.TEST
        if _is_non_canonical(file_path):
            return cls.NON_CANONICAL
        if _is_dts_file(file_path):
            return cls.DTS
        if cls.is_barrel(db, file_path):
            return cls.BARREL
        return cls.CANONICAL

    @classmethod
    def is_barrel(cls, db: Any, file_path: str | Path) -> bool:
        """Return whether *file_path* is a pure re-export barrel surface.

        ``__init__.py`` and ``package-info.java`` count as barrels only when
        the index holds zero definition chunks for them. A database failure
        raises so the caller surfaces the error instead of silently treating
        the file either as a barrel or as canonical.

        Args:
            db: A database exposing ``connect()`` over ``code_chunks``.
            file_path: The stored file path of the candidate chunk.

        Returns:
            True when the file is a pure re-export barrel.

        Raises:
            RuntimeError: When the definition-count lookup cannot run.
        """
        path = Path(file_path)
        if path.name not in _BARREL_NAMES:
            return False
        try:
            with db.connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM code_chunks "
                    "WHERE file_path = ? AND is_definition = 1;",
                    (str(file_path),),
                ).fetchone()
        except Exception as exc:
            logger.error("Barrel classification failed for %s: %s", file_path, exc)
            raise RuntimeError(f"Barrel classification failed for {file_path}: {exc}") from exc
        return (row["n"] if row else 0) == 0
