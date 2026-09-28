"""Unit tests for the confidence scoring module."""

from __future__ import annotations

from src.engine.confidence import (
    AMBIGUOUS_CAP,
    BOOST_CONTROLLER_ENDPOINT,
    BOOST_DEFINITION,
    FLOOR_EXACT_FQN,
    FLOOR_EXACT_FQN_DEFINITION,
    FLOOR_EXACT_SYMBOL,
    FLOOR_EXACT_SYMBOL_DEFINITION,
    SEMANTIC_ONLY_FLOOR,
    MatchEvidence,
    QueryMatchContext,
    calibrated_confidence,
    confidence_band,
    confidence_score,
    envelope_band,
    is_controller_endpoint,
    is_exact_fqn_match,
    is_exact_symbol_match,
    qualified_query_name,
    subword_overlap,
)


def _evidence(
    *,
    query_subwords: list[str] | None = None,
    chunk_subwords: list[str] | None = None,
    vector_score: float = 0.0,
    fqn: str = "path::Widget",
    is_definition: bool = False,
    content: str = "class Widget {}",
    file_path: str = "src/Widget.java",
    query_identifier: str | None = None,
) -> MatchEvidence:
    return MatchEvidence(
        query_subwords=query_subwords if query_subwords is not None else ["widget"],
        chunk_subwords=chunk_subwords if chunk_subwords is not None else ["widget"],
        vector_score=vector_score,
        fqn=fqn,
        is_definition=is_definition,
        content=content,
        file_path=file_path,
        query_identifier=query_identifier,
    )


def test_subword_overlap_full() -> None:
    assert subword_overlap(["password", "encode"], ["password", "encode"]) == 1.0


def test_subword_overlap_partial() -> None:
    assert subword_overlap(["password", "encode"], ["password"]) == 0.5


def test_subword_overlap_empty_query_returns_zero() -> None:
    assert subword_overlap([], ["password"]) == 0.0


def test_subword_overlap_duplicates_ignored() -> None:
    assert subword_overlap(["x", "x", "y"], ["x"]) == 0.5


def test_confidence_score_combines_overlap_and_vector() -> None:
    score = confidence_score(["password"], ["password"], 0.9)
    assert 0.0 < score <= 1.0
    assert score == 0.5 * 1.0 + 0.5 * 0.9


def test_confidence_bands() -> None:
    assert confidence_band(0.9, 0.7, 0.45) == "high"
    assert confidence_band(0.6, 0.7, 0.45) == "medium"
    assert confidence_band(0.2, 0.7, 0.45) == "low"


def test_envelope_band_none_for_empty_list() -> None:
    assert envelope_band([]) == "none"


def test_envelope_band_tracks_highest_result_band() -> None:
    assert envelope_band(["low", "high", "medium"]) == "high"


def test_envelope_band_low_when_all_results_low() -> None:
    assert envelope_band(["low", "low"]) == "low"


def test_confidence_score_clamps_to_unit() -> None:
    score = confidence_score(["password"], ["password"], 3.0)
    assert 0.0 <= score <= 1.0


# --- Calibrated match-type evidence -------------------------------------------------


def test_calibrated_preserves_base_blend_without_evidence() -> None:
    """With no match-type evidence the calibrated score equals the base blend."""
    evidence = _evidence(
        query_subwords=["alpha", "beta"], chunk_subwords=["alpha"], vector_score=0.4
    )
    context = QueryMatchContext()
    assert calibrated_confidence(evidence, context) == confidence_score(
        ["alpha", "beta"], ["alpha"], 0.4
    )


def test_calibrated_applies_definition_boost() -> None:
    evidence = _evidence(is_definition=True, vector_score=0.0)
    score = calibrated_confidence(evidence, QueryMatchContext())
    assert score == 0.5 * 1.0 + 0.5 * 0.0 + BOOST_DEFINITION


def test_qualified_query_name_detection() -> None:
    assert qualified_query_name("AuthController.authenticate") == "AuthController.authenticate"
    assert qualified_query_name("pkg::Widget") == "pkg::Widget"
    assert qualified_query_name("validate login credentials") is None
    assert qualified_query_name("3.5") is None


