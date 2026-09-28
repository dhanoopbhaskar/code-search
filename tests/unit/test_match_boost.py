"""Unit tests for the pure match-boost module.

Covers name normalization, tier classification, tier priority, boost
bounding, demotion withholding, and generic-stem dampening.
"""

from __future__ import annotations

from src.engine.match_boost import (
    EXACT_TIERS,
    BoostVerdict,
    MatchEvidence,
    MatchTier,
    QueryNameContext,
    boost_for_tier,
    classify_filename_match,
    classify_path_match,
    classify_symbol_match,
    compute_verdict,
    normalize_name,
    strongest_tier,
)

_WEIGHTS: dict[MatchTier, float] = {
    MatchTier.exact_fqn: 2.0,
    MatchTier.exact_symbol: 1.5,
    MatchTier.exact_filename: 1.5,
    MatchTier.stem: 0.5,
    MatchTier.path_term: 1.0,
}


def _context(
    query: str,
    *,
    normalized: str | None = None,
    significant_terms: tuple[str, ...] = (),
    query_identifier: str | None = None,
    qualified_name: str | None = None,
    ambiguous: bool = False,
) -> QueryNameContext:
    return QueryNameContext(
        raw_query=query,
        normalized=normalized if normalized is not None else normalize_name(query),
        subwords=tuple(significant_terms),
        significant_terms=significant_terms,
        query_identifier=query_identifier,
        qualified_name=qualified_name,
        ambiguous=ambiguous,
    )


def _verdict(
    evidence: MatchEvidence,
    *,
    normalized_query: str = "",
    generic_stems: frozenset[str] = frozenset(),
    pool_max: float = 1.0,
    cap: float = 2.0,
) -> BoostVerdict:
    return compute_verdict(
        evidence,
        _WEIGHTS,
        pool_max=pool_max,
        cap=cap,
        generic_stems=generic_stems,
        normalized_query=normalized_query,
    )


def test_normalize_name_case_and_separators() -> None:
    assert normalize_name("README") == "readme"
    assert normalize_name("  readme  ") == "readme"
    assert normalize_name("Readme.md") == "readmemd"
    assert normalize_name("auth_service") == "authservice"
    assert normalize_name("A::B") == "ab"


def test_match_tier_priority_order() -> None:
    assert MatchTier.exact_fqn > MatchTier.exact_symbol
    assert MatchTier.exact_symbol > MatchTier.exact_filename
    assert MatchTier.exact_filename > MatchTier.stem
    assert MatchTier.stem > MatchTier.path_term
    assert MatchTier.path_term > MatchTier.none
    assert strongest_tier([MatchTier.stem, MatchTier.exact_filename]) is MatchTier.exact_filename
    assert strongest_tier([]) is MatchTier.none


def test_classify_filename_match_name_and_stem() -> None:
    ctx = _context("README")
    assert classify_filename_match(ctx, "docs/README.md") is MatchTier.exact_filename
    assert classify_filename_match(ctx, "docs/readme") is MatchTier.exact_filename
    assert classify_filename_match(ctx, "docs/OPERATIONS.md") is MatchTier.none


def test_classify_filename_match_separator_insensitive() -> None:
    ctx = _context("auth_service")
    assert classify_filename_match(ctx, "src/auth_service.py") is MatchTier.exact_filename
    # Separators are stripped, so snake_case and camelCase compare equal.
    assert classify_filename_match(ctx, "src/AuthService.java") is MatchTier.exact_filename
    assert classify_filename_match(ctx, "src/AuthFactory.java") is MatchTier.none


def test_classify_filename_match_empty_query() -> None:
    ctx = _context("")
    assert classify_filename_match(ctx, "README.md") is MatchTier.none


def test_classify_symbol_match_definition_only() -> None:
    ctx = _context("ArticleService", query_identifier="ArticleService")
    assert classify_symbol_match(ctx, "pkg::ArticleService", True) is MatchTier.exact_symbol
    assert classify_symbol_match(ctx, "pkg::ArticleService", False) is MatchTier.none


def test_classify_symbol_match_ambiguous_suppressed() -> None:
    ctx = _context("save", query_identifier="save", ambiguous=True)
    assert classify_symbol_match(ctx, "pkg::ArticleService.save", True) is MatchTier.none


def test_classify_symbol_match_fqn_forms() -> None:
    ctx = _context("ArticleService.getArticle", qualified_name="ArticleService.getArticle")
    assert (
        classify_symbol_match(ctx, "pkg::ArticleService.getArticle(Long)", True)
        is MatchTier.exact_fqn
    )
    assert classify_symbol_match(ctx, "pkg::Other.getArticle(Long)", True) is MatchTier.none


