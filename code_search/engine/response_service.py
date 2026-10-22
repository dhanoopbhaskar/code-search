"""Response service for index-change envelopes and code-scoped config hints.

Handles the "index changed — restart required" envelope display when a query
runs against an index that was rebuilt after the serving process loaded it,
and retains the code-scoped config hint for callers that do not supply the
engine's own scope signal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from code_search.engine.index_service import IndexChangeDetector, index_mtime
from code_search.engine.scent_detection import detect_config_ddl_scent
from code_search.engine.search import DEFAULT_CONTENT_SCOPE

# Fields an agent needs to locate and judge a hit. Compact mode drops the
# explanatory score breakdown and per-arm scores, which dominate the JSON
# envelope without changing the answer.
_COMPACT_RESULT_FIELDS: tuple[str, ...] = (
    "chunk_id",
    "file_path",
    "line_start",
    "line_end",
    "fqn",
    "language",
    "score",
    "score_normalized",
    "is_definition",
    "is_test_file",
    "content_type",
    "file_role",
    "confidence",
    "confidence_band",
    "below_threshold",
    "borderline",
    "redacted_count",
)

_SIGNATURE_MAX_CHARS = 200


_PATHS_ONLY_FIELDS: tuple[str, ...] = (
    "file_path",
    "line_start",
    "line_end",
    "symbol",
    "confidence_band",
    "is_definition",
    "is_test_file",
)


def _short_fqn(fqn: str | None, file_path: str | None) -> str | None:
    """Return the trailing symbol name of *fqn*, or ``None`` when absent."""
    if not fqn:
        return None
    normalized = fqn.split("(", 1)[0]
    if file_path and normalized.startswith(file_path):
        suffix = normalized[len(file_path) :].lstrip(":/\\")
        if suffix:
            normalized = suffix
    if "::" in normalized:
        normalized = normalized.rsplit("::", 1)[-1]
    elif "." in normalized:
        normalized = normalized.rsplit(".", 1)[-1]
    return normalized or None


def _drop_empty(result: dict[str, Any]) -> dict[str, Any]:
    """Remove ``None``/empty optional fields from a compact result."""
    flags = {"below_threshold", "borderline", "redacted_count"}
    return {
        key: value
        for key, value in result.items()
        if value is not None
        and value != ""
        and value != []
        and value != {}
        and not (key in flags and not value)
    }


def compact_result(
    result: dict[str, Any],
    max_snippet_lines: int = 10,
    paths_only: bool = False,
) -> dict[str, Any]:
    """Return a trimmed, agent-sized version of a search result.

    Rebuilds the result from :data:`_COMPACT_RESULT_FIELDS`, so the score
    breakdown and per-arm scores are dropped. Keeps the identifiers and
    location, at most *max_snippet_lines* of content, and the first non-empty
    line as ``signature``. The original line range is preserved so the caller
    can read the full block if needed.

    Args:
        result: A ranked search result.
        max_snippet_lines: Maximum content lines to keep. ``0`` means no
            content at all (matching the MCP ``max_snippet_lines=0`` contract).
        paths_only: Return only location and classification fields.

    Returns:
        A new result dict; optional empty fields are omitted.
    """
    file_path = result.get("file_path")
    symbol = _short_fqn(result.get("fqn"), file_path)
    base = {key: result.get(key) for key in _COMPACT_RESULT_FIELDS if key in result}
    base["symbol"] = symbol
    # A compact envelope never repeats the full path inside ``fqn``.
    if "fqn" in base:
        base["fqn"] = symbol
    if paths_only:
        return _drop_empty({key: base.get(key) for key in _PATHS_ONLY_FIELDS})
    limit = max(0, max_snippet_lines)
    if limit == 0:
        return _drop_empty(base)
    lines = (result.get("content") or "").splitlines()
    snippet = "\n".join(lines[:limit])
    signature = ""
    for line in lines:
        if line.strip():
            signature = line.strip()
            break
    base["content"] = snippet
    base["signature"] = signature[:_SIGNATURE_MAX_CHARS]
    base["content_truncated"] = len(lines) > limit
    return _drop_empty(base)


def compact_results(
    results: list[dict[str, Any]],
    max_snippet_lines: int = 10,
    paths_only: bool = False,
) -> list[dict[str, Any]]:
    """Apply :func:`compact_result` to every result in *results*."""
    return [compact_result(result, max_snippet_lines, paths_only) for result in results]


def relativize_results(
    results: list[dict[str, Any]],
    root: str | Path | None,
) -> list[dict[str, Any]]:
    """Return results with ``file_path``/``fqn`` relative to the index root.

    Text output has always rendered relative paths; machine-readable output
    should not expose the filesystem layout or differ from it. The stored
    ``fqn`` carries an absolute path prefix, so it is stripped too.

    Args:
        results: Search results (not mutated).
        root: The indexed repository root; ``None`` leaves paths unchanged.

    Returns:
        Copies of the results with portable path spellings.
    """
    if not root:
        return results
    from code_search.engine.graph_query import relative_display

    prefix = str(Path(root).resolve())
    out: list[dict[str, Any]] = []
    for result in results:
        copy = dict(result)
        file_path = copy.get("file_path")
        if file_path:
            copy["file_path"] = relative_display(str(file_path), root)
        fqn = copy.get("fqn")
        if isinstance(fqn, str) and fqn.startswith(prefix):
            copy["fqn"] = fqn[len(prefix) :].lstrip("/\\")
        out.append(copy)
    return out


def build_response(
    results: list[dict[str, Any]],
    query: str,
    detector: IndexChangeDetector,
    content_scope: str = DEFAULT_CONTENT_SCOPE,
    metadata_store: Any = None,
    scope_signal: str | None = None,
) -> dict[str, Any]:
    """Build a search response, checking for the index-change envelope
    and the code-scoped config hint.

    When the index was rebuilt after the serving process loaded it (the
    recorded ``last_indexed_at`` differs from the detector's snapshot), the
    response carries the visible "index changed — restart required" envelope
    so a query is never a silent empty/stale result.

    When ``scope_signal`` is supplied it is used verbatim (the engine computed
    the surface-neutral message for the effective scope). Only when no engine
    signal is supplied and ``--content code`` genuinely excludes configuration
    does the helper derive a config hint — a code-focused scope includes
    configuration, so it must not claim configuration is excluded.

    Args:
        results: Raw search results from the query.
        query: The user query string.
        detector: Index change detector seeded with the index state the
            serving process loaded.
        content_scope: The content-type scope (code, config, docs, all,
            code_focused).
        metadata_store: The ``IndexMetadataStore`` exposing the current
            ``last_indexed_at``; when ``None`` the change check is skipped.
        scope_signal: The engine's surface-neutral scope message, or ``None``.

    Returns:
        dict with keys:
        - ``results``: The search results.
        - ``envelope``: Index-change envelope or scope message, or None.
        - ``index_status``: Current index status.
        - ``index_changed``: Whether the index changed since the process
          loaded it.
        - ``reload_required``: Whether a reload is needed.
        - ``silent_empty``: Whether the response hid a silent empty result.
    """
    current_mtime = index_mtime(metadata_store) if metadata_store is not None else None
    change_result = detector.detect_index_change(current_mtime)

    index_envelope = change_result.get("envelope")
    reload_required = change_result.get("should_reload", False)
    status = detector.metadata.status if detector.metadata else None
    index_status = status.value if status is not None else "unknown"

    final_envelope: str | None = index_envelope if index_envelope else None

    if final_envelope is None and scope_signal is not None:
        # The engine already produced the authoritative, surface-neutral
        # message for the effective scope.
        final_envelope = scope_signal

    # Fallback for direct callers without an engine signal: a genuinely
    # excluding scope (``code``) with a config/DDL-shaped query names the
    # override. A code-focused scope includes configuration, so it never emits
    # the "configuration excluded" hint.
    if final_envelope is None and content_scope == "code" and query:
        scent_result = detect_config_ddl_scent(query)
        if scent_result["has_scent"] and scent_result["scent_type"] in ("config", "ddl"):
            hint_patterns = {
                "config": (
                    "config content excluded by code scope; use --content config to include"
                ),
                "ddl": ("DDL content excluded by code scope; use --content config to include"),
            }
            final_envelope = hint_patterns[scent_result["scent_type"]]

    return {
        "results": results,
        "envelope": final_envelope,
        "index_status": index_status,
        "index_changed": bool(index_envelope),
        "reload_required": reload_required,
        "silent_empty": False,
    }
