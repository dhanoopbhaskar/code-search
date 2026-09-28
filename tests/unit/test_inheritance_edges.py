"""Per-language inheritance-edge capture."""

from pathlib import Path

import pytest

from src.engine.parser import ASTParser
from src.engine.symbols import SymbolExtractor


@pytest.fixture
def extractor() -> SymbolExtractor:
    return SymbolExtractor(ASTParser())


def _inherits(extractor: SymbolExtractor, path: Path, source: str) -> list[tuple[str, str, str]]:
    """Return ``(source_leaf, target_fqn, target_raw)`` for every INHERITS edge."""
    data = source.encode()
    edges = extractor.extract_edges(path, data)
    out: list[tuple[str, str, str]] = []
    for edge in edges:
        if edge["edge_type"] != "INHERITS":
            continue
        src = edge["source_fqn"].rsplit("::", 1)[-1]
        out.append((src, edge["target_fqn"], edge.get("target_raw") or ""))
    return out


def test_python_base_clause(extractor: SymbolExtractor, tmp_path: Path) -> None:
    path = tmp_path / "a.py"
    edges = _inherits(extractor, path, "class Dog(Animal):\n    pass\n")
    assert edges == [("Dog", "Animal", "Animal")]


def test_python_multiple_bases_emit_one_edge_each(
    extractor: SymbolExtractor, tmp_path: Path
) -> None:
    path = tmp_path / "a.py"
    edges = _inherits(extractor, path, "class Multi(Alpha, Beta):\n    pass\n")
    assert [(s, t) for s, t, _ in edges] == [("Multi", "Alpha"), ("Multi", "Beta")]


def test_java_extends_and_implements(extractor: SymbolExtractor, tmp_path: Path) -> None:
    path = tmp_path / "A.java"
    source = "class Impl extends Base implements Alpha, Beta {}\n"
    edges = _inherits(extractor, path, source)
    assert [(s, t) for s, t, _ in edges] == [
        ("Impl", "Base"),
        ("Impl", "Alpha"),
        ("Impl", "Beta"),
    ]


def test_java_interface_extends(extractor: SymbolExtractor, tmp_path: Path) -> None:
    path = tmp_path / "A.java"
    edges = _inherits(extractor, path, "interface Pet extends Animal {}\n")
    assert edges == [("Pet", "Animal", "Animal")]


def test_typescript_class_and_interface(extractor: SymbolExtractor, tmp_path: Path) -> None:
    path = tmp_path / "a.ts"
    source = "class Dog extends Base implements Alpha {}\ninterface Pet extends Animal {}\n"
    edges = _inherits(extractor, path, source)
    assert [(s, t) for s, t, _ in edges] == [
        ("Dog", "Base"),
        ("Dog", "Alpha"),
        ("Pet", "Animal"),
    ]


def test_javascript_extends(extractor: SymbolExtractor, tmp_path: Path) -> None:
    path = tmp_path / "a.js"
    assert _inherits(extractor, path, "class Dog extends Animal {}\n") == [
        ("Dog", "Animal", "Animal")
    ]


def test_csharp_base_list(extractor: SymbolExtractor, tmp_path: Path) -> None:
    path = tmp_path / "a.cs"
    edges = _inherits(extractor, path, "class Impl : Base, IAlpha {}\n")
    assert [(s, t) for s, t, _ in edges] == [("Impl", "Base"), ("Impl", "IAlpha")]


def test_cpp_base_class_clause(extractor: SymbolExtractor, tmp_path: Path) -> None:
    path = tmp_path / "a.cpp"
    edges = _inherits(extractor, path, "class Impl : public Base, private Mixin {};\n")
    assert [(s, t) for s, t, _ in edges] == [("Impl", "Base"), ("Impl", "Mixin")]


def test_kotlin_delegation_specifiers(extractor: SymbolExtractor, tmp_path: Path) -> None:
    path = tmp_path / "a.kt"
    edges = _inherits(extractor, path, "class Impl : Base(), IFoo {}\n")
    assert [(s, t) for s, t, _ in edges] == [("Impl", "Base"), ("Impl", "IFoo")]


def test_ruby_superclass(extractor: SymbolExtractor, tmp_path: Path) -> None:
    path = tmp_path / "a.rb"
    assert _inherits(extractor, path, "class Impl < Base\nend\n") == [("Impl", "Base", "Base")]


def test_qualified_and_generic_bases_reduce_to_simple_name(
    extractor: SymbolExtractor, tmp_path: Path
) -> None:
    path = tmp_path / "A.java"
    source = "class Impl extends mixins.Base implements IList {}\n"
    edges = _inherits(extractor, path, source)
    assert [(s, t, raw) for s, t, raw in edges] == [
        ("Impl", "Base", "Base"),
        ("Impl", "IList", "IList"),
    ]


def test_cyclic_inheritance_terminates(extractor: SymbolExtractor, tmp_path: Path) -> None:
    path = tmp_path / "a.py"
    edges = _inherits(extractor, path, "class A(B):\n    pass\n\n\nclass B(A):\n    pass\n")
    assert [(s, t) for s, t, _ in edges] == [("A", "B"), ("B", "A")]


def test_no_edges_for_unsupported_languages(extractor: SymbolExtractor, tmp_path: Path) -> None:
    php = tmp_path / "a.php"
    php.write_text("<?php class Impl extends Base {}\n")
    assert _inherits(extractor, php, php.read_text()) == []

    go = tmp_path / "a.go"
    assert _inherits(extractor, go, "package main\n\ntype Impl struct {}\n") == []

    rust = tmp_path / "a.rs"
    assert _inherits(extractor, rust, "struct Impl;\n") == []
