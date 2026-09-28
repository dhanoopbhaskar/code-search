"""Per-result search confidence, calibrated with match-type evidence.

The base blend scores how much a query's decomposed sub-words actually appear
in a chunk's identifiers, blended with the raw vector cosine. That blend alone
cannot tell an exact primary definition from a fuzzy co-occurrence, so obvious
definitions can land in the low band when the vector arm is weak. This module
therefore layers *match-type evidence* on top of the unchanged base blend:

- a primary-definition boost and a controller-endpoint boost,
- evidence floors for exact FQN and exact unqualified symbol matches,
- an ambiguity cap so overloaded names never reach the high band, and
- a semantic-only floor for strong vector matches with no lexical overlap.

The calibrated score is a pure, deterministic function of the query text, the
chunk metadata, and the raw vector cosine. It feeds only the reported
``confidence``/``confidence_band``/``borderline`` fields; the BM25 score, the
vector score, the RRF fusion weights, and the ranked order are untouched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- Match-type evidence constants -------------------------------------------------
# These are module-level and documented so the calibration is auditable and the
# score is reproducible; the values are exercised directly by the unit tests.

#: Additive boost for a chunk that is a symbol's definition site.
BOOST_DEFINITION = 0.15
#: Additive boost for a definition chunk that is a controller endpoint.
BOOST_CONTROLLER_ENDPOINT = 0.10
#: Floor for a definition whose fully qualified name the query matches exactly.
FLOOR_EXACT_FQN_DEFINITION = 0.90
#: Floor for a reference whose fully qualified name the query matches exactly
#: (stays in the medium band, below the high floor).
FLOOR_EXACT_FQN = 0.65
#: Floor for a definition whose unqualified name the query matches exactly.
FLOOR_EXACT_SYMBOL_DEFINITION = 0.80
#: Floor for a reference whose unqualified name the query matches exactly.
FLOOR_EXACT_SYMBOL = 0.65
#: Ceiling applied when the query's bare identifier is ambiguous/overloaded.
AMBIGUOUS_CAP = 0.69
#: Floor for a strong semantic match with no lexical overlap.
SEMANTIC_ONLY_FLOOR = 0.50
#: Minimum vector cosine for the semantic-only floor to apply.
SEMANTIC_ONLY_VECTOR_MIN = 0.50

_QUALIFIED_SEGMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CONTROLLER_ANNOTATION_RE = re.compile(r"@(?:Get|Post|Put|Delete|Patch|Request)Mapping\b")


def _clamp_unit(value: float) -> float:
    """Clamp *value* into ``[0.0, 1.0]``."""
    return max(0.0, min(1.0, value))


def _normalize_fqn(fqn: str) -> str:
    """Return *fqn* with any trailing call signature ``(...)`` removed.

    The indexer stores method FQNs as ``...::Class.method(String,String)``; the
    signature is not part of the symbol name a user types, so it is stripped
    before name comparisons.
    """
    paren = fqn.find("(")
    return fqn[:paren] if paren != -1 else fqn


def _short_symbol_name(fqn: str) -> str:
    """Return the trailing symbol name of *fqn* (dotted or ``::`` scoped)."""
    normalized = _normalize_fqn(fqn)
    if "::" in normalized:
        normalized = normalized.rsplit("::", 1)[-1]
    return normalized.rsplit(".", 1)[-1]


def qualified_query_name(query: str) -> str | None:
    """Return *query* when it is a qualified name (``A.B`` / ``A::B``), else ``None``.

    Every segment must be a bare identifier, so a dotted decimal or a sentence
    containing a period is not treated as a qualified name.

    Args:
        query: The raw query text.

    Returns:
        The trimmed qualified name, or ``None`` when the query is not qualified.
    """
    text = query.strip()
    if not text:
        return None
    if "::" in text:
        parts = text.split("::")
    elif "." in text:
        parts = text.split(".")
    else:
        return None
    if not parts or any(not _QUALIFIED_SEGMENT_RE.fullmatch(part) for part in parts):
        return None
    return text


def is_exact_fqn_match(qualified_name: str | None, fqn: str) -> bool:
    """Return whether *qualified_name* matches *fqn* exactly.

    Four forms count as an exact match, with the candidate's signature suffix
    ignored: equality (``A.B`` names ``A.B``), a dotted suffix (``A.B`` matches
    ``pkg.A.B``), a ``::`` suffix (``A.B`` matches ``path::A.B``), and the owner
    form — a qualified query ``Owner.member`` whose owner names the candidate
    (``AuthController.authenticate`` matches the ``AuthController`` class
    chunk), so a member query still credits the type it belongs to.

    Args:
        qualified_name: The query's qualified form, or ``None``.
        fqn: The candidate chunk's fully qualified name.

    Returns:
        ``True`` when the qualified query names the candidate exactly.
    """
    if not qualified_name:
        return False
    normalized = _normalize_fqn(fqn)
    if normalized == qualified_name:
        return True
    if normalized.endswith("." + qualified_name) or normalized.endswith("::" + qualified_name):
        return True
    short = _short_symbol_name(normalized)
    return qualified_name.startswith(short + ".") or qualified_name.startswith(short + "::")


def is_exact_symbol_match(query_identifier: str | None, fqn: str, ambiguous: bool) -> bool:
    """Return whether a bare *query_identifier* names the candidate's short name.

    Ambiguous (overloaded) identifiers never count as exact matches — the query
    does not identify one symbol, so it must not earn exact-match credit.

    Args:
        query_identifier: The query's bare identifier, or ``None``.
        fqn: The candidate chunk's fully qualified name.
        ambiguous: Whether the identifier resolves to multiple candidates.

    Returns:
        ``True`` when the unqualified query equals the candidate's short name.
    """
    if not query_identifier or ambiguous:
        return False
    return _short_symbol_name(fqn) == query_identifier


def is_controller_endpoint(is_definition: bool, content: str, file_path: str) -> bool:
    """Return whether a definition chunk is a controller endpoint.

    A definition is an endpoint when its content carries a Spring mapping
    annotation or its file stem ends with ``Controller`` (the filename fallback
    for non-Spring controllers). References are never endpoints.

    Args:
        is_definition: Whether the chunk is the symbol's definition site.
        content: The chunk source (already in memory).
        file_path: The containing file path.

    Returns:
        ``True`` when the chunk is a controller endpoint definition.
    """
    if not is_definition:
        return False
    # Cheap substring gate before the (much costlier) annotation regex, so the
    # common non-controller definition pays only a scan for "Mapping".
    if "Mapping" in content and _CONTROLLER_ANNOTATION_RE.search(content):
        return True
    name = file_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return name.rsplit(".", 1)[0].endswith("Controller")


@dataclass(frozen=True)
class QueryMatchContext:
    """Query-level facts computed once per request and reused per candidate.

    Attributes:
        query_identifier: The query's bare identifier, or ``None``.
        qualified_name: The query's qualified form (``A.B`` / ``A::B``), or ``None``.
        ambiguous: Whether the bare identifier resolves to multiple candidates.
        resolved_symbol_name: The canonical short name when the query resolves
            exactly, or ``None``.
        symbol_resolved: Whether the query is a symbol-shaped reference that
            resolves to an indexed declaration (outcome ``resolved`` or
            ``ambiguous``), so the quality gate admits it.
    """

    query_identifier: str | None = None
    qualified_name: str | None = None
    ambiguous: bool = False
    resolved_symbol_name: str | None = None
    symbol_resolved: bool = False


@dataclass(frozen=True)
class MatchEvidence:
    """Per-result facts a confidence verdict is computed from.

    Built from the already-fetched chunk row and the raw vector cosine; the
    query-level ``QueryMatchContext`` supplies the qualified name, the bare
    identifier, and the ambiguity flag.

    Attributes:
        query_subwords: The query's decomposed sub-words.
        chunk_subwords: The candidate chunk's indexed sub-words.
        vector_score: The raw cosine in ``[0, 1]``; ``0.0`` when the vector arm
            produced no hit.
        fqn: The candidate's fully qualified name.
        is_definition: Whether the chunk is the symbol's definition site.
        content: The chunk source.
        file_path: The containing file path (controller filename fallback).
        query_identifier: Optional copy of the query's bare identifier.
    """

    query_subwords: list[str]
    chunk_subwords: list[str]
    vector_score: float
    fqn: str
    is_definition: bool
    content: str
    file_path: str
    query_identifier: str | None = None


def subword_overlap(query_subwords: list[str], chunk_subwords: list[str]) -> float:
    """Return the fraction of distinct *query_subwords* present in *chunk_subwords*.

    Duplicate sub-words in the query count once, so a repeated word cannot
    inflate coverage. ``0.0`` when the query carries no decomposable sub-words,
    so a query with nothing to match can never report a confident hit.

    Args:
        query_subwords: The query's decomposed sub-words.
        chunk_subwords: The chunk's indexed sub-words.

    Returns:
        The overlap fraction in ``[0.0, 1.0]``.
    """
    if not query_subwords:
        return 0.0
    chunk = set(chunk_subwords)
    distinct = set(query_subwords)
    hits = sum(1 for w in distinct if w in chunk)
    return hits / len(distinct)


def confidence_score(
    query_subwords: list[str],
    chunk_subwords: list[str],
    vector_score: float = 0.0,
) -> float:
    """Blend lexical sub-word overlap with the raw vector cosine (base blend).

    The two signals are averaged with equal weight; a chunk with no vector
    evidence (``vector_score`` 0.0) is scored purely on overlap. This is the
    pre-calibration blend, retained so callers and the evaluation harness can
    compare calibrated scores against the baseline.

    Args:
        query_subwords: The query's decomposed sub-words.
        chunk_subwords: The chunk's indexed sub-words.
        vector_score: The chunk's raw (pre-normalization) vector cosine in
            ``[0.0, 1.0]``; ``0.0`` when the vector arm produced no hit.

    Returns:
        The blended confidence in ``[0.0, 1.0]``.
    """
    overlap = subword_overlap(query_subwords, chunk_subwords)
    return 0.5 * overlap + 0.5 * _clamp_unit(vector_score)


def calibrated_confidence(evidence: MatchEvidence, context: QueryMatchContext) -> float:
    """Return the calibrated confidence for one candidate.

    The score starts from the unchanged base blend and layers match-type
    evidence: a primary-definition boost, a controller-endpoint boost, exact
    FQN/symbol floors, an ambiguity cap, and a semantic-only floor.

    Args:
        evidence: The candidate's per-result match facts.
        context: The query-level match context.

    Returns:
        The calibrated confidence in ``[0.0, 1.0]``.
    """
    overlap = subword_overlap(evidence.query_subwords, evidence.chunk_subwords)
    vector_score = _clamp_unit(evidence.vector_score)
    score = 0.5 * overlap + 0.5 * vector_score

    if evidence.is_definition:
        score += BOOST_DEFINITION
    if is_controller_endpoint(evidence.is_definition, evidence.content, evidence.file_path):
        score += BOOST_CONTROLLER_ENDPOINT

    query_identifier = context.query_identifier or evidence.query_identifier
    exact_fqn = is_exact_fqn_match(context.qualified_name, evidence.fqn)
    exact_symbol = is_exact_symbol_match(query_identifier, evidence.fqn, context.ambiguous)
    if exact_fqn:
        score = max(
            score, FLOOR_EXACT_FQN_DEFINITION if evidence.is_definition else FLOOR_EXACT_FQN
        )
    elif exact_symbol:
        score = max(
            score,
            FLOOR_EXACT_SYMBOL_DEFINITION if evidence.is_definition else FLOOR_EXACT_SYMBOL,
        )

    if context.ambiguous:
        score = min(score, AMBIGUOUS_CAP)

    if overlap == 0.0 and vector_score >= SEMANTIC_ONLY_VECTOR_MIN:
        score = max(score, SEMANTIC_ONLY_FLOOR)

    return _clamp_unit(score)


def confidence_band(score: float, high_floor: float, medium_floor: float) -> str:
    """Map a confidence *score* to ``high``, ``medium``, or ``low``.

    A score below *medium_floor* is ``low``; at or above *high_floor* is
    ``high``; everything in between is ``medium``.

    Args:
        score: The blended confidence score.
        high_floor: The score at which a result becomes ``high``.
        medium_floor: The score below which a result is ``low``.

    Returns:
        One of ``"high"``, ``"medium"``, or ``"low"``.
    """
    if score >= high_floor:
        return "high"
    if score >= medium_floor:
        return "medium"
    return "low"


def is_borderline(band: str) -> bool:
    """Return whether a confidence *band* is borderline (low confidence).

    A ``low`` band is borderline — consumers should verify such results;
    ``high``/``medium`` bands are not.

    Args:
        band: One of ``"high"``, ``"medium"``, or ``"low"``.

    Returns:
        ``True`` when *band* is ``"low"``.
    """
    return band == "low"


def envelope_band(bands: list[str]) -> str:
    """Aggregate per-result confidence bands into one envelope band.

    The envelope reports the strongest band present: any ``high`` result
    yields ``high``, else any ``medium`` yields ``medium``, else ``low``.
    ``none`` when the envelope carries no results at all.

    Args:
        bands: The per-result confidence bands.

    Returns:
        One of ``"high"``, ``"medium"``, ``"low"``, or ``"none"``.
    """
    if not bands:
        return "none"
    if "high" in bands:
        return "high"
    if "medium" in bands:
        return "medium"
    return "low"
