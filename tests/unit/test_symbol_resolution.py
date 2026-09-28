"""Unit tests for the pure resolution policy (identity tiers and ranking).

These tests exercise :mod:`src.engine.symbol_resolution` directly with
synthetic candidate dicts — no database, no index, no model — so the ranking
policy, the identity tiers, the outcome mapping, deprecation detection, and the
evidence tokens are pinned independently of the storage layer.
"""

from __future__ import annotations

from typing import Any

from src.engine.symbol_resolution import (
    EVIDENCE_DEFINITION_SITE,
    EVIDENCE_DEPRECATED,
    EVIDENCE_DETERMINISTIC_TIEBREAK,
    EVIDENCE_EXACT_CONVENTIONAL_FQN,
    EVIDENCE_EXACT_FQN,
    EVIDENCE_MOST_PARAMETERS,
    EVIDENCE_NON_DEPRECATED,
    EVIDENCE_PARENT_SCOPE_MATCH,
    EVIDENCE_PRODUCTION_SITE,
    is_deprecated,
    outcome_for_kind,
    parse_reference,
    resolve_reference,
    resolve_with_signature,
)

_COUNTER = {"n": 0}


def _cand(
    name: str,
    *,
    fqn: str | None = None,
    conventional_fqn: str | None = None,
    kind: str = "method",
    file_path: str = "src/main/Prod.java",
    parent_name: str | None = "Service",
    parent_symbol_id: int | None = 1,
    declared_rules: str | None = None,
    params: list[str] | None = None,
    id: int | None = None,
) -> dict[str, Any]:
    """Build a synthetic candidate row (mirrors the graph candidate shape)."""
    _COUNTER["n"] += 1
    signature = None
    if params is not None:
        signature = {
            "arity": len(params),
            "param_types": list(params),
            "normalized": ",".join(p.lower() for p in params),
        }
    return {
        "id": id if id is not None else _COUNTER["n"],
        "fqn": fqn
        if fqn is not None
        else (
            f"src/main/Prod.java::{parent_name}.{name}"
            if parent_name
            else f"src/main/Prod.java::{name}"
        ),
        "conventional_fqn": conventional_fqn,
        "name": name,
        "kind": kind,
        "file_path": file_path,
        "line_start": 1,
        "line_end": 2,
        "parent_name": parent_name,
        "parent_symbol_id": parent_symbol_id,
        "declared_rules": declared_rules,
        "signature": signature,
    }


def _resolve(query: str, candidates: list[dict[str, Any]], max_candidates: int = 10):
    reference = parse_reference(query)
    if reference.signature is not None:
        return resolve_with_signature(reference, candidates, max_candidates=max_candidates)
    return resolve_reference(reference, candidates, max_candidates=max_candidates)


# --- Reference parsing and outcome mapping ----------------------------------


def test_parse_reference_forms() -> None:
    assert parse_reference("save").form == "bare_leaf"
    assert parse_reference("ArticleService.save").form == "qualified"
    assert parse_reference("com.example.ArticleService.save").form == "suffix"
    assert parse_reference("src/A.java::A.save(Article)").form == "exact_fqn"


def test_parse_reference_leaf_and_parent() -> None:
    ref = parse_reference("ArticleService.save")
    assert ref.leaf == "save"
    assert ref.parent_qualifier == "ArticleService"
    nested = parse_reference("Outer.Inner.method")
    assert nested.leaf == "method"
    assert nested.parent_qualifier == "Outer.Inner"
    suffix = parse_reference("com.example.ArticleService.save")
    assert suffix.leaf == "save"
    assert suffix.parent_qualifier == "com.example.ArticleService"


def test_parse_reference_case_sensitive_components() -> None:
    ref = parse_reference("ArticleService.Save")
    assert ref.leaf == "Save"
    assert ref.parent_qualifier == "ArticleService"


def test_parse_reference_signature_normalized() -> None:
    ref = parse_reference("Service.handle(Map<String, Object>, String)")
    assert ref.signature is not None
    assert ref.signature["normalized"] == "map,string"
    assert ref.leaf == "handle"
    assert ref.parent_qualifier == "Service"


def test_outcome_for_kind_mapping() -> None:
    assert outcome_for_kind("exact") == "resolved"
    assert outcome_for_kind("ambiguous") == "ambiguous"
    assert outcome_for_kind("suggestion") == "not_found"
    assert outcome_for_kind("not_found") == "not_found"
    assert outcome_for_kind("unknown") == "not_found"


def test_is_deprecated_markers() -> None:
    assert is_deprecated("@Deprecated") is True
    assert is_deprecated("@deprecated") is True
    assert is_deprecated("Deprecation") is True
    assert is_deprecated("PreAuthorize") is False
    assert is_deprecated(None) is False
    assert is_deprecated("") is False


# --- Identity tiers resolve only when exactly one declaration matches --------


def test_exact_fqn_unique_resolves() -> None:
    row = _cand("save", fqn="src/A.java::A.save(Article)")
    result = _resolve("src/A.java::A.save(Article)", [row])
    assert result.kind == "exact"
    assert result.symbol is row


