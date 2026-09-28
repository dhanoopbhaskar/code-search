import os
from collections.abc import Iterator
from contextlib import contextmanager

from src.engine.config import Settings, _is_non_canonical, _is_test_file


@contextmanager
def _env_override(name: str, value: str) -> Iterator[None]:
    previous = os.environ.pop(name, None)
    os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def test_freshness_ttl_seconds_default() -> None:
    old = os.environ.pop("CODE_SEARCH_FRESHNESS_TTL_SECONDS", None)
    try:
        assert Settings().freshness_ttl_seconds == 5.0
    finally:
        if old is not None:
            os.environ["CODE_SEARCH_FRESHNESS_TTL_SECONDS"] = old


def test_freshness_ttl_seconds_env_override() -> None:
    os.environ["CODE_SEARCH_FRESHNESS_TTL_SECONDS"] = "0"
    try:
        assert Settings().freshness_ttl_seconds == 0.0
    finally:
        del os.environ["CODE_SEARCH_FRESHNESS_TTL_SECONDS"]


def test_spec_segment_in_main_source_is_not_test() -> None:
    assert (
        _is_test_file(
            "src/main/java/com/example/qualitydefects/infra/spec/ArticleSpecification.java"
        )
        is False
    )


def test_midpath_test_segment_in_main_source_is_not_test() -> None:
    assert _is_test_file("src/main/java/com/example/test/SomeClass.java") is False


def test_top_level_test_roots_are_test() -> None:
    assert _is_test_file("tests/test_auth.py") is True
    assert _is_test_file("/repo/test/foo_test.py") is True
    assert _is_test_file("__tests__/foo.test.ts") is True
    assert _is_test_file("__test__/foo_spec.rb") is True


def test_language_convention_test_roots_are_test() -> None:
    assert _is_test_file("src/test/java/com/example/AuthServiceTest.java") is True
    assert _is_test_file("androidTest/FooTest.kt") is True
    assert _is_test_file("app/src/jvmTest/FooTests.kt") is True
    assert _is_test_file("integrationTest/FooTest.java") is True


def test_test_filename_conventions_are_test() -> None:
    assert _is_test_file("src/auth/test_validate.py") is True
    assert _is_test_file("src/auth/validate_test.py") is True
    assert _is_test_file("src/foo/bar.test.js") is True
    assert _is_test_file("src/foo/bar.spec.ts") is True
    assert _is_test_file("spec/feature_spec.rb") is True
    assert _is_test_file("src/main/java/com/example/UserServiceTest.java") is True
    assert _is_test_file("src/main/java/com/example/UserServiceTests.java") is True
    assert _is_test_file("src/main/java/com/example/LoginTestCase.java") is True
    assert _is_test_file("src/foo/WidgetTest.kt") is True
    assert _is_test_file("src/foo/WidgetTests.swift") is True


def test_production_filenames_are_not_test() -> None:
    assert _is_test_file("src/utils.py") is False
    assert _is_test_file("src/main.py") is False
    assert _is_test_file("src/main/java/com/example/UserService.java") is False
    assert _is_test_file("src/main/java/com/example/security/TokenService.java") is False
    assert (
        _is_test_file(
            "src/main/java/com/example/qualitydefects/infra/spec/ArticleSpecification.java"
        )
        is False
    )


def test_non_canonical_files_are_not_tests() -> None:
    assert _is_test_file("generated/ArticleStub.java") is False
    assert _is_test_file("examples/foo.py") is False
    assert _is_test_file("src/stubs/fake_api.py") is False


def test_non_canonical_roots_flagged() -> None:
    assert _is_non_canonical("generated/ArticleStub.java") is True
    assert _is_non_canonical("examples/foo.py") is True
    assert _is_non_canonical("example/foo.py") is True
    assert _is_non_canonical("legacy/v1_client.py") is True
    assert _is_non_canonical("vendor/dep.js") is True
    assert _is_non_canonical("src/stubs/fake_api.py") is True


def test_non_canonical_filename_conventions_flagged() -> None:
    assert _is_non_canonical("src/mock_database.py") is True
    assert _is_non_canonical("src/fake_api.py") is True
    assert _is_non_canonical("src/foo/foo.stub.ts") is True
    assert _is_non_canonical("src/main/java/com/example/ArticleStub.java") is True


