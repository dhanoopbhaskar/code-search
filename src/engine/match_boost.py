"""Pure filename/exact-match classification and bounded boost math.

The ranked path fuses BM25 and vector results via RRF and then layers several
additive, pool-max-scaled passes on top. None of those passes understands the
strongest signal a query can carry: the query *is* an indexed file name, a file
stem, an exact symbol, or a fully qualified name. This module isolates that
judgement as pure functions and immutable value objects so it is unit-testable
without a database, mirroring the ``src/engine/confidence.py`` separation
(pure scoring vs. pipeline wiring).

The module provides:

* :func:`normalize_name` — case- and separator-insensitive name normalization.
* :class:`MatchTier` — the priority-ordered match taxonomy.
* :class:`QueryNameContext` — request-scoped name facts shared by every
  candidate.
* :class:`MatchEvidence` — per-candidate facts a boost verdict is derived from.
* :class:`BoostVerdict` — the bounded additive adjustment for one candidate.
* :func:`boost_for_tier` — the bounded per-tier boost arithmetic.
* :func:`compute_verdict` — max-tier selection, demotion withholding, and
  generic-stem dampening.
* :func:`classify_filename_match`, :func:`classify_symbol_match`, and
  :func:`classify_path_match` — the tier classifiers.
* :func:`filename_candidates` — the FTS5-backed exact-filename candidate lookup.

All functions are deterministic and perform no network or third-party calls.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

from src.engine.confidence import is_exact_fqn_match, is_exact_symbol_match

logger = logging.getLogger(__name__)

#: Separators stripped when normalizing a file name, stem, or query so that
#: ``README``, ``readme``, and ``Readme.md`` all compare equal.
_NAME_SEPARATORS_RE = re.compile(r"[_\-./\\:]+")


class MatchTier(IntEnum):
    """The strongest filename/symbol evidence connecting a query to a chunk.

    The integer values encode priority so ``max()`` selects the strongest
    applicable tier; a chunk receives at most one tier.
    """

    none = 0
    path_term = 1
    stem = 2
    exact_filename = 3
    exact_symbol = 4
    exact_fqn = 5


#: Tiers withheld from demoted (test/non-canonical/infra/resource/analysis)
#: chunks so a filename match cannot leap above production code.
EXACT_TIERS: frozenset[MatchTier] = frozenset(
    {MatchTier.exact_fqn, MatchTier.exact_symbol, MatchTier.exact_filename}
)


def normalize_name(text: str) -> str:
    """Return *text* casefolded with separators removed.

    ``"Readme.md"``, ``"read_me"``, and ``"README"`` all normalize to
    ``"readme"``; ``"ArticleService.getArticle"`` normalizes to
    ``"articleservicegetarticle"``. Used for both the query and the candidate
    file name/stem so the comparison is case- and separator-insensitive.

    Args:
        text: The raw name, query, or path segment.

    Returns:
        The normalized comparison form (never ``None``; empty for empty input).
    """
    return _NAME_SEPARATORS_RE.sub("", text.strip().casefold())


def _query_subwords(text: str) -> list[str]:
    """Return the decomposed sub-words of *text*.

    Delegates to :func:`src.engine.search.decompose_query` (imported lazily to
    avoid the circular import between the search pipeline and this module) so
    the filename vocabulary matches the indexed sub-word vocabulary exactly.
    """
    from src.engine.search import decompose_query

    return decompose_query(text)


@dataclass(frozen=True)
class QueryNameContext:
    """Request-scoped name facts computed once and reused per candidate.

    Attributes:
        raw_query: The user query text.
        normalized: :func:`normalize_name` applied to *raw_query*.
        subwords: The query's decomposed sub-words.
        significant_terms: Sub-words used for proportional path matching
            (stopwords removed).
        query_identifier: The query's bare identifier, or ``None``.
        qualified_name: The query's ``A.B`` / ``A::B`` form, or ``None``.
        ambiguous: Whether the bare identifier resolves to multiple candidates.
        exact_filename_candidates: Chunk ids whose file name/stem equals
            *normalized* within the active content scope.
    """

    raw_query: str
    normalized: str
    subwords: tuple[str, ...] = ()
    significant_terms: tuple[str, ...] = ()
    query_identifier: str | None = None
    qualified_name: str | None = None
    ambiguous: bool = False
    exact_filename_candidates: tuple[int, ...] = ()


@dataclass(frozen=True)
class MatchEvidence:
    """Per-candidate facts a boost verdict is derived from.

    Attributes:
        chunk_id: The candidate chunk id.
        tier: The strongest applicable match tier.
        match_ratio: Fraction of significant terms matched for the proportional
            tiers; ``1.0`` for the exact tiers and ``0.0`` for ``none``.
        is_demoted_role: Whether the chunk is a test/non-canonical/infra/
            resource/analysis chunk.
        has_independent_evidence: Whether the chunk already carries a non-zero
            lexical or vector contribution in the fused pool.
    """

    chunk_id: int
    tier: MatchTier
    match_ratio: float = 0.0
    is_demoted_role: bool = False
    has_independent_evidence: bool = True

    def __post_init__(self) -> None:
        """Clamp *match_ratio* and align it with the tier."""
        if self.tier in EXACT_TIERS:
            ratio = 1.0
        elif self.tier is MatchTier.none:
            ratio = 0.0
        else:
            ratio = max(0.0, min(1.0, self.match_ratio))
        if ratio != self.match_ratio:
            object.__setattr__(self, "match_ratio", ratio)


@dataclass(frozen=True)
class BoostVerdict:
    """The additive ranking adjustment produced for one candidate.

    Attributes:
        tier: The tier the boost was applied for (the dampened ``stem`` tier
            when a generic-stem ``exact_filename`` was reduced).
        boost: The additive amount added to the fused score.
        applied: ``False`` when the tier was withheld (demoted role or a
            generic stem without independent evidence).
    """

    tier: MatchTier
    boost: float
    applied: bool


def boost_for_tier(
    tier: MatchTier,
    weight: float,
    strength: float,
    pool_max: float,
    cap: float,
) -> float:
    """Return the bounded additive boost for one match tier.

    The boost is ``pool_max * weight * strength`` capped at
    ``cap * pool_max`` so no single tier can distort the fused ordering, and is
    zero for the ``none`` tier, a non-positive weight, or a non-positive
    strength.

    Args:
        tier: The match tier the boost applies to.
        weight: The configured per-tier multiplier.
        strength: The per-tier strength (``1.0`` for exact tiers, the
            ``match_ratio`` for proportional tiers).
        pool_max: The current highest fused score.
        cap: The maximum per-chunk boost multiplier.

    Returns:
        The additive boost, never negative and never above ``cap * pool_max``.
    """
    if tier is MatchTier.none or weight <= 0.0 or strength <= 0.0:
        return 0.0
    return min(pool_max * weight * strength, cap * pool_max)


def strongest_tier(tiers: Iterable[MatchTier]) -> MatchTier:
    """Return the highest-priority tier in *tiers* (``none`` when empty)."""
    return max(tiers, default=MatchTier.none)


def compute_verdict(
    evidence: MatchEvidence,
    weights: Mapping[MatchTier, float],
    *,
    pool_max: float,
    cap: float,
    generic_stems: frozenset[str],
    normalized_query: str,
) -> BoostVerdict:
    """Return the bounded boost verdict for one candidate's evidence.

    Only the single strongest tier applies (never a sum of overlapping tiers).
    The exact tiers are withheld from demoted chunks. A query that is exactly a
    generic file stem has its ``exact_filename`` tier dampened to the
    proportional ``stem`` tier and applies only when the chunk already carries
    independent lexical or vector evidence.

    Args:
        evidence: The candidate's match evidence.
        weights: Per-tier weight multipliers.
        pool_max: The current highest fused score.
        cap: The maximum per-chunk boost multiplier.
        generic_stems: The ubiquitous file-stem vocabulary.
        normalized_query: :func:`normalize_name` applied to the query.

    Returns:
        The :class:`BoostVerdict` to apply (``applied=False`` when withheld).
    """
    tier = evidence.tier
    if tier is MatchTier.none:
        return BoostVerdict(tier=tier, boost=0.0, applied=False)

    is_generic_filename = tier is MatchTier.exact_filename and normalized_query in generic_stems
    effective_tier = MatchTier.stem if is_generic_filename else tier

    if evidence.is_demoted_role and effective_tier in EXACT_TIERS:
        return BoostVerdict(tier=tier, boost=0.0, applied=False)
    if is_generic_filename and not evidence.has_independent_evidence:
        return BoostVerdict(tier=tier, boost=0.0, applied=False)

    weight = weights.get(effective_tier, 0.0)
    strength = (
        evidence.match_ratio if effective_tier in (MatchTier.stem, MatchTier.path_term) else 1.0
    )
    boost = boost_for_tier(effective_tier, weight, strength, pool_max, cap)
    return BoostVerdict(tier=effective_tier, boost=boost, applied=boost > 0.0)


def classify_filename_match(context: QueryNameContext, file_path: str) -> MatchTier:
    """Return ``exact_filename`` when the query equals a file's name or stem.

    The comparison is case- and separator-insensitive: ``README`` matches both
    ``README.md`` (name) and a ``README`` stem, and ``auth_service`` matches
    ``auth_service.py``. Returns ``MatchTier.none`` otherwise.

    Args:
        context: The request-scoped name context.
        file_path: The candidate chunk's file path.

    Returns:
        :attr:`MatchTier.exact_filename` or :attr:`MatchTier.none`.
    """
    normalized = context.normalized
    if not normalized:
        return MatchTier.none
    path = Path(file_path)
    if normalized == normalize_name(path.name) or normalized == normalize_name(path.stem):
        return MatchTier.exact_filename
    return MatchTier.none


def classify_symbol_match(context: QueryNameContext, fqn: str, is_definition: bool) -> MatchTier:
    """Return the exact-symbol tier for a definition chunk, else ``none``.

    Reuses the pure predicates from :mod:`src.engine.confidence` so there is a
    single definition of "exact match". References never receive an exact tier,
    and an ambiguous (overloaded) bare identifier receives no ``exact_symbol``
    credit.

    Args:
        context: The request-scoped name context.
        fqn: The candidate chunk's fully qualified name.
        is_definition: Whether the chunk is the symbol's definition site.

    Returns:
        :attr:`MatchTier.exact_fqn`, :attr:`MatchTier.exact_symbol`, or
        :attr:`MatchTier.none`.
    """
    if not is_definition:
        return MatchTier.none
    if is_exact_fqn_match(context.qualified_name, fqn):
        return MatchTier.exact_fqn
    if is_exact_symbol_match(context.query_identifier, fqn, context.ambiguous):
        return MatchTier.exact_symbol
    return MatchTier.none


def classify_path_match(
    context: QueryNameContext,
    file_path: str,
    *,
    min_prefix: int = 3,
    keywords_min: int = 2,
) -> tuple[MatchTier, float]:
    """Return the proportional path tier and match ratio for a candidate.

    The query's significant terms (those at least *min_prefix* characters) are
    prefix-matched against the file stem and then the parent-directory
    sub-words; the file stem is preferred. The pass is skipped entirely when
    fewer than *keywords_min* eligible terms remain, so a single generic term
    cannot crown a name-matched file. The returned ratio is the fraction of
    eligible terms matched, clamped to ``[0.0, 1.0]``.

    Args:
        context: The request-scoped name context.
        file_path: The candidate chunk's file path.
        min_prefix: Minimum length for an eligible query term and a matched
            path term.
        keywords_min: Minimum eligible query terms required to run the pass.

    Returns:
        ``(MatchTier.stem | MatchTier.path_term | MatchTier.none, match_ratio)``.
    """
    keywords = [t for t in context.significant_terms if len(t) >= min_prefix]
    if len(keywords) < keywords_min:
        return MatchTier.none, 0.0
    path = Path(file_path)
    stem_terms = set(_query_subwords(path.stem))
    parent_terms = set(_query_subwords(path.parent.name))
    stem_hits = 0
    parent_hits = 0
    for kw in keywords:
        if any(len(t) >= min_prefix and _term_matches(kw, t) for t in stem_terms):
            stem_hits += 1
        elif any(len(t) >= min_prefix and _term_matches(kw, t) for t in parent_terms):
            parent_hits += 1
    total_hits = stem_hits + parent_hits
    if total_hits == 0:
        return MatchTier.none, 0.0
    ratio = min(1.0, total_hits / len(keywords))
    tier = MatchTier.stem if stem_hits else MatchTier.path_term
    return tier, ratio


def _term_matches(keyword: str, term: str) -> bool:
    """Return whether *keyword* and *term* share a prefix relationship."""
    return term == keyword or keyword.startswith(term) or term.startswith(keyword)


def filename_candidates(db: Any, context: QueryNameContext, content_scope: str) -> tuple[int, ...]:
    """Return chunk ids whose file name/stem equals the query, within scope.

    Narrows candidates with a single FTS5 ``file_path`` query built from the
    query's sub-words (never a full-corpus scan), applies the active content
    scope in the same query, then verifies normalized equality in Python.

    Args:
        db: The graph database exposing ``chunks_fts`` and ``code_chunks``.
        context: The request-scoped name context.
        content_scope: The active content scope (``all``/``code``/``config``/
            ``docs``/``code_focused``).

    Returns:
        A deterministic, de-duplicated tuple of matching chunk ids.
    """
    from src.engine.search import DEFAULT_CONTENT_SCOPE

    if not context.normalized:
        return ()
    tokens = [w for w in context.subwords if w]
    if not tokens:
        tokens = [context.normalized]
    match_expr = "file_path : (" + " OR ".join(tokens) + ")"
    if content_scope == "all":
        content_clause = ""
    elif content_scope == DEFAULT_CONTENT_SCOPE:
        content_clause = " AND c.content_type = 'code'"
    else:
        content_clause = " AND c.content_type = ?"
    params: list[Any] = [match_expr]
    if content_scope not in ("all", DEFAULT_CONTENT_SCOPE):
        params.append(content_scope)
    try:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT f.rowid AS id, c.file_path AS file_path "
                "FROM chunks_fts AS f JOIN code_chunks AS c ON c.id = f.rowid "
                "WHERE chunks_fts MATCH ?" + content_clause + " ORDER BY f.rowid;",
                params,
            ).fetchall()
    except Exception as exc:
        logger.warning("Exact filename candidate lookup failed: %s", exc)
        return ()
    matched: list[int] = []
    seen: set[int] = set()
    for row in rows:
        chunk_id = int(row["id"])
        if chunk_id in seen:
            continue
        if classify_filename_match(context, row["file_path"]) is MatchTier.exact_filename:
            seen.add(chunk_id)
            matched.append(chunk_id)
    return tuple(matched)
