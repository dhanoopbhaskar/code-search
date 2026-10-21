"""Lexical query content-intent classification and scope signal text.

Classifies a user query into documentation, configuration, or neutral intent
using only the query text, then builds the surface-neutral message attached to a
search response when scope behaviour occurs. Classification is pure and
deterministic for a given query string and performs no I/O, no corpus scan, and
no network access, so it stays air-gap safe and deterministic.
"""

from __future__ import annotations

import re
from enum import StrEnum

from code_search.engine.scent_detection import detect_config_ddl_scent

__all__ = [
    "ContentIntent",
    "build_scope_signal",
    "classify_content_intent",
    "scope_override",
]


class ContentIntent(StrEnum):
    """The content axis a query asks about."""

    DOCS = "docs"
    CONFIG = "config"
    CODE = "code"
    NEUTRAL = "neutral"


# Documentation-shaped vocabulary. Matched as whole identifier-like tokens so a
# symbol name that merely contains one of these words ("guide_factory") does not
# trigger documentation intent.
_DOCS_KEYWORDS: frozenset[str] = frozenset(
    {
        "readme",
        "documentation",
        "docs",
        "doc",
        "guide",
        "guides",
        "tutorial",
        "tutorials",
        "manual",
        "handbook",
        "runbook",
        "changelog",
        "faq",
        "document",
        "documents",
        "introduction",
        "overview",
        "walkthrough",
        "deployment",
        "deploy",
        "installation",
        "install",
        "setup",
        "operations",
        "wiki",
        "markdown",
        "prose",
        "release",
        "releases",
    }
)

# Multi-word documentation phrases matched verbatim in the lowercased query.
_DOCS_PHRASES: tuple[str, ...] = (
    "how to",
    "how do i",
    "getting started",
    "release notes",
)

# Code-shaped vocabulary. These tokens describe source-level constructs rather
# than prose or configuration, so a query containing one is asking about code
# even when it also reads like a natural-language phrase.
_CODE_KEYWORDS: frozenset[str] = frozenset(
    {
        "annotation",
        "argument",
        "async",
        "await",
        "callback",
        "callee",
        "caller",
        "class",
        "code",
        "compile",
        "constructor",
        "controller",
        "decorator",
        "def",
        "endpoint",
        "enum",
        "exception",
        "extends",
        "fn",
        "func",
        "function",
        "implements",
        "import",
        "interface",
        "method",
        "module",
        "parameter",
        "return",
        "returns",
        "runtime",
        "source",
        "struct",
        "syntax",
        "throw",
        "variable",
    }
)

# Nouns that name a source-level construct rather than a prose topic. A
# multi-word query using one of these ("login handler", "user login handler")
# is asking about code even when the other words are ordinary terms.
_CODE_CONSTRUCT_NOUNS: frozenset[str] = frozenset(
    {
        "adapter",
        "adapters",
        "bean",
        "beans",
        "component",
        "components",
        "dao",
        "dto",
        "entity",
        "entities",
        "factory",
        "gateway",
        "handler",
        "handlers",
        "interceptor",
        "listener",
        "mapper",
        "mappers",
        "middleware",
        "repository",
        "repositories",
        "resolver",
        "scheduler",
        "serializer",
        "service",
        "services",
        "validator",
        "worker",
    }
)

# Source-file extensions and identifier shapes that mark a query as
# code-shaped (``ArticleService.save``, ``login_handler``, ``User``).
_SOURCE_EXTENSION_RE = re.compile(
    r"\.(?:py|pyi|java|kt|kts|ts|tsx|js|jsx|mjs|cjs|go|rs|rb|swift|php|cs|cpp|cc|c|h|hpp)$",
    re.IGNORECASE,
)
_DOTTED_NAME_RE = re.compile(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b")

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_]*")

# The scope that forces inclusion of each intent's content type.
_OVERRIDE_BY_INTENT: dict[ContentIntent, str] = {
    ContentIntent.DOCS: "all",
    ContentIntent.CONFIG: "config",
}


