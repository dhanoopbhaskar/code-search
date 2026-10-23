"""Config/DDL scent detection for type-aware ranking adjustments.

Detects whether a user query signals configuration or schema (DDL) intent
and returns boost/deprioritization parameters applied during ranking.
"""

from __future__ import annotations

import re
from typing import Any

_CONFIG_KEYWORDS: frozenset[str] = frozenset(
    {
        "config",
        "configuration",
        "connection",
        "pool",
        "timeout",
        "setting",
        "settings",
        "port",
        "server",
        "database",
        "datasource",
        "property",
        "properties",
        "yaml",
        "yml",
        "toml",
        "json",
        "env",
        "secret",
        "credential",
        "key",
        "url",
        "mysql",
        "mariadb",
        "postgres",
        "postgresql",
    }
)

# Tokens too generic to establish configuration intent on their own. They only
# count alongside a config-shaped noun phrase or another independent token, so
# a code query that happens to mention a ``key`` or ``secret`` is not hijacked.
_GENERIC_CONFIG_TOKENS: frozenset[str] = frozenset(
    {"key", "secret", "connection", "setting", "settings", "property", "properties"}
)

# Config-shaped nouns that establish intent without a second token.
_CONFIG_NOUN_TOKENS: frozenset[str] = frozenset(
    {
        "config",
        "configuration",
        "datasource",
        "properties",
        "yaml",
        "yml",
        "toml",
        "port",
        "url",
        "postgres",
        "postgresql",
        "mysql",
        "mariadb",
        "mongodb",
        "redis",
        "jdbc",
    }
)

_CONFIG_PHRASES: tuple[str, ...] = ("connection pool", "config file", "configuration file")

# Code vocabulary that suppresses a weak, token-only configuration signal.
_CODE_CONTEXT_TOKENS: frozenset[str] = frozenset(
    {
        "array",
        "algorithm",
        "buffer",
        "class",
        "controller",
        "file",
        "function",
        "handler",
        "list",
        "map",
        "method",
        "object",
        "service",
        "string",
        "token",
    }
)

_CONFIG_FILE_RE = re.compile(
    r"\b(?:application|bootstrap|config|settings)[\w.-]*\.(?:properties|ya?ml|toml)\b|"
    r"\b[\w-]+\.(?:properties|ya?ml|toml)\b"
)

_DDL_KEYWORDS: frozenset[str] = frozenset(
    {
        "schema",
        "schemas",
        "table",
        "tables",
        "column",
        "columns",
        "ddl",
        "alter",
        "constraint",
        "migration",
        "migrations",
        "flyway",
        "seed",
    }
)

# Multi-word DDL phrases matched verbatim in the query.
_DDL_PHRASES: tuple[str, ...] = ("create table", "add column", "alter table", "schema version")

# Filenames/patterns deprioritized when a config/DDL scent is active (build
# metadata that competes with the real config answer).
_CONFIG_DEPRIORITIZE = frozenset(
    {"package-lock.json", "pom.xml", "maven-wrapper.properties", "build.gradle"}
)
_DDL_DEPRIORITIZE = frozenset({"package-lock.json", "pom.xml", "maven-wrapper.properties"})


def _query_tokens(query: str) -> set[str]:
    """Return the lowercased identifier-like tokens of *query*."""
    return set(re.findall(r"[a-zA-Z][a-zA-Z0-9_]*", query.lower()))


def compute_scent_adjustment(
    file_role: str,  # noqa: ARG001  (contract API)
    file_extension: str,
    scent_type: str,
    boost_factor: float,
) -> float:
    """Compute the multiplicative ranking adjustment for a file under a scent.

    Type-aware ranking: under a config/DDL scent, files
    that match the boost patterns (``.properties``/``.sql``/
    ``docker-compose.yml``) are lifted by ``boost_factor`` while build-metadata
    files (``pom.xml``/``package-lock.json``/``maven-wrapper.properties``) get
    a relative deprioritization (a strictly positive multiplier, so strong
    evidence keeps them reachable).

    Args:
        file_role: The classified role (code/config/infra/resource/docs).
        file_extension: The file extension (``.properties``) or bare filename
            (``pom.xml``).
        scent_type: ``config``, ``ddl``, or ``neutral``.
        boost_factor: The configured boost factor ([0.0, 2.0]).

    Returns:
        A multiplier to apply to the file's weighted score; ``1.0`` means no
        adjustment.
    """
    if scent_type not in ("config", "ddl"):
        return 1.0
    lowered = (file_extension or "").lower()
    deprioritize = _CONFIG_DEPRIORITIZE if scent_type == "config" else _DDL_DEPRIORITIZE
    if lowered in deprioritize:
        return 0.5
    if scent_type == "config":
        boost_match = (
            lowered.endswith(".properties")
            or lowered.endswith(".sql")
            or (lowered == "docker-compose.yml")
        )
    else:
        boost_match = lowered.endswith(".sql") or lowered == "docker-compose.yml"
    return max(boost_factor, 1.0) if boost_match else 1.0


def detect_config_ddl_scent(query: str) -> dict[str, Any]:
    """Detect config/DDL scent in a query.

    Args:
        query: The full user query string.

    Returns:
        dict with keys: has_scent (bool), scent_type (enum),
        boost_factor (float), deprioritize_patterns (set),
        boost_patterns (set)
    """
    q = query.lower()
    tokens = _query_tokens(query)

    explicit_config = "--content config" in q
    config_tokens = tokens & _CONFIG_KEYWORDS
    non_generic_config = config_tokens - _GENERIC_CONFIG_TOKENS
    noun_phrase = (
        bool(tokens & _CONFIG_NOUN_TOKENS)
        or any(phrase in q for phrase in _CONFIG_PHRASES)
        or bool(_CONFIG_FILE_RE.search(q))
    )
    code_context = bool(tokens & _CODE_CONTEXT_TOKENS)
    # A noun phrase (or an explicit flag/file name) is sufficient. Bare tokens
    # need at least two independent config words, at least one of them
    # non-generic, and no code vocabulary that suggests the query is about
    # code rather than configuration.
    has_config_scent = (
        explicit_config
        or noun_phrase
        or (len(config_tokens) >= 2 and bool(non_generic_config) and not code_context)
    )
    has_ddl_scent = (
        "--content ddl" in q
        or any(phrase in q for phrase in _DDL_PHRASES)
        or bool(tokens & _DDL_KEYWORDS)
    )

    _config_phrase = explicit_config
    _ddl_phrase = "--content ddl" in q

    if _config_phrase or (has_config_scent and not has_ddl_scent):
        scent_type = "config"
    elif has_ddl_scent or _ddl_phrase:
        scent_type = "ddl"
    else:
        scent_type = "neutral"

    if scent_type == "neutral":
        has_scent = False
        boost_factor = 1.0
        deprioritize_patterns: set[str] = set()
        boost_patterns: set[str] = set()
    elif scent_type == "config":
        has_scent = True
        boost_factor = 1.5
        deprioritize_patterns = {"package-lock.json", "pom.xml", "maven-wrapper.properties"}
        boost_patterns = {".properties", ".sql", "docker-compose.yml"}
    else:
        has_scent = True
        boost_factor = 1.8
        deprioritize_patterns = {"package-lock.json", "pom.xml"}
        boost_patterns = {".sql", "docker-compose.yml"}

    return {
        "has_scent": has_scent,
        "scent_type": scent_type,
        "boost_factor": boost_factor,
        "deprioritize_patterns": deprioritize_patterns,
        "boost_patterns": boost_patterns,
    }