def test_canonical_files_are_not_non_canonical() -> None:
    assert _is_non_canonical("src/main.py") is False
    assert _is_non_canonical("tests/test_auth.py") is False
    assert (
        _is_non_canonical("src/main/java/com/example/qualitydefects/security/TokenService.java")
        is False
    )
    assert (
        _is_non_canonical(
            "src/main/java/com/example/qualitydefects/infra/spec/ArticleSpecification.java"
        )
        is False
    )


def test_semble_knob_defaults() -> None:
    keys = (
        "CODE_SEARCH_CHUNK_TARGET_CHARS",
        "CODE_SEARCH_CHUNK_MIN_CHARS",
        "CODE_SEARCH_STEM_RESCUE_BOOST",
        "CODE_SEARCH_STEM_MATCH_BOOST",
        "CODE_SEARCH_ALPHA_SYMBOL",
        "CODE_SEARCH_ALPHA_NL",
        "CODE_SEARCH_STEM_MIN_PREFIX",
        "CODE_SEARCH_NL_BOOST_MAX",
        "CODE_SEARCH_EMBEDDED_SYMBOL_BOOST",
        "CODE_SEARCH_DTS_PENALTY",
        "CODE_SEARCH_BARREL_PENALTY",
    )
    previous = {key: os.environ.pop(key, None) for key in keys}
    try:
        settings = Settings()
        assert settings.chunk_target_chars == 750
        assert settings.chunk_min_chars == 50
        assert settings.stem_rescue_boost == 1.0
        assert settings.stem_match_boost == 1.5
        assert settings.alpha_symbol == 0.3
        assert settings.alpha_nl == 0.5
        assert settings.stem_min_prefix == 3
        assert settings.nl_boost_max == 1.0
        assert settings.embedded_symbol_boost == 0.5
        assert settings.dts_penalty == 0.7
        assert settings.barrel_penalty == 0.5
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_alpha_symbol_clamped_to_upper_bound() -> None:
    with _env_override("CODE_SEARCH_ALPHA_SYMBOL", "5"):
        assert Settings().alpha_symbol == 1.0


def test_alpha_nl_clamped_to_lower_bound() -> None:
    with _env_override("CODE_SEARCH_ALPHA_NL", "-1"):
        assert Settings().alpha_nl == 0.0


def test_dts_penalty_floor_stays_positive() -> None:
    with _env_override("CODE_SEARCH_DTS_PENALTY", "0"):
        assert Settings().dts_penalty > 0.0


def test_barrel_penalty_floor_stays_positive() -> None:
    with _env_override("CODE_SEARCH_BARREL_PENALTY", "0"):
        assert Settings().barrel_penalty > 0.0


def test_dts_penalty_clamped_to_upper_bound() -> None:
    with _env_override("CODE_SEARCH_DTS_PENALTY", "2"):
        assert Settings().dts_penalty == 1.0


def test_boost_clamped_to_non_negative() -> None:
    with _env_override("CODE_SEARCH_STEM_MATCH_BOOST", "-1"):
        assert Settings().stem_match_boost == 0.0


def test_chunk_target_chars_floored_at_one() -> None:
    with _env_override("CODE_SEARCH_CHUNK_TARGET_CHARS", "0"):
        assert Settings().chunk_target_chars == 1


def test_chunk_min_chars_clamped_below_target() -> None:
    with (
        _env_override("CODE_SEARCH_CHUNK_MIN_CHARS", "1000"),
        _env_override("CODE_SEARCH_CHUNK_TARGET_CHARS", "750"),
    ):
        assert Settings().chunk_min_chars == 749


def test_stem_min_prefix_floored_at_one() -> None:
    with _env_override("CODE_SEARCH_STEM_MIN_PREFIX", "0"):
        assert Settings().stem_min_prefix == 1


def test_nl_boost_keywords_min_default() -> None:
    old = os.environ.pop("CODE_SEARCH_NL_BOOST_KEYWORDS_MIN", None)
    try:
        assert Settings().nl_boost_keywords_min == 2
    finally:
        if old is not None:
            os.environ["CODE_SEARCH_NL_BOOST_KEYWORDS_MIN"] = old


def test_nl_boost_keywords_min_floored_at_one() -> None:
    with _env_override("CODE_SEARCH_NL_BOOST_KEYWORDS_MIN", "0"):
        assert Settings().nl_boost_keywords_min == 1