def classify_content_intent(query: str) -> ContentIntent:
    """Classify *query* into documentation, configuration, code, or neutral intent.

    Precedence is documentation, then configuration, then code, then neutral,
    so a query that mixes signals resolves to a single predictable intent.
    Configuration intent delegates to the shared
    :func:`detect_config_ddl_scent` detector so the config/DDL vocabulary keeps
    one source of truth. Code intent is lexical: code vocabulary, an
    identifier-shaped token, or a single significant token.

    Args:
        query: The user query text.

    Returns:
        The classified :class:`ContentIntent`.
    """
    lowered = (query or "").lower()
    raw_tokens = [m.group(0) for m in _TOKEN_RE.finditer(query or "")]
    tokens = {token.lower() for token in raw_tokens}
    if tokens & _DOCS_KEYWORDS or any(phrase in lowered for phrase in _DOCS_PHRASES):
        return ContentIntent.DOCS
    if detect_config_ddl_scent(lowered)["has_scent"]:
        return ContentIntent.CONFIG
    if _is_code_shaped(raw_tokens, query):
        return ContentIntent.CODE
    return ContentIntent.NEUTRAL


def _is_code_shaped(raw_tokens: list[str], query: str) -> bool:
    """Return whether *query* is a fuzzy source-level search.

    A single lowercase token (``login``), code vocabulary (``function``,
    ``controller``), a code construct noun (``login handler``), a snake_case
    identifier (``login_handler``), or a source-file extension marks the query
    as code-shaped. Exact symbol-shaped
    queries (``AuthService``, ``ArticleService.save``) are excluded: their
    exact-match boost already outranks configuration, and keeping them on the
    broader default preserves symbol-query behaviour. Documentation and
    configuration signals are classified before this helper runs, so their
    vocabulary never reaches it.
    """
    if not raw_tokens:
        return False
    if _is_exact_symbol_query(query):
        return False
    if len(raw_tokens) == 1:
        return True
    lowered = {token.lower() for token in raw_tokens}
    if lowered & (_CODE_KEYWORDS | _CODE_CONSTRUCT_NOUNS):
        return True
    if _SOURCE_EXTENSION_RE.search(query):
        return True
    return any("_" in token or "$" in token for token in raw_tokens)


def _is_exact_symbol_query(query: str) -> bool:
    """Return whether *query* is a bare symbol-shaped identifier.

    A dotted/qualified name or a single token with internal capitals names a
    declaration rather than describing one, so it is not a fuzzy code-shaped
    search.
    """
    stripped = query.strip().strip("`'\"")
    if _DOTTED_NAME_RE.fullmatch(stripped):
        return True
    if re.fullmatch(r"[A-Za-z_]\w*", stripped):
        return any(char.isupper() for char in stripped[1:])
    return False


def scope_override(intent: ContentIntent, effective: str) -> str:
    """Return the neutral scope token that forces inclusion of *intent*'s type.

    Args:
        intent: The classified query intent.
        effective: The effective scope applied to the search.

    Returns:
        ``all`` for documentation intent, ``config`` for configuration intent,
        and the effective scope itself for neutral intent (no override due).
    """
    return _OVERRIDE_BY_INTENT.get(intent, effective)


def build_scope_signal(
    intent: ContentIntent,
    effective: str,
    origin: str,
    suggested: str | None,
) -> str | None:
    """Build the surface-neutral scope message, or ``None`` when none is due.

    The message names the scope in neutral terms (never a command flag) so every
    surface renders the identical text and adds its own override dialect.
    ``None`` is returned whenever the effective scope already includes the
    intent's content type, so a scope that includes configuration never produces
    a contradictory "configuration excluded" message.

    Args:
        intent: The classified query intent.
        effective: The effective scope applied to the search.
        origin: ``explicit``, ``inferred``, or ``default``.
        suggested: The recommended scope when no switch occurred, else ``None``.

    Returns:
        The actionable message, or ``None`` when no message is due.
    """
    if intent in (ContentIntent.CODE, ContentIntent.NEUTRAL):
        return None

    if intent is ContentIntent.DOCS:
        if origin == "inferred":
            return (
                "documentation intent detected; searched with content scope all "
                "inferred from the query; use content scope code_focused to "
                "restrict to code and config"
            )
        if effective in ("docs", "all"):
            return None
        if suggested:
            return (
                f"documentation intent detected; results from content scope "
                f"{effective} are shown; use content scope {suggested} to include "
                f"documentation"
            )
        return (
            f"documentation intent detected; documentation is excluded by content "
            f"scope {effective}; use content scope all to include it"
        )

    # ContentIntent.CONFIG
    if effective in ("code_focused", "config", "all"):
        return None
    return (
        f"configuration intent detected; configuration is excluded by content "
        f"scope {effective}; use content scope config to include it"
    )
