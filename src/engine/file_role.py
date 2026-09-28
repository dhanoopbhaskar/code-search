"""File role classification for ranking adjustments.

Defines the ``file_role`` enum and classification rules that drive
ranking adjustments in the fused path.

The ``file_role`` of a chunk determines its relative priority:
``infra`` files are deprioritized for code queries, ``config`` files
are boosted for config/DDL-scent queries, and ``docs`` files are
rank-only.
"""

from __future__ import annotations

from typing import Any

from src.engine.classification import FileRole
from src.engine.classification import file_role as classify_file_role_impl

# Root-level tooling filenames that default to ``infra`` role
# Patterns use simple matching: exact filename or *.sh extension
_INFRA_FILENAMES: frozenset[str] = frozenset(
    {
        "package-lock.json",
        "pom.xml",
        "maven-wrapper.properties",
        "docker-compose.yml",
    }
)

# File extensions that default to ``config`` role
_CONFIG_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".properties",
        ".sql",
    }
)

# File extensions that default to ``docs`` role
_DOCS_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".md",
        ".markdown",
        ".rst",
        ".txt",
    }
)


# Evidence-based literal strings that can override the default ``infra``
# classification for tooling files. When one of these literals is found in
# the file content, the file is promoted above the default role.
_INFRA_OVERRIDE_LITERALS: frozenset[str] = frozenset(
    {
        "jdbc:mysql",
        "postgresql://",
        "mongodb://",
        "redis://",
    }
)


def classify_file_role(
    file_path: str,
    content_patterns: list[str] | None = None,  # noqa: ARG001  (contract API)
    literal_evidence: list[str] | None = None,
) -> dict[str, Any]:
    """Classify a file's role for ranking adjustment.

    Delegates to the canonical ``classification.file_role`` implementation
    for the core classification, then adds contract-specific metadata.

    Evidence-based overrides (literal_evidence) can promote ``infra`` files
    when they contain strong on-topic content (e.g. a database connection
    string).

    Args:
        file_path: Absolute path to the file
        content_patterns: Inferred content patterns from AST analysis
        literal_evidence: Literal dependency strings found in the file

    Returns:
        dict with keys:
        - role (FileRole): The classified role
        - evidence_threshold (int): Minimum literal evidence required to override
        - canonical_extensions (set): File extensions considered canonical for this role
        - inferred_extensions (set): File extensions inferred from content patterns
    """
    # Use the canonical classifier from classification.py
    role = classify_file_role_impl(file_path)

    # Evidence-based override: if literal evidence matches, promote infra files
    if literal_evidence and role is FileRole.INFRA:
        for lit in literal_evidence:
            if any(override in lit for override in _INFRA_OVERRIDE_LITERALS):
                role = FileRole.CODE
                break

    evidence_threshold = 1
    canonical_extensions: set[str] = set()
    inferred_extensions: set[str] = set()

    if role is FileRole.CONFIG:
        canonical_extensions = {".properties", ".sql"}
        inferred_extensions = {".yml", ".yaml", ".toml", ".json", ".xml", ".conf", ".ini", ".env"}
    elif role is FileRole.DOCS:
        canonical_extensions = {".md", ".markdown", ".rst", ".txt"}
        inferred_extensions = {".py", ".js", ".ts", ".java", ".cc", ".cpp", ".h", ".rs", ".go"}
    elif role is FileRole.INFRA:
        canonical_extensions = {
            "*.sh",
            "package-lock.json",
            "pom.xml",
            "maven-wrapper.properties",
            "docker-compose.yml",
        }
        inferred_extensions = {".yml", ".yaml", ".toml", ".json", ".xml"}
    elif role in (FileRole.MODEL, FileRole.DTO, FileRole.ASSEMBLER, FileRole.EXCEPTION):
        # Boilerplate roles - treat as code for extension purposes
        canonical_extensions = set()
        inferred_extensions = set()
    elif role is FileRole.RESOURCE:
        canonical_extensions = {".xml", ".json", ".yaml", ".yml", ".toml"}
        inferred_extensions = set()
    elif role is FileRole.ANALYSIS:
        canonical_extensions = {".md", ".html", ".json"}
        inferred_extensions = set()
    else:  # CODE
        canonical_extensions = set()
        inferred_extensions = set()

    return {
        "role": role,
        "evidence_threshold": evidence_threshold,
        "canonical_extensions": canonical_extensions,
        "inferred_extensions": inferred_extensions,
    }
