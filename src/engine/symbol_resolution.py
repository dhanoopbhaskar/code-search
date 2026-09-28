"""Pure symbol-reference parsing, outcome mapping, and candidate ranking policy.

This module holds the deterministic, database-free resolution policy shared by
:meth:`SymbolStore.resolve_name` (envelope assembly) and the graph candidate
query. It imports only :mod:`src.engine.config` (for the test-file predicate)
and never imports ``symbols.py`` or ``graph.py``, so both may import it without
creating the existing ``symbols`` <-> ``graph`` circular import.

Every function here is a pure function of the query text and candidate
metadata: no database access, no network, no wall-clock, and no dependence on
set iteration order. Identical query plus index state therefore yields
byte-for-byte identical candidate content and order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.engine.config import _is_test_file

# --- Resolution outcomes (the three user-visible values) --------------------

OUTCOME_RESOLVED = "resolved"
OUTCOME_AMBIGUOUS = "ambiguous"
OUTCOME_NOT_FOUND = "not_found"

_KIND_TO_OUTCOME: dict[str, str] = {
    "exact": OUTCOME_RESOLVED,
    "ambiguous": OUTCOME_AMBIGUOUS,
    "suggestion": OUTCOME_NOT_FOUND,
    "not_found": OUTCOME_NOT_FOUND,
}


def outcome_for_kind(kind: str) -> str:
    """Map an existing envelope ``kind`` to its user-visible ``outcome``.

    ``exact`` resolves; ``ambiguous`` stays ambiguous; ``suggestion`` and
    ``not_found`` both classify as ``not_found`` (suggestions remain attached
    to the envelope's candidate list).

    Args:
        kind: One of ``exact``, ``ambiguous``, ``suggestion``, ``not_found``.

    Returns:
        ``resolved``, ``ambiguous``, or ``not_found``.
    """
    return _KIND_TO_OUTCOME.get(kind, OUTCOME_NOT_FOUND)


# --- Ranking evidence tokens ------------------------------------------------

EVIDENCE_EXACT_FQN = "exact_fqn"
EVIDENCE_EXACT_CONVENTIONAL_FQN = "exact_conventional_fqn"
EVIDENCE_PARENT_SCOPE_MATCH = "parent_scope_match"
EVIDENCE_NON_DEPRECATED = "non_deprecated"
EVIDENCE_DEPRECATED = "deprecated"
EVIDENCE_SIGNATURE_MATCH = "signature_match"
EVIDENCE_MOST_PARAMETERS = "most_parameters"
EVIDENCE_PRODUCTION_SITE = "production_site"
EVIDENCE_DEFINITION_SITE = "definition_site"
EVIDENCE_DETERMINISTIC_TIEBREAK = "deterministic_tiebreak"

# --- Deprecation detection --------------------------------------------------

_DEPRECATION_MARKERS: tuple[str, ...] = ("deprecated", "deprecation")


def is_deprecated(declared_rules: str | None) -> bool:
    """Return whether *declared_rules* names a deprecation marker.

    ``symbols.declared_rules`` stores Java annotation / Python decorator text
    such as ``@Deprecated``; detection is a case-insensitive substring match on
    a small marker set, so no schema change is required.

    Args:
        declared_rules: The stored rule text, or ``None``.

    Returns:
        ``True`` when a deprecation marker is present.
    """
    if not declared_rules:
        return False
    lowered = declared_rules.lower()
    return any(marker in lowered for marker in _DEPRECATION_MARKERS)


# --- Signature parsing (canonical pure implementation) ----------------------


def normalize_signature(signature: str | None) -> dict[str, Any] | None:
    """Parse and normalize a ``(params)`` signature.

    Strips a leading ``(...)`` group (defaulting to empty params when absent),
    erases generic bodies before splitting (``Map<String,Object>`` -> ``Map``,
    ``List<Tag>`` -> ``List``, ``Map<String,Object>,String`` -> ``Map,String``),
    and collapses whitespace. Returns ``{"arity": int, "param_types": [...],
    "normalized": "map,string"}`` using the *stored* spelling's namespace-free
    type tokens; ``None`` when the input has no ``(``.

    Generic bodies are removed **before** the comma split, so a comma inside a
    generic body (``Map<String,Object>``) never inflates the arity. Arrow/generic
    tokens such as ``Map<String, Object>`` keep their base name only, and type
    order is preserved, so semantically identical signatures match while
    genuinely different ones never conflate. The function is a
    pure helper: consumers parse both the caller-supplied signature and the
    stored ``fqn``/``conventional_fqn`` ``(params)`` and compare
    arity-then-type-names.
    """
    if signature is None:
        return None
    if "(" not in signature:
        return None
    open_idx = signature.find("(")
    close_idx = signature.rfind(")")
    if close_idx == -1 or close_idx < open_idx:
        return None
    body = signature[open_idx + 1 : close_idx]

    def _erase_generics(text: str) -> str:
        out: list[str] = []
        depth = 0
        for ch in text:
            if ch == "<":
                depth += 1
            elif ch == ">":
                depth = max(0, depth - 1)
            elif depth == 0:
                out.append(ch)
        return "".join(out)

    erased = _erase_generics(body)
    param_types = [p.strip() for p in erased.split(",")]
    param_types = [p for p in param_types if p]
    normalized = ",".join(t.lower() for t in param_types)
    return {
        "arity": len(param_types),
        "param_types": param_types,
        "normalized": normalized,
    }


# --- Reference parsing ------------------------------------------------------


def strip_params(name: str) -> str:
    """Strip a trailing ``(...)`` parameter list from a name."""
    idx = name.find("(")
    return name[:idx] if idx != -1 else name


def symbol_leaf(query: str) -> str:
    """Extract the bare symbol name from a query (dotted, param, or path forms)."""
    q = strip_params(query)
    if "::" in q:
        q = q.split("::", 1)[-1]
    if q.endswith("/") and "/" in q:
        q = q.rsplit("/", 1)[-1]
    if "." in q:
        q = q.rsplit(".", 1)[-1]
    return q


def _parent_qualifier(query: str) -> str | None:
    """Return the qualifier before the leaf for dotted / ``::`` forms."""
    q = strip_params(query)
    if "::" in q:
        q = q.split("::", 1)[-1]
    if "/" in q:
        q = q.rsplit("/", 1)[-1]
    if "." not in q:
        return None
    qualifier = q.rsplit(".", 1)[0]
    return qualifier or None


def _reference_form(query: str) -> str:
    """Classify the reference shape: exact_fqn / qualified / suffix / bare_leaf."""
    if "::" in query and "/" in query:
        return EVIDENCE_EXACT_FQN
    qualifier = _parent_qualifier(query)
    if qualifier is None:
        return "bare_leaf"
    if "." in qualifier or "::" in qualifier:
        return "suffix"
    return "qualified"


@dataclass(frozen=True)
class SymbolReference:
    """The caller-supplied name, parsed into its matching components.

    Attributes:
        raw: The query trimmed of surrounding whitespace.
        leaf: The bare member name after stripping ``(params)``, ``::``
            namespace, path, and trailing qualifier.
        parent_qualifier: The qualifier before the leaf for dotted / ``::``
            forms, or ``None`` for a bare leaf.
        signature: Parsed ``(params)`` object (``{arity, param_types,
            normalized}``) or ``None``.
        form: ``exact_fqn`` | ``exact_conventional_fqn`` | ``qualified`` |
            ``suffix`` | ``bare_leaf``.
    """

    raw: str
    leaf: str
    parent_qualifier: str | None
    signature: dict[str, Any] | None
    form: str


def parse_reference(query: str) -> SymbolReference:
    """Parse *query* into a :class:`SymbolReference` (pure, no database).

    Matching is case-sensitive; a supplied ``(params)`` suffix is normalized
    before identity comparison.
    """
    raw = (query or "").strip()
    signature = normalize_signature(raw)
    form = _reference_form(raw)
    if form == EVIDENCE_EXACT_FQN:
        form = "exact_fqn"
    return SymbolReference(
        raw=raw,
        leaf=symbol_leaf(raw),
        parent_qualifier=_parent_qualifier(raw),
        signature=signature,
        form=form,
    )


# --- Ranking ----------------------------------------------------------------


@dataclass
class ResolutionResult:
    """The policy decision for one reference.

    Attributes:
        symbol: The resolved declaration, or ``None``.
        candidates: Ordered candidate rows (evidence/deprecated attached) when
            not resolved; the fallback suggestion rows when ``kind`` is
            ``suggestion``.
        kind: ``exact`` | ``ambiguous`` | ``suggestion`` | ``not_found``.
    """

    symbol: dict[str, Any] | None
    candidates: list[dict[str, Any]]
    kind: str


def _candidate_arity(candidate: dict[str, Any]) -> int:
    """Return the candidate's stored arity, or ``0`` when it has no signature."""
    sig = candidate.get("signature")
    if isinstance(sig, dict):
        arity = sig.get("arity")
        if isinstance(arity, int):
            return arity
    return 0


def _candidate_normalized(candidate: dict[str, Any]) -> str | None:
    """Return the candidate's normalized signature string, or ``None``."""
    sig = candidate.get("signature")
    if isinstance(sig, dict):
        normalized = sig.get("normalized")
        if isinstance(normalized, str):
            return normalized
    return None


def _parent_matches(candidate: dict[str, Any], parent_qualifier: str | None) -> bool:
    """Return whether the query's qualifier matches the candidate's parent."""
    if not parent_qualifier:
        return False
    parent_name = candidate.get("parent_name")
    if not parent_name:
        return False
    qualifier_leaf = parent_qualifier.rsplit(".", 1)[-1]
    if "::" in qualifier_leaf:
        qualifier_leaf = qualifier_leaf.rsplit("::", 1)[-1]
    if qualifier_leaf == parent_name or parent_qualifier == parent_name:
        return True
    return parent_qualifier.endswith("." + parent_name) or parent_qualifier.endswith(
        "::" + parent_name
    )


def _signature_matches(candidate: dict[str, Any], query_sig: dict[str, Any] | None) -> bool:
    """Return whether *candidate*'s signature equals the supplied one."""
    if not query_sig:
        return False
    normalized = _candidate_normalized(candidate)
    if normalized is None:
        return False
    return _candidate_arity(candidate) == query_sig.get("arity") and normalized == query_sig.get(
        "normalized"
    )


def _rank_candidates(
    candidates: list[dict[str, Any]],
    reference: SymbolReference,
    max_candidates: int,
) -> list[dict[str, Any]]:
    """Order *candidates* best-first by the documented policy and attach evidence.

    Ordered key: ``parent_scope_match`` -> ``non_deprecated`` ->
    ``signature_match`` -> ``most_parameters`` -> ``production_site`` ->
    stable ``fqn``/``id`` tie-break. Each returned candidate is a shallow copy
    carrying the additive ``evidence`` and ``deprecated`` fields. When the
    query is an exact FQN or conventional FQN that matches more than one row
    (duplicate declarations across files), the matching ``exact_fqn`` /
    ``exact_conventional_fqn`` evidence is attached so those ambiguous lists
    stay explainable.
    """
    parent = reference.parent_qualifier
    query_sig = reference.signature
    max_arity = max((_candidate_arity(c) for c in candidates), default=0)

    decorated: list[tuple[dict[str, Any], bool, bool, bool, int, bool]] = []
    for candidate in candidates:
        decorated.append(
            (
                candidate,
                _parent_matches(candidate, parent),
                is_deprecated(candidate.get("declared_rules")),
                _signature_matches(candidate, query_sig),
                _candidate_arity(candidate),
                not _is_test_file(candidate.get("file_path") or ""),
            )
        )

    decorated.sort(
        key=lambda item: (
            0 if item[1] else 1,
            1 if item[2] else 0,
            0 if item[3] else 1,
            -item[4],
            0 if item[5] else 1,
            item[0].get("fqn") or "",
            item[0].get("id") or 0,
        )
    )

    primary_counts: dict[tuple[bool, bool, bool, int, bool], int] = {}
    for _cand, parent_match, deprecated, sig_match, arity, production in decorated:
        key = (parent_match, deprecated, sig_match, arity, production)
        primary_counts[key] = primary_counts.get(key, 0) + 1

    ranked: list[dict[str, Any]] = []
    for candidate, parent_match, deprecated, sig_match, arity, production in decorated[
        : max(0, max_candidates)
    ]:
        evidence: list[str] = []
        if candidate.get("fqn") == reference.raw:
            evidence.append(EVIDENCE_EXACT_FQN)
        elif candidate.get("conventional_fqn") == reference.raw:
            evidence.append(EVIDENCE_EXACT_CONVENTIONAL_FQN)
        if parent_match:
            evidence.append(EVIDENCE_PARENT_SCOPE_MATCH)
        evidence.append(EVIDENCE_DEPRECATED if deprecated else EVIDENCE_NON_DEPRECATED)
        if sig_match:
            evidence.append(EVIDENCE_SIGNATURE_MATCH)
        if arity == max_arity:
            evidence.append(EVIDENCE_MOST_PARAMETERS)
        if production:
            evidence.append(EVIDENCE_PRODUCTION_SITE)
        evidence.append(EVIDENCE_DEFINITION_SITE)
        primary = (parent_match, deprecated, sig_match, arity, production)
        if primary_counts.get(primary, 0) > 1:
            evidence.append(EVIDENCE_DETERMINISTIC_TIEBREAK)
        summary = dict(candidate)
        summary["evidence"] = evidence
        summary["deprecated"] = deprecated
        ranked.append(summary)
    return ranked


def resolve_reference(
    reference: SymbolReference,
    candidates: list[dict[str, Any]],
    *,
    max_candidates: int,
) -> ResolutionResult:
    """Apply the resolution tiers and the ranked disambiguation policy.

    Identity tiers resolve only when exactly one declaration matches:
    ``exact_fqn`` -> ``exact_conventional_fqn`` -> ``unique_leaf`` (bare
    references only) -> ``exact_parent_scope`` (qualified references only).
    When more than one declaration matches, the result is a ranked candidate
    list and never an auto-selected declaration.

    Args:
        reference: The parsed caller reference.
        candidates: Raw candidate rows (with ``parent_name`` and ``signature``).
        max_candidates: The bound applied to the ambiguous candidate list.

    Returns:
        A :class:`ResolutionResult`.
    """
    if not candidates or not reference.raw or not reference.leaf:
        return ResolutionResult(None, [], "not_found")

    raw = reference.raw
    exact = [c for c in candidates if c.get("fqn") == raw]
    if len(exact) == 1:
        return ResolutionResult(exact[0], [], "exact")
    if len(exact) > 1:
        return ResolutionResult(
            None, _rank_candidates(exact, reference, max_candidates), "ambiguous"
        )

    conventional = [c for c in candidates if c.get("conventional_fqn") == raw]
    if len(conventional) == 1:
        return ResolutionResult(conventional[0], [], "exact")
    if len(conventional) > 1:
        return ResolutionResult(
            None, _rank_candidates(conventional, reference, max_candidates), "ambiguous"
        )

    name_rows = [c for c in candidates if c.get("name") == reference.leaf]
    if not name_rows:
        return ResolutionResult(None, candidates[:10], "suggestion")

    if not reference.parent_qualifier:
        if len(name_rows) == 1:
            return ResolutionResult(name_rows[0], [], "exact")
        return ResolutionResult(
            None, _rank_candidates(name_rows, reference, max_candidates), "ambiguous"
        )

    scoped = [c for c in name_rows if c.get("parent_name")]
    if not scoped:
        # A module-qualified top-level name: resolve by unique leaf.
        if len(name_rows) == 1:
            return ResolutionResult(name_rows[0], [], "exact")
        return ResolutionResult(
            None, _rank_candidates(name_rows, reference, max_candidates), "ambiguous"
        )

    scope = [c for c in scoped if _parent_matches(c, reference.parent_qualifier)]
    if len(scope) == 1:
        return ResolutionResult(scope[0], [], "exact")
    if not scope:
        # A qualifier that matches no parent must never resolve an unrelated
        # same-named declaration.
        return ResolutionResult(None, [], "not_found")
    return ResolutionResult(None, _rank_candidates(scope, reference, max_candidates), "ambiguous")


def resolve_with_signature(
    reference: SymbolReference,
    candidates: list[dict[str, Any]],
    *,
    max_candidates: int,
) -> ResolutionResult:
    """Signature-aware overload disambiguation.

    A supplied signature is a ranking signal, never an auto-select filter. A
    unique signature-consistent overload resolves; several return the ranked
    candidate list; a signature inconsistent with every overload falls back to
    the ranked list (never a contradicting declaration as resolved).

    Args:
        reference: The parsed caller reference (with ``signature`` populated).
        candidates: Raw candidate rows.
        max_candidates: The bound applied to the ambiguous candidate list.

    Returns:
        A :class:`ResolutionResult`.
    """
    if not candidates or not reference.raw or not reference.leaf:
        return ResolutionResult(None, [], "not_found")

    raw = reference.raw
    exact = [c for c in candidates if c.get("fqn") == raw]
    if len(exact) == 1:
        return ResolutionResult(exact[0], [], "exact")
    if len(exact) > 1:
        return ResolutionResult(
            None, _rank_candidates(exact, reference, max_candidates), "ambiguous"
        )
    conventional = [c for c in candidates if c.get("conventional_fqn") == raw]
    if len(conventional) == 1:
        return ResolutionResult(conventional[0], [], "exact")
    if len(conventional) > 1:
        return ResolutionResult(
            None, _rank_candidates(conventional, reference, max_candidates), "ambiguous"
        )

    name_rows = [c for c in candidates if c.get("name") == reference.leaf]
    matched = [c for c in name_rows if _signature_matches(c, reference.signature)]
    if matched:
        if len(matched) == 1:
            return ResolutionResult(matched[0], [], "exact")
        return ResolutionResult(
            None, _rank_candidates(matched, reference, max_candidates), "ambiguous"
        )
    if name_rows:
        return ResolutionResult(
            None, _rank_candidates(name_rows, reference, max_candidates), "ambiguous"
        )
    return ResolutionResult(None, [], "not_found")
