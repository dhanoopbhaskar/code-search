"""Content-type classification and config-scent vocabulary.

The content axis (``code|config|docs``) is the single vocabulary shared by the
indexer (index-time stamping), the query-time ranking weights, and the
content-type filter. These tests pin the extension/path conventions and the
config-scent vocabulary that lifts config chunks for config questions.
"""

from __future__ import annotations

import pytest

from src.engine.classification import ContentType, content_type
from src.engine.config import Settings


class TestContentType:
    def test_code_extensions_classify_as_code(self) -> None:
        for path in (
            "src/main/java/com/example/article/ArticleService.java",
            "src/article/service.py",
            "types/controller.ts",
            "src/lib/util.go",
            "pkg/auth.go",
        ):
            assert content_type(path) is ContentType.CODE, path

    def test_config_extensions_classify_as_config(self) -> None:
        for path in (
            "src/main/resources/application-dev.properties",
            "application.yml",
            "config/values.yaml",
            "build.gradle",
            "settings.toml",
            "app.json",
            "pom.xml",
            "nginx.conf",
            "db.ini",
            ".env",
            "config/app.cfg",
        ):
            assert content_type(path) is ContentType.CONFIG, path

    def test_docs_extensions_classify_as_docs(self) -> None:
        for path in (
            "docs/README.md",
            "docs/guide.markdown",
            "README.rst",
            "docs/deployment.txt",
            "docs/architecture.adoc",
        ):
            assert content_type(path) is ContentType.DOCS, path

    def test_env_style_filenames_classify_as_config(self) -> None:
        assert content_type(".env.local") is ContentType.CONFIG
        assert content_type(".env.prod") is ContentType.CONFIG
        assert content_type("environment") is ContentType.CONFIG

    def test_upper_case_suffixes_classify_the_same(self) -> None:
        assert content_type("config/APP.PROPERTIES") is ContentType.CONFIG
        assert content_type("docs/README.MD") is ContentType.DOCS
        assert content_type("src/Main.JAVA") is ContentType.CODE

    def test_content_type_members(self) -> None:
        assert ContentType.CODE.value == "code"
        assert ContentType.CONFIG.value == "config"
        assert ContentType.DOCS.value == "docs"


class TestConfigScentVocabulary:
    def test_default_config_scent_words_loaded(self) -> None:
        settings = Settings()
        assert "config" in settings.config_scent_words
        assert "pool" in settings.config_scent_words
        assert "timeout" in settings.config_scent_words
        assert "connection" in settings.config_scent_words

    def test_config_scent_words_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODE_SEARCH_CONFIG_SCENT_WORDS", "pool,timeout")
        settings = Settings()
        assert settings.config_scent_words == ("pool", "timeout")
        assert "connection" not in settings.config_scent_words

    def test_empty_config_scent_words_env_clears_vocabulary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODE_SEARCH_CONFIG_SCENT_WORDS", "")
        settings = Settings()
        assert settings.config_scent_words == ()