def test_is_exact_fqn_match_ignores_signature_suffix() -> None:
    assert is_exact_fqn_match(
        "AuthController.authenticate", "path::AuthController.authenticate(String,String)"
    )
    assert is_exact_fqn_match("A.B", "A.B")
    assert is_exact_fqn_match("A.B", "pkg.A.B")
    assert is_exact_fqn_match("AuthController.authenticate", "path::AuthController")
    assert not is_exact_fqn_match("A.C", "pkg.A.B")
    assert not is_exact_fqn_match(None, "pkg.A.B")


def test_exact_fqn_definition_floor() -> None:
    evidence = _evidence(
        query_subwords=["authenticate"],
        chunk_subwords=[],
        fqn="path::AuthController.authenticate(String,String)",
        is_definition=True,
    )
    context = QueryMatchContext(qualified_name="AuthController.authenticate")
    assert calibrated_confidence(evidence, context) == FLOOR_EXACT_FQN_DEFINITION


def test_exact_fqn_reference_floor_stays_below_high() -> None:
    evidence = _evidence(
        query_subwords=["authenticate"],
        chunk_subwords=[],
        fqn="path::AuthController.authenticate(String,String)",
        is_definition=False,
    )
    context = QueryMatchContext(qualified_name="AuthController.authenticate")
    assert calibrated_confidence(evidence, context) == FLOOR_EXACT_FQN


def test_is_exact_symbol_match_withholds_credit_when_ambiguous() -> None:
    assert is_exact_symbol_match("AuthService", "path::AuthService", False)
    assert not is_exact_symbol_match("AuthService", "path::AuthService", True)
    assert not is_exact_symbol_match(None, "path::AuthService", False)
    assert not is_exact_symbol_match("AuthService", "path::AuthService.authenticate", False)


def test_exact_symbol_floors() -> None:
    definition = _evidence(
        query_subwords=["authservice"],
        chunk_subwords=[],
        fqn="path::AuthService",
        is_definition=True,
    )
    reference = _evidence(
        query_subwords=["authservice"],
        chunk_subwords=[],
        fqn="path::AuthService",
        is_definition=False,
    )
    context = QueryMatchContext(query_identifier="AuthService")
    assert calibrated_confidence(definition, context) == FLOOR_EXACT_SYMBOL_DEFINITION
    assert calibrated_confidence(reference, context) == FLOOR_EXACT_SYMBOL


def test_ambiguous_name_is_capped_below_high() -> None:
    evidence = _evidence(
        query_subwords=["save"],
        chunk_subwords=["save"],
        vector_score=1.0,
        fqn="path::CommentService.save(Comment)",
        is_definition=True,
    )
    context = QueryMatchContext(query_identifier="save", ambiguous=True)
    assert calibrated_confidence(evidence, context) == AMBIGUOUS_CAP


def test_semantic_only_floor_lifts_strong_vector_match() -> None:
    evidence = _evidence(query_subwords=["login"], chunk_subwords=["auth"], vector_score=0.6)
    assert calibrated_confidence(evidence, QueryMatchContext()) == SEMANTIC_ONLY_FLOOR


def test_is_controller_endpoint_detection() -> None:
    assert is_controller_endpoint(True, '@GetMapping("/x")', "src/Foo.java")
    assert is_controller_endpoint(True, "class Foo {}", "src/AuthController.java")
    assert not is_controller_endpoint(False, '@GetMapping("/x")', "src/AuthController.java")
    assert not is_controller_endpoint(True, "class Foo {}", "src/Widget.java")


def test_controller_endpoint_boost() -> None:
    evidence = _evidence(
        is_definition=True,
        content='@PostMapping("/login")',
        file_path="src/AuthController.java",
    )
    score = calibrated_confidence(evidence, QueryMatchContext())
    assert score == 0.5 * 1.0 + BOOST_DEFINITION + BOOST_CONTROLLER_ENDPOINT


def test_definition_outranks_reference_at_equal_overlap() -> None:
    definition = _evidence(is_definition=True)
    reference = _evidence(is_definition=False)
    context = QueryMatchContext()
    assert calibrated_confidence(definition, context) > calibrated_confidence(reference, context)
