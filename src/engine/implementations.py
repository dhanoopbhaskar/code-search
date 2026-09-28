"""Interface implementation lookup — the ONE shared resolution/traversal rule.

:func:`find_implementations` resolves a reference to an interface (or type)
member, walks the ``INHERITS`` graph backwards to every static subtype, matches
the member by name and normalized signature, and classifies the result into one
of four honest outcomes (``resolved`` | ``ambiguous`` | ``not_found`` |
``no_static_implementation``). Every retrieval surface (MCP tool, CLI command,
daemon action, and the ``implements`` traversal direction) delegates here, so
candidates, classification, and ordering cannot diverge.

The rule performs no I/O beyond the two stores and attaches no
freshness/audit concerns; surfaces add transport only.
"""

from __future__ import annotations

from typing import Any

from src.engine.config import Settings
from src.engine.graph import EdgeStore
from src.engine.symbols import SymbolStore

OUTCOME_RESOLVED = "resolved"
OUTCOME_AMBIGUOUS = "ambiguous"
OUTCOME_NOT_FOUND = "not_found"
OUTCOME_NO_STATIC = "no_static_implementation"

# Symbol kinds that can declare a member (a method/function reference resolves
# to the parent type rather than the member itself).
_METHOD_KINDS = {"method", "function", "constructor"}
_TYPE_KINDS = {"class", "interface", "enum", "type_alias"}

# Languages whose inheritance/implementation clauses the indexer captures. A
# declaring type in any other language yields an honest "may be uncaptured"
# note rather than a false assertion that no implementer exists.
_INHERITANCE_LANGUAGES = {
    "python",
    "java",
    "typescript",
    "javascript",
    "c_sharp",
    "cpp",
    "kotlin",
    "ruby",
}


def find_implementations(
    symbol_store: SymbolStore,
    edge_store: EdgeStore,
    reference: str,
    max_depth: int | None = None,
) -> dict[str, Any]:
    """Return the static implementations of an interface member or type.

    Args:
        symbol_store: The symbol store used to resolve the reference and read
            member declarations.
        edge_store: The edge store used for the reverse (subtype) and forward
            (ancestor) ``INHERITS`` walks.
        reference: An FQN, conventional FQN, partial, or bare member name.
        max_depth: Optional reverse-traversal bound; defaults to
            ``Settings.max_graph_depth`` so indirect (sub-interface)
            implementations are reached like every other surface.

    Returns:
        The shared ``ImplementationResult`` envelope: ``outcome``, ``symbol``,
        ``declaring_type``, ``implementations``, ``candidates``, and
        ``explanation``.
    """
    if max_depth is None:
        max_depth = Settings.from_env().max_graph_depth

    envelope = symbol_store.resolve_name(reference)
    if envelope.get("kind") == "ambiguous":
        return _envelope(OUTCOME_AMBIGUOUS, candidates=envelope.get("candidates", []))
    symbol = envelope.get("symbol")
    if symbol is None:
        return _envelope(OUTCOME_NOT_FOUND, candidates=envelope.get("candidates", []))

    declaring, language, query_type = _declaring_type(symbol_store, symbol)
    if declaring is None:
        return _envelope(OUTCOME_NOT_FOUND, symbol=_symbol_summary(symbol))

    subtypes = edge_store.get_subtypes(declaring["id"], max_depth=max_depth)
    implementations = (
        _type_implementations(subtypes)
        if query_type == "type"
        else _member_implementations(
            symbol_store, edge_store, symbol, subtypes, max_depth, declaring["id"]
        )
    )
    implementations.sort(key=_implementation_sort_key)

    if implementations:
        return _envelope(
            OUTCOME_RESOLVED,
            symbol=_symbol_summary(symbol),
            declaring=declaring,
            implementations=implementations,
        )
    return _envelope(
        OUTCOME_NO_STATIC,
        symbol=_symbol_summary(symbol),
        declaring=declaring,
        explanation=_no_static_explanation(declaring, language),
    )