def test_exact_conventional_fqn_unique_resolves() -> None:
    row = _cand(
        "save",
        fqn="src/A.java::A.save(Article)",
        conventional_fqn="com.example.A.save(Article)",
    )
    result = _resolve("com.example.A.save(Article)", [row])
    assert result.kind == "exact"
    assert result.symbol is row


def test_unique_leaf_bare_resolves() -> None:
    row = _cand("save", fqn="src/A.java::A.save(Article)")
    result = _resolve("save", [row])
    assert result.kind == "exact"
    assert result.symbol is row


def test_exact_parent_scope_unique_resolves() -> None:
    row = _cand("save", fqn="src/A.java::A.save(Article)", parent_name="A")
    result = _resolve("A.save", [row])
    assert result.kind == "exact"
    assert result.symbol is row


def test_nested_class_parent_scope_resolves() -> None:
    row = _cand("method", fqn="src/A.java::Outer.Inner.method", parent_name="Inner")
    result = _resolve("Outer.Inner.method", [row])
    assert result.kind == "exact"
    assert result.symbol is row


def test_empty_and_whitespace_reference_not_found() -> None:
    rows = [_cand("save"), _cand("delete")]
    assert _resolve("", rows).kind == "not_found"
    assert _resolve("   ", rows).kind == "not_found"


def test_case_only_mismatch_does_not_resolve() -> None:
    row = _cand("save", fqn="src/A.java::A.save")
    result = _resolve("Save", [row])
    assert result.symbol is None
    assert result.kind in ("ambiguous", "not_found", "suggestion")


def test_wrong_parent_qualifier_does_not_resolve_unrelated_name() -> None:
    row = _cand("save", fqn="src/A.java::A.save", parent_name="ArticleService")
    result = _resolve("WrongClass.save", [row])
    assert result.symbol is None
    assert result.kind == "not_found"


def test_duplicate_fqn_yields_ambiguous_ranked_list_not_first_match() -> None:
    rows = [
        _cand("save", fqn="src/A.java::A.save", parent_name="A", id=1),
        _cand("save", fqn="src/A.java::A.save", parent_name="A", id=2),
    ]
    result = _resolve("src/A.java::A.save", rows)
    assert result.symbol is None
    assert result.kind == "ambiguous"
    assert len(result.candidates) == 2
    assert all(EVIDENCE_EXACT_FQN in c["evidence"] for c in result.candidates)


def test_duplicate_conventional_fqn_yields_ambiguous_exact_evidence() -> None:
    rows = [
        _cand(
            "save",
            fqn="src/a/A.java::A.save",
            conventional_fqn="com.example.A.save",
            parent_name="A",
            id=1,
        ),
        _cand(
            "save",
            fqn="src/b/A.java::A.save",
            conventional_fqn="com.example.A.save",
            parent_name="A",
            id=2,
        ),
    ]
    result = _resolve("com.example.A.save", rows)
    assert result.symbol is None
    assert result.kind == "ambiguous"
    assert len(result.candidates) == 2
    assert all(EVIDENCE_EXACT_CONVENTIONAL_FQN in c["evidence"] for c in result.candidates)
    assert all(EVIDENCE_EXACT_FQN not in c["evidence"] for c in result.candidates)


def test_generic_parameterized_formatting_difference_resolves() -> None:
    row = _cand(
        "generateToken",
        fqn="src/T.java::T.generateToken(Map,String)",
        conventional_fqn="com.example.T.generateToken(Map<String,Object>,String)",
        params=["Map", "String"],
    )
    result = _resolve("T.generateToken(Map<String, Object>, String)", [row])
    assert result.kind == "exact"
    assert result.symbol is row


# --- Ranked disambiguation and evidence --------------------------------------


def test_ambiguous_list_most_parameters_first() -> None:
    one = _cand("save", fqn="src/A.java::A.save(Article)", params=["Article"], parent_name="A")
    two = _cand(
        "save",
        fqn="src/A.java::A.save(Article,boolean)",
        params=["Article", "boolean"],
        parent_name="A",
    )
    result = _resolve("A.save", [one, two])
    assert result.kind == "ambiguous"
    assert result.candidates[0]["fqn"] == two["fqn"]
    assert EVIDENCE_MOST_PARAMETERS in result.candidates[0]["evidence"]
    assert EVIDENCE_MOST_PARAMETERS not in result.candidates[1]["evidence"]
    assert EVIDENCE_PARENT_SCOPE_MATCH in result.candidates[0]["evidence"]
    assert EVIDENCE_DEFINITION_SITE in result.candidates[0]["evidence"]


