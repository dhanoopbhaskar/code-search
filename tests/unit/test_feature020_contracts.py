"""Unit tests for the contract modules.

Pins the pure functions behind the serving contract independently of the
indexed integration tests: occurrence counting, config/DDL scent detection
and type-aware adjustment, model warm/cold reporting, index-change detection,
the serving response service, and the file-role/rescue-floor classifiers.
"""

from __future__ import annotations

from src.engine.file_role import FileRole, classify_file_role
from src.engine.occurrence_count import count_occurrences_per_line
from src.engine.rescue_floor import evaluate_rescue_floor
from src.engine.scent_detection import compute_scent_adjustment, detect_config_ddl_scent


class TestOccurrenceCount:
    def test_multi_occurrence_line_counts_twice(self) -> None:
        result = count_occurrences_per_line("a slugify b slugify\nslugify\n", "slugify")
        assert result["total"] == 3
        assert result["per_line"] == [2, 1]
        assert result["line_numbers"] == [1, 2]
        assert sum(result["per_line"]) == result["total"]

    def test_single_occurrence_per_line_matches_prior_behavior(self) -> None:
        result = count_occurrences_per_line("def slugify(x):\n    return x\n", "slugify")
        assert result["total"] == 1
        assert result["per_line"] == [1]
        assert result["line_numbers"] == [1]

    def test_empty_text_or_pattern(self) -> None:
        assert count_occurrences_per_line("", "x")["total"] == 0
        assert count_occurrences_per_line("abc", "")["total"] == 0


class TestScentDetection:
    def test_config_scent_keywords(self) -> None:
        assert detect_config_ddl_scent("server port configuration")["scent_type"] == "config"
        assert detect_config_ddl_scent("where is the mysql url")["scent_type"] == "config"

    def test_ddl_scent_keywords(self) -> None:
        assert detect_config_ddl_scent("create table articles")["scent_type"] == "ddl"
        assert (
            detect_config_ddl_scent("which schema migration adds a column")["scent_type"] == "ddl"
        )

    def test_neutral_query(self) -> None:
        result = detect_config_ddl_scent("how is the article saved")
        assert result["has_scent"] is False
        assert result["scent_type"] == "neutral"
        assert result["boost_factor"] == 1.0

    def test_plain_word_does_not_false_positive(self) -> None:
        assert detect_config_ddl_scent("how important is this")["scent_type"] == "neutral"


class TestComputeScentAdjustment:
    def test_config_boosts_properties_and_sql(self) -> None:
        assert compute_scent_adjustment("resource", ".properties", "config", 1.5) == 1.5
        assert compute_scent_adjustment("resource", ".sql", "config", 1.5) == 1.5

    def test_build_metadata_deprioritized(self) -> None:
        assert compute_scent_adjustment("resource", "pom.xml", "config", 1.5) == 0.5
        assert compute_scent_adjustment("resource", "package-lock.json", "config", 1.5) == 0.5

    def test_neutral_returns_identity(self) -> None:
        assert compute_scent_adjustment("resource", ".properties", "neutral", 1.5) == 1.0

    def test_code_file_unchanged(self) -> None:
        assert compute_scent_adjustment("code", ".java", "config", 1.5) == 1.0


class TestRescueFloor:
    def test_pure_gibberish_returns_no_match(self) -> None:
        result = evaluate_rescue_floor(["foxxyz", "qwerty", "asdfgh"], {"article", "service"}, 0.0)
        assert result["pure_gibberish"] is True
        assert result["return_rescue"] is False
        assert result["envelope"] is not None

    def test_borderline_real_returns_results(self) -> None:
        result = evaluate_rescue_floor(["article", "garbage"], {"article", "service"}, 0.2)
        assert result["pure_gibberish"] is False
        assert result["borderline_real"] is True


class TestFileRoleClassifier:
    def test_root_shell_script_is_infra(self) -> None:
        assert classify_file_role("wait-for-it.sh")["role"] is FileRole.INFRA

    def test_lockfile_is_infra(self) -> None:
        assert classify_file_role("package-lock.json")["role"] is FileRole.INFRA

    def test_infra_overridden_by_literal_evidence(self) -> None:
        result = classify_file_role("package-lock.json", literal_evidence=["jdbc:mysql://db:3306"])
        assert result["role"] is FileRole.CODE

    def test_properties_is_config(self) -> None:
        assert (
            classify_file_role("src/main/resources/application.properties")["role"]
            is FileRole.CONFIG
        )