def _declaring_type(
    symbol_store: SymbolStore, symbol: dict[str, Any]
) -> tuple[dict[str, Any] | None, str, str]:
    """Return ``(declaring_type, language, query_type)`` for a resolved symbol.

    A method/function reference resolves to its enclosing type (when that
    parent is a type); a type reference resolves to itself.
    """
    parent_id = symbol.get("parent_symbol_id")
    if parent_id and symbol.get("kind") in _METHOD_KINDS:
        parent = symbol_store.get_by_id(parent_id)
        if parent is not None and parent.get("kind") in _TYPE_KINDS:
            return _type_summary(parent), parent.get("language") or "", "method"
    return _type_summary(symbol), symbol.get("language") or "", "type"


def _type_implementations(subtypes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one site-less implementation entry per static subtype."""
    return [_implementation(subtype, None) for subtype in subtypes]


def _member_implementations(
    symbol_store: SymbolStore,
    edge_store: EdgeStore,
    symbol: dict[str, Any],
    subtypes: list[dict[str, Any]],
    max_depth: int,
    declaring_id: int,
) -> list[dict[str, Any]]:
    """Return the subtypes that provide the queried member, direct or inherited.

    A subtype that neither declares the member nor inherits it from a
    *different* type is not an implementer. The queried declaring type is
    excluded from the ancestor walk so a subtype is never reported as
    implementing the member by inheriting it from the very declaration being
    queried.
    """
    name = symbol.get("name")
    if not name:
        return []
    query_sig = symbol.get("signature")

    # Batch the declared-method lookup so an interface with many implementers
    # does not issue one query per subtype.
    declared = symbol_store.methods_of_many([st["id"] for st in subtypes], name)
    implementations: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for subtype in subtypes:
        match = _select_member(declared.get(subtype["id"], []), query_sig)
        if match is not None:
            row, match_kind = match
            site = _site(row, subtype["fqn"], inherited=False, match=match_kind)
            implementations.append(_implementation(subtype, site))
        else:
            pending.append(subtype)

    if not pending:
        return implementations

    # Only subtypes without a declared method need an ancestor walk; batch the
    # ancestor method lookup as well.
    ancestor_map = {st["id"]: edge_store.get_ancestors(st["id"], max_depth) for st in pending}
    ancestor_ids = sorted({a["id"] for ancestors in ancestor_map.values() for a in ancestors})
    ancestor_methods = symbol_store.methods_of_many(ancestor_ids, name)
    for subtype in pending:
        for ancestor in ancestor_map[subtype["id"]]:
            if ancestor["id"] == declaring_id:
                continue
            match = _select_member(ancestor_methods.get(ancestor["id"], []), query_sig)
            if match is not None:
                row, match_kind = match
                site = _site(row, ancestor["fqn"], inherited=True, match=match_kind)
                implementations.append(_implementation(subtype, site))
                break
    return implementations


def _select_member(
    rows: list[dict[str, Any]], query_sig: dict[str, Any] | None
) -> tuple[dict[str, Any], str] | None:
    """Return the best matching declaration among *rows*, or ``None``.

    A signature-consistent declaration is preferred over a name-only fallback;
    ties resolve to the lowest symbol id so the selection is deterministic.
    """
    scored: list[tuple[int, int, str, dict[str, Any]]] = []
    for row in rows:
        match_kind = _match_kind(query_sig, row.get("signature"))
        if match_kind is None:
            continue
        scored.append((0 if match_kind == "signature" else 1, row.get("id") or 0, match_kind, row))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]))
    _rank, _symbol_id, match_kind, row = scored[0]
    return row, match_kind


def _match_kind(
    query_sig: dict[str, Any] | None, candidate_sig: dict[str, Any] | None
) -> str | None:
    """Classify a candidate match as ``signature`` / ``name_only`` / no match.

    When both sides expose a signature it must agree (arity and normalized
    parameter types); a mismatch is not a match at all, so a same-named method
    with a different signature is never attributed. When either side lacks a
    signature the match is name-only and is labelled as such.
    """
    if query_sig and candidate_sig:
        same = query_sig.get("arity") == candidate_sig.get("arity") and query_sig.get(
            "normalized"
        ) == candidate_sig.get("normalized")
        return "signature" if same else None
    return "name_only"


def _symbol_summary(symbol: dict[str, Any]) -> dict[str, Any]:
    """Compact identity/location summary of the resolved declaration."""
    return {
        "fqn": symbol.get("fqn"),
        "name": symbol.get("name"),
        "kind": symbol.get("kind"),
        "file_path": symbol.get("file_path"),
        "line_start": symbol.get("line_start"),
        "line_end": symbol.get("line_end"),
        "signature": symbol.get("signature"),
    }


def _type_summary(row: dict[str, Any]) -> dict[str, Any]:
    """Compact identity/location summary of a declaring or implementing type."""
    return {
        "id": row.get("id"),
        "fqn": row.get("fqn"),
        "name": row.get("name"),
        "kind": row.get("kind"),
        "file_path": row.get("file_path"),
        "line_start": row.get("line_start"),
        "line_end": row.get("line_end"),
    }


def _site(
    row: dict[str, Any],
    declaring_type_fqn: str | None,
    *,
    inherited: bool,
    match: str,
) -> dict[str, Any]:
    """Shape the implementation site (the declaration that provides the member)."""
    return {
        "fqn": row.get("fqn"),
        "name": row.get("name"),
        "kind": row.get("kind"),
        "file_path": row.get("file_path"),
        "line_start": row.get("line_start"),
        "line_end": row.get("line_end"),
        "declaring_type_fqn": declaring_type_fqn,
        "signature": row.get("signature"),
        "inherited": inherited,
        "match": match,
    }


def _implementation(subtype: dict[str, Any], site: dict[str, Any] | None) -> dict[str, Any]:
    """Group an implementing type with its site and relationship."""
    relationship = "direct" if subtype.get("depth") == 1 else "indirect"
    return {
        "type": {
            **_type_summary(subtype),
            "relationship": relationship,
            "depth": subtype.get("depth"),
            "path": subtype.get("path") or [],
        },
        "site": site,
        "relationship": relationship,
    }


def _implementation_sort_key(implementation: dict[str, Any]) -> tuple[Any, ...]:
    """Documented total order: direct, declared, kind, FQN, id."""
    site = implementation.get("site") or {}
    type_row = implementation.get("type") or {}
    return (
        0 if implementation.get("relationship") == "direct" else 1,
        1 if site.get("inherited") else 0,
        type_row.get("kind") or "",
        type_row.get("fqn") or "",
        type_row.get("id") or 0,
    )


def _no_static_explanation(declaring: dict[str, Any], language: str) -> str:
    """Return the honest no-static explanation for *declaring*.

    A proxy-capable declaring type (``kind == "interface"``) states that a
    runtime-generated implementation may exist; any other kind states that no
    statically-known implementing type was found. When the declaring language's
    inheritance clauses are not captured, the explanation notes the
    relationships may be uncaptured rather than asserting none exist.
    """
    if declaring.get("kind") == "interface":
        explanation = "No static implementation found; a runtime-generated implementation may exist"
    else:
        explanation = "No statically-known implementing type found"
    if language and language not in _INHERITANCE_LANGUAGES:
        explanation += f" (inheritance relationships may be uncaptured for {language})"
    return explanation


def _envelope(
    outcome: str,
    *,
    symbol: dict[str, Any] | None = None,
    declaring: dict[str, Any] | None = None,
    implementations: list[dict[str, Any]] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    explanation: str | None = None,
) -> dict[str, Any]:
    """Shape the shared implementation envelope."""
    return {
        "outcome": outcome,
        "symbol": symbol,
        "declaring_type": declaring,
        "implementations": implementations or [],
        "candidates": candidates or [],
        "explanation": explanation,
    }
