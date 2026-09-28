"""Response service for index-change envelopes and code-scoped config hints.

Handles the "index changed — restart required" envelope display when a query
runs against an index that was rebuilt after the serving process loaded it,
and retains the code-scoped config hint for callers that do not supply the
engine's own scope signal.
"""

from __future__ import annotations

from typing import Any

from src.engine.index_service import IndexChangeDetector, index_mtime
from src.engine.scent_detection import detect_config_ddl_scent
from src.engine.search import DEFAULT_CONTENT_SCOPE


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
    signal is supplied and ``--content code``/``code_focused`` genuinely
    excludes configuration does the helper derive a config hint.

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
    if metadata_store is not None:
        # Source the same lifecycle vocabulary freshness reports, so the
        # top-level field and freshness never disagree.
        index_status = metadata_store.get_index_status()
    else:
        status = detector.metadata.status if detector.metadata else None
        index_status = status.value if status is not None else "unknown"

    final_envelope: str | None = index_envelope if index_envelope else None

    if final_envelope is None and scope_signal is not None:
        # The engine already produced the authoritative, surface-neutral
        # message for the effective scope.
        final_envelope = scope_signal

    # Fallback for direct callers without an engine signal: a genuinely
    # excluding scope (``code``/``code_focused``) with a config/DDL-shaped
    # query names the override. Both scopes now exclude configuration
    # identically, so both emit the same hint.
    if (
        final_envelope is None
        and content_scope in ("code", DEFAULT_CONTENT_SCOPE)
        and query
    ):
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