def test_story_tokens_absent_from_source_comments() -> None:
    """Comments and docstrings under ``src/``, ``tests/`` and ``scripts/`` must
    state actual reasons, not requirement/story/task identifiers that the code
    cannot resolve. Test fixtures are exempt because their comments are indexed
    content.

    Delegates to the same checker run by ``make lint`` so the guard and the
    lint gate cannot drift apart.
    """
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "check_comment_refs.py"),
            "src/",
            "tests/",
            "scripts/",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_rescue_knob_defaults() -> None:
    old = {
        key: os.environ.pop(key, None)
        for key in (
            "CODE_SEARCH_RESCUE_T1_ENABLED",
            "CODE_SEARCH_RESCUE_T1_INFORMATIVE_TOKENS_MIN",
            "CODE_SEARCH_RESCUE_T1_CONCEPT_SIGNAL_MIN",
            "CODE_SEARCH_RESCUE_T1_RELEVANCE_THRESHOLD",
            "CODE_SEARCH_RESCUE_LITERAL_ENABLED",
            "CODE_SEARCH_DEFINITION_OWNER_BOOST",
            "CODE_SEARCH_MODEL_FILE_PENALTY",
            "CODE_SEARCH_DECLARED_RULE_BOOST",
            "CODE_SEARCH_INFRA_DEBOOST",
            "CODE_SEARCH_INFRA_DEBOOST_RELAXED",
            "CODE_SEARCH_EXHAUSTIVE_ENABLED",
            "CODE_SEARCH_EXHAUSTIVE_MAX_LINES",
            "CODE_SEARCH_ENUMERATE_ENABLED",
        )
    }
    try:
        settings = Settings()
        assert settings.rescue_t1_enabled is True
        assert settings.rescue_t1_informative_tokens_min == 1
        assert settings.rescue_t1_concept_signal_min == 1
        assert settings.rescue_t1_relevance_threshold == 0.0
        assert settings.rescue_literal_enabled is True
        assert settings.definition_owner_boost == 1.5
        assert settings.model_file_penalty == 0.6
        assert settings.declared_rule_boost == 1.5
        assert settings.infra_deboost == 0.35
        assert settings.infra_deboost_relaxed == 0.5
        assert settings.exhaustive_enabled is True
        assert settings.exhaustive_max_lines == 1000
        assert settings.enumerate_enabled is True
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_rescue_t1_minima_floored_at_one() -> None:
    with (
        _env_override("CODE_SEARCH_RESCUE_T1_INFORMATIVE_TOKENS_MIN", "0"),
        _env_override("CODE_SEARCH_RESCUE_T1_CONCEPT_SIGNAL_MIN", "0"),
    ):
        settings = Settings()
        assert settings.rescue_t1_informative_tokens_min == 1
        assert settings.rescue_t1_concept_signal_min == 1


def test_exhaustive_max_lines_floored_at_one() -> None:
    with _env_override("CODE_SEARCH_EXHAUSTIVE_MAX_LINES", "0"):
        assert Settings().exhaustive_max_lines == 1


def test_mode_toggles_override() -> None:
    with (
        _env_override("CODE_SEARCH_RESCUE_T1_ENABLED", "false"),
        _env_override("CODE_SEARCH_RESCUE_LITERAL_ENABLED", "false"),
        _env_override("CODE_SEARCH_EXHAUSTIVE_ENABLED", "false"),
        _env_override("CODE_SEARCH_ENUMERATE_ENABLED", "false"),
    ):
        settings = Settings()
        assert settings.rescue_t1_enabled is False
        assert settings.rescue_literal_enabled is False
        assert settings.exhaustive_enabled is False
        assert settings.enumerate_enabled is False


def test_exhaustive_case_sensitive_default_true() -> None:
    old = os.environ.pop("CODE_SEARCH_EXHAUSTIVE_CASE_SENSITIVE", None)
    try:
        assert Settings().exhaustive_case_sensitive is True
    finally:
        if old is not None:
            os.environ["CODE_SEARCH_EXHAUSTIVE_CASE_SENSITIVE"] = old


def test_declared_rule_intent_words_include_ownership() -> None:
    settings = Settings()
    assert "own" in settings.declared_rule_intent_words
    assert "owner" in settings.declared_rule_intent_words
    assert "definition" in settings.definition_intent_words
    assert "used" in settings.behavior_intent_words