def test_classify_path_match_stem_and_parent() -> None:
    ctx = _context(
        "authentication service",
        significant_terms=("authentication", "service"),
    )
    tier, ratio = classify_path_match(ctx, "services/auth_service.py")
    assert tier is MatchTier.stem
    assert ratio == 1.0

    tier, ratio = classify_path_match(ctx, "auth/security.py")
    assert tier is MatchTier.path_term
    assert ratio == 0.5


def test_classify_path_match_no_overlap() -> None:
    ctx = _context("authentication service", significant_terms=("authentication", "service"))
    tier, ratio = classify_path_match(ctx, "core/x.py")
    assert tier is MatchTier.none
    assert ratio == 0.0


def test_classify_path_match_generic_term_guard() -> None:
    # A single generic term never fires the proportional pass.
    ctx = _context("config", significant_terms=("config",))
    tier, ratio = classify_path_match(ctx, "app/config.py")
    assert tier is MatchTier.none
    assert ratio == 0.0


def test_classify_path_match_short_terms_gated() -> None:
    ctx = _context("au", significant_terms=("au",))
    tier, _ = classify_path_match(ctx, "core/auth.py", keywords_min=1)
    assert tier is MatchTier.none


def test_boost_for_tier_bounds_and_scales() -> None:
    assert boost_for_tier(MatchTier.exact_filename, 1.5, 1.0, 1.0, 2.0) == 1.5
    assert boost_for_tier(MatchTier.exact_fqn, 2.0, 1.0, 1.0, 2.0) == 2.0
    # Capped at cap * pool_max.
    assert boost_for_tier(MatchTier.exact_fqn, 5.0, 1.0, 1.0, 2.0) == 2.0
    # None tier and non-positive weight/strength yield zero.
    assert boost_for_tier(MatchTier.none, 1.5, 1.0, 1.0, 2.0) == 0.0
    assert boost_for_tier(MatchTier.stem, 0.0, 1.0, 1.0, 2.0) == 0.0
    assert boost_for_tier(MatchTier.stem, 0.5, 0.0, 1.0, 2.0) == 0.0


def test_boost_scales_with_pool_max() -> None:
    assert boost_for_tier(MatchTier.exact_filename, 1.5, 1.0, 4.0, 2.0) == 6.0


def test_match_evidence_ratio_alignment() -> None:
    assert MatchEvidence(1, MatchTier.exact_fqn, match_ratio=0.2).match_ratio == 1.0
    assert MatchEvidence(1, MatchTier.none, match_ratio=0.9).match_ratio == 0.0
    assert MatchEvidence(1, MatchTier.stem, match_ratio=1.7).match_ratio == 1.0


def test_compute_verdict_exact_filename() -> None:
    verdict = _verdict(MatchEvidence(1, MatchTier.exact_filename))
    assert verdict.applied
    assert verdict.tier is MatchTier.exact_filename
    assert verdict.boost == 1.5


def test_compute_verdict_none_tier() -> None:
    verdict = _verdict(MatchEvidence(1, MatchTier.none))
    assert verdict == BoostVerdict(tier=MatchTier.none, boost=0.0, applied=False)


def test_compute_verdict_withholds_exact_for_demoted_role() -> None:
    verdict = _verdict(MatchEvidence(1, MatchTier.exact_filename, is_demoted_role=True))
    assert not verdict.applied
    assert verdict.boost == 0.0


def test_compute_verdict_demotion_allows_proportional() -> None:
    evidence = MatchEvidence(1, MatchTier.stem, match_ratio=0.5, is_demoted_role=True)
    verdict = _verdict(evidence)
    assert verdict.applied
    assert verdict.tier is MatchTier.stem
    assert verdict.boost == 0.25


def test_compute_verdict_generic_stem_dampened_to_stem() -> None:
    evidence = MatchEvidence(1, MatchTier.exact_filename)
    verdict = _verdict(evidence, normalized_query="config", generic_stems=frozenset({"config"}))
    assert verdict.applied
    assert verdict.tier is MatchTier.stem
    assert verdict.boost == 0.5


def test_compute_verdict_generic_stem_requires_independent_evidence() -> None:
    evidence = MatchEvidence(1, MatchTier.exact_filename, has_independent_evidence=False)
    verdict = _verdict(evidence, normalized_query="config", generic_stems=frozenset({"config"}))
    assert not verdict.applied


def test_compute_verdict_generic_stem_non_generic_query_unaffected() -> None:
    evidence = MatchEvidence(1, MatchTier.exact_filename)
    verdict = _verdict(evidence, normalized_query="readme", generic_stems=frozenset({"config"}))
    assert verdict.tier is MatchTier.exact_filename


def test_exact_tiers_constant() -> None:
    assert MatchTier.exact_fqn in EXACT_TIERS
    assert MatchTier.exact_symbol in EXACT_TIERS
    assert MatchTier.exact_filename in EXACT_TIERS
    assert MatchTier.stem not in EXACT_TIERS
