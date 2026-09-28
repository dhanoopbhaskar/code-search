from typing import Any

import pytest

from src.engine.classification import ContentType, FileRole, PathClass, content_type, file_role


class BarrelConnection:
    def __init__(self, count: int) -> None:
        self._count = count

    def execute(self, _sql: str, _params: Any = None) -> "BarrelConnection":
        return self

    def fetchone(self) -> dict[str, Any]:
        return {"n": self._count}

    def __enter__(self) -> "BarrelConnection":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class FailingConnection:
    def execute(self, _sql: str, _params: Any = None) -> "FailingConnection":
        raise RuntimeError("database unavailable")

    def __enter__(self) -> "FailingConnection":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class DBDouble:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def connect(self) -> Any:
        return self._connection


def test_path_class_members() -> None:
    assert PathClass.CANONICAL.value == "canonical"
    assert PathClass.TEST.value == "test"
    assert PathClass.NON_CANONICAL.value == "non_canonical"
    assert PathClass.DTS.value == "dts"
    assert PathClass.BARREL.value == "barrel"


def test_path_class_of_test_shape() -> None:
    assert PathClass.of(DBDouble(BarrelConnection(5)), "tests/test_auth.py") == PathClass.TEST
    assert PathClass.of(DBDouble(BarrelConnection(5)), "src/test/java/AuthServiceTest.java") == (
        PathClass.TEST
    )


def test_path_class_of_non_canonical_shape() -> None:
    assert PathClass.of(DBDouble(BarrelConnection(5)), "examples/legacy/Foo.java") == (
        PathClass.NON_CANONICAL
    )


def test_path_class_of_dts_shape() -> None:
    assert PathClass.of(DBDouble(BarrelConnection(5)), "types/foo.d.ts") == PathClass.DTS


def test_path_class_of_canonical_plain_file() -> None:
    assert PathClass.of(DBDouble(BarrelConnection(5)), "src/foo.ts") == PathClass.CANONICAL


def test_path_class_of_barrel_zero_definitions() -> None:
    db = DBDouble(BarrelConnection(0))
    assert PathClass.of(db, "pkg/__init__.py") == PathClass.BARREL


def test_path_class_of_not_barrel_when_definitions_exist() -> None:
    db = DBDouble(BarrelConnection(4))
    assert PathClass.of(db, "pkg/__init__.py") == PathClass.CANONICAL


def test_path_class_is_barrel_only_for_named_surfaces() -> None:
    db = DBDouble(BarrelConnection(0))
    assert PathClass.is_barrel(db, "pkg/__init__.py") is True
    assert PathClass.is_barrel(db, "src/foo.ts") is False


def test_path_class_barrel_raises_on_database_failure() -> None:
    db = DBDouble(FailingConnection())
    with pytest.raises(RuntimeError, match="Barrel classification failed"):
        PathClass.of(db, "pkg/__init__.py")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/main/resources/application.properties", ContentType.CONFIG),
        ("src/main/resources/application.yml", ContentType.CONFIG),
        ("config/app.json", ContentType.CONFIG),
        ("db/migration/V1__create_articles_table.sql", ContentType.CONFIG),
        ("schema.sql", ContentType.CONFIG),
        ("src/main/java/ArticleService.java", ContentType.CODE),
        ("src/main.py", ContentType.CODE),
        ("docs/README.md", ContentType.DOCS),
        ("guides/setup.markdown", ContentType.DOCS),
        ("guides/setup.adoc", ContentType.DOCS),
        ("notes.txt", ContentType.DOCS),
    ],
)
def test_content_type(path: str, expected: ContentType) -> None:
    assert content_type(path) == expected


def test_sql_reclassifies_to_config() -> None:
    """``.sql`` moves from ``code`` to ``config`` so schema/migration chunks
    route through the config content filter and config-scent boosts."""
    assert content_type("db/migration/V1__create_articles_table.sql") == ContentType.CONFIG
    assert file_role("db/migration/V1__create_articles_table.sql") == FileRole.CONFIG


def test_file_role_members() -> None:
    assert FileRole.DOCS.value == "docs"
    assert FileRole.ANALYSIS.value == "analysis"