def test_ambiguous_list_non_deprecated_first() -> None:
    old = _cand(
        "process",
        fqn="src/L.java::L.process(String)",
        params=["String"],
        parent_name="L",
        declared_rules="@Deprecated",
    )
    new = _cand("process", fqn="src/L.java::L.process(int)", params=["int"], parent_name="L")
    result = _resolve("L.process", [old, new])
    assert result.kind == "ambiguous"
    assert result.candidates[0]["fqn"] == new["fqn"]
    assert result.candidates[0]["deprecated"] is False
    assert EVIDENCE_NON_DEPRECATED in result.candidates[0]["evidence"]
    assert result.candidates[1]["deprecated"] is True
    assert EVIDENCE_DEPRECATED in result.candidates[1]["evidence"]


def test_all_deprecated_candidates_still_returned() -> None:
    a = _cand(
        "run",
        fqn="src/F.java::F.run(String)",
        params=["String"],
        parent_name="F",
        declared_rules="@Deprecated",
    )
    b = _cand(
        "run",
        fqn="src/F.java::F.run(int)",
        params=["int"],
        parent_name="F",
        declared_rules="@Deprecated",
    )
    result = _resolve("F.run", [a, b])
    assert result.kind == "ambiguous"
    assert len(result.candidates) == 2
    assert all(c["deprecated"] is True for c in result.candidates)


def test_production_site_ranks_ahead_of_test_site() -> None:
    test_row = _cand(
        "save",
        fqn="src/test/A.java::A.save(Article)",
        params=["Article"],
        parent_name="A",
        file_path="src/test/java/A.java",
        id=1,
    )
    prod_row = _cand(
        "save",
        fqn="src/main/A.java::A.save(Article,boolean)",
        params=["Article", "boolean"],
        parent_name="A",
        file_path="src/main/java/A.java",
        id=2,
    )
    result = _resolve("A.save", [test_row, prod_row])
    # most_parameters outranks production_site, so the 2-arg production row wins.
    assert result.candidates[0]["fqn"] == prod_row["fqn"]

    # With equal arity the production site decides.
    test_row2 = _cand(
        "save",
        fqn="src/test/A.java::A.save(Article)",
        params=["Article"],
        parent_name="A",
        file_path="src/test/java/A.java",
        id=3,
    )
    prod_row2 = _cand(
        "save",
        fqn="src/main/A.java::A.save(Article)",
        params=["Article"],
        parent_name="A",
        file_path="src/main/java/A.java",
        id=4,
    )
    result2 = _resolve("A.save", [test_row2, prod_row2])
    assert result2.candidates[0]["fqn"] == prod_row2["fqn"]
    assert EVIDENCE_PRODUCTION_SITE in result2.candidates[0]["evidence"]


def test_large_match_set_bounded_and_stable() -> None:
    rows = [
        _cand("save", fqn=f"src/save_{i}.py::save", parent_name=None, parent_symbol_id=None, id=i)
        for i in range(50)
    ]
    first = _resolve("save", rows, max_candidates=10)
    second = _resolve("save", list(reversed(rows)), max_candidates=10)
    assert len(first.candidates) == 10
    assert [c["fqn"] for c in first.candidates] == [c["fqn"] for c in second.candidates]
    assert first.candidates[0]["fqn"] == "src/save_0.py::save"


def test_tiebreak_evidence_when_primary_key_ties() -> None:
    a = _cand("save", fqn="src/a.py::save", parent_name=None, parent_symbol_id=None, id=1)
    b = _cand("save", fqn="src/b.py::save", parent_name=None, parent_symbol_id=None, id=2)
    result = _resolve("save", [a, b])
    assert result.kind == "ambiguous"
    assert all(EVIDENCE_DETERMINISTIC_TIEBREAK in c["evidence"] for c in result.candidates)
    assert result.candidates[0]["fqn"] == "src/a.py::save"


def test_misspelled_reference_returns_suggestions_never_resolves() -> None:
    # The pure policy receives the fallback rows the candidate query produced;
    # they are suggestion-level and never a resolved declaration.
    suggestion = _cand("isTokenValid", fqn="src/T.java::T.isTokenValid(String)", params=["String"])
    suggestion["edit_distance"] = 2
    result = _resolve("validateToken", [suggestion])
    assert result.kind == "suggestion"
    assert result.symbol is None
    assert result.candidates[0]["edit_distance"] == 2


def test_signature_match_evidence_on_matched_candidate() -> None:
    one = _cand("save", fqn="src/A.java::A.save(Article)", params=["Article"], parent_name="A")
    two = _cand(
        "save",
        fqn="src/A.java::A.save(Article,boolean)",
        params=["Article", "boolean"],
        parent_name="A",
    )
    result = _resolve("A.save(Article, boolean)", [one, two])
    assert result.kind == "exact"
    assert result.symbol is two


def test_signature_inconsistent_falls_back_to_ranked_list() -> None:
    one = _cand("save", fqn="src/A.java::A.save(Article)", params=["Article"], parent_name="A")
    two = _cand(
        "save",
        fqn="src/A.java::A.save(Article,boolean)",
        params=["Article", "boolean"],
        parent_name="A",
    )
    result = _resolve("A.save(boolean)", [one, two])
    assert result.kind == "ambiguous"
    assert result.symbol is None
    assert all(c["signature"]["normalized"] != "boolean" for c in result.candidates)