def test_find_related_weight_env_overrides() -> None:
    """All four find_related knobs read from CODE_SEARCH_* env vars."""
    with (
        _env_override("CODE_SEARCH_FIND_RELATED_WEIGHT_PACKAGE", "0.5"),
        _env_override("CODE_SEARCH_FIND_RELATED_WEIGHT_TYPE", "0.2"),
        _env_override("CODE_SEARCH_FIND_RELATED_WEIGHT_CALL_GRAPH", "0.3"),
        _env_override("CODE_SEARCH_FIND_RELATED_SEMANTIC_BLEND", "0.7"),
    ):
        settings = Settings()
        assert settings.find_related_weight_package == 0.5
        assert settings.find_related_weight_type == 0.2
        assert settings.find_related_weight_call_graph == 0.3
        assert settings.find_related_semantic_blend == 0.7


def test_find_related_weights_normalize_to_one() -> None:
    """Non-unit-sum weights are normalized so the weighted fusion stays meaningful."""
    with (
        _env_override("CODE_SEARCH_FIND_RELATED_WEIGHT_PACKAGE", "0.9"),
        _env_override("CODE_SEARCH_FIND_RELATED_WEIGHT_TYPE", "0.3"),
        _env_override("CODE_SEARCH_FIND_RELATED_WEIGHT_CALL_GRAPH", "0.3"),
    ):
        settings = Settings()
        total = (
            settings.find_related_weight_package
            + settings.find_related_weight_type
            + settings.find_related_weight_call_graph
        )
        assert abs(total - 1.0) < 1e-6


def test_find_related_semantic_blend_clamped() -> None:
    """Blend outside [0, 1] clamps to the nearest bound."""
    with _env_override("CODE_SEARCH_FIND_RELATED_SEMANTIC_BLEND", "1.5"):
        assert Settings().find_related_semantic_blend == 1.0
    with _env_override("CODE_SEARCH_FIND_RELATED_SEMANTIC_BLEND", "-1"):
        assert Settings().find_related_semantic_blend == 0.0


def test_model_profile_default_resolves_to_default_model() -> None:
    """The default profile is unchanged: ``potion-code-16m-32d`` / 32."""
    with _env_override("CODE_SEARCH_MODEL_PROFILE", "default"):
        settings = Settings()
    assert settings.resolve_embedding_profile() == ("potion-code-16m-32d", 32)


def test_model_profile_fast_resolves_to_configured_pair() -> None:
    """The fast profile resolves to the configured local model/dimension pair."""
    with (
        _env_override("CODE_SEARCH_MODEL_PROFILE", "fast"),
        _env_override("CODE_SEARCH_FAST_EMBEDDING_MODEL", "potion-base-2M"),
        _env_override("CODE_SEARCH_FAST_EMBEDDING_DIM", "64"),
    ):
        settings = Settings()
    assert settings.resolve_embedding_profile() == ("potion-base-2M", 64)


def test_unknown_model_profile_raises() -> None:
    """An unknown profile raises an explicit error rather than scoring silently."""
    import pytest

    with _env_override("CODE_SEARCH_MODEL_PROFILE", "turbo"):
        settings = Settings()
    with pytest.raises(ValueError, match="CODE_SEARCH_MODEL_PROFILE"):
        settings.resolve_embedding_profile()


def test_index_model_mismatch_raises() -> None:
    """A recorded model different from the active profile raises explicitly."""
    import pytest

    from src.engine.embeddings import check_index_model_compatibility

    class _Meta:
        def __init__(self, value: str | None) -> None:
            self._value = value

        def get(self, _key: str) -> str | None:
            return self._value

    check_index_model_compatibility(Settings(), _Meta("potion-code-16m-32d"))
    check_index_model_compatibility(Settings(), _Meta(None))
    with pytest.raises(ValueError, match="re-run"):
        check_index_model_compatibility(Settings(), _Meta("some-other-model"))


def test_fast_profile_is_withheld_without_qualifying_candidate() -> None:
    """No candidate met the required floors, so the fast profile is not shipped."""
    from src.engine.embeddings import profile_model_available

    with _env_override("CODE_SEARCH_MODEL_PROFILE", "fast"):
        settings = Settings()
    assert settings.resolve_embedding_profile() == ("potion-base-2M", 64)
    assert profile_model_available(settings) is False
