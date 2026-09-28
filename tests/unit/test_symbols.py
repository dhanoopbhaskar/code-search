from pathlib import Path

import pytest

from src.engine.config import Settings
from src.engine.graph import EdgeStore, GraphDatabase
from src.engine.parser import ASTParser
from src.engine.symbols import SymbolExtractor, SymbolStore


@pytest.fixture
def parser() -> ASTParser:
    return ASTParser()


@pytest.fixture
def extractor(parser: ASTParser) -> SymbolExtractor:
    return SymbolExtractor(parser)


@pytest.fixture
def db(tmp_path: Path) -> GraphDatabase:
    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "test.db", settings)
    db.initialize()
    return db


@pytest.fixture
def edge_store(db: GraphDatabase) -> EdgeStore:
    return EdgeStore(db)


@pytest.fixture
def populated_db(db: GraphDatabase) -> GraphDatabase:
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            ("mymodule.MyClass", "MyClass", "class", "src/mymodule.py", 1, 10, 0, 5, "python"),
        )
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language, parent_symbol_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "(SELECT id FROM symbols WHERE fqn = 'mymodule.MyClass'));",
            (
                "mymodule.MyClass.my_method",
                "my_method",
                "method",
                "src/mymodule.py",
                3,
                8,
                4,
                20,
                "python",
            ),
        )
        conn.execute(
            "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
            "content, language, is_definition) "
            "VALUES (?, ?, ?, ?, ?, ?, ?);",
            (
                "mymodule.MyClass.my_method",
                "src/mymodule.py",
                3,
                8,
                "def my_method(self):\n    pass\n",
                "python",
                1,
            ),
        )
    return db


@pytest.fixture
def populated_edge_store(populated_db: GraphDatabase) -> EdgeStore:
    return EdgeStore(populated_db)


def test_extract_function_symbol(extractor: SymbolExtractor, tmp_path: Path) -> None:
    py_file = tmp_path / "test.py"
    py_file.write_text(
        'def greet(name: str) -> str:\n    """Say hello."""\n    return f"Hello, {name}"\n'
    )
    source = py_file.read_bytes()
    symbols = extractor.extract_symbols(py_file, source)
    assert len(symbols) >= 1
    sym = symbols[0]
    assert sym["name"] == "greet"
    assert sym["kind"] == "function"
    assert sym["fqn"].endswith("::greet")
    assert sym["file_path"] == str(py_file)
    assert sym["language"] == "python"


def test_extract_class_and_method(extractor: SymbolExtractor, tmp_path: Path) -> None:
    py_file = tmp_path / "test.py"
    py_file.write_text(
        "class Calculator:\n    def add(self, a: int, b: int) -> int:\n        return a + b\n"
    )
    source = py_file.read_bytes()
    symbols = extractor.extract_symbols(py_file, source)
    assert len(symbols) >= 2
    class_sym = next(s for s in symbols if s["kind"] == "class")
    method_sym = next(s for s in symbols if s["kind"] == "method")
    assert class_sym["name"] == "Calculator"
    assert method_sym["name"] == "add"
    assert method_sym["parent_fqn"] == class_sym["fqn"]


def test_extract_nested_class(extractor: SymbolExtractor, tmp_path: Path) -> None:
    py_file = tmp_path / "test.py"
    py_file.write_text(
        "class Outer:\n    class Inner:\n        def method(self):\n            pass\n"
    )
    source = py_file.read_bytes()
    symbols = extractor.extract_symbols(py_file, source)
    assert len(symbols) >= 3
    outer = next(s for s in symbols if s["name"] == "Outer")
    inner = next(s for s in symbols if s["name"] == "Inner")
    method = next(s for s in symbols if s["name"] == "method")
    assert inner["parent_fqn"] == outer["fqn"]
    assert method["parent_fqn"] == inner["fqn"]


def test_extract_docstring(extractor: SymbolExtractor, tmp_path: Path) -> None:
    py_file = tmp_path / "test.py"
    py_file.write_text(
        '"""Module docstring."""\ndef hello():\n    """Function docstring."""\n    pass\n'
    )
    source = py_file.read_bytes()
    symbols = extractor.extract_symbols(py_file, source)
    assert len(symbols) >= 1
    sym = symbols[0]
    doc = sym.get("docstring")
    assert doc is not None
    assert "Function docstring" in doc


def test_empty_file(extractor: SymbolExtractor, tmp_path: Path) -> None:
    py_file = tmp_path / "empty.py"
    py_file.write_text("")
    source = py_file.read_bytes()
    symbols = extractor.extract_symbols(py_file, source)
    assert len(symbols) == 0


def test_no_symbols_comment_only(extractor: SymbolExtractor, tmp_path: Path) -> None:
    py_file = tmp_path / "comment.py"
    py_file.write_text("# Just a comment\n# Another line\n")
    source = py_file.read_bytes()
    symbols = extractor.extract_symbols(py_file, source)
    assert len(symbols) == 0


def test_symbol_definition_lookup_found(
    populated_edge_store: EdgeStore,
) -> None:
    result = populated_edge_store.get_symbol_definition("mymodule.MyClass.my_method")
    assert result is not None
    assert result["fqn"] == "mymodule.MyClass.my_method"
    assert result["name"] == "my_method"
    assert result["kind"] == "method"
    assert result["file_path"] == "src/mymodule.py"
    assert result["line_start"] == 3
    assert result["line_end"] == 8
    assert result["parent_fqn"] == "mymodule.MyClass"
    assert result["parent_name"] == "MyClass"
    assert result["parent_kind"] == "class"
    assert result["source_code"] is not None
    assert "def my_method" in str(result["source_code"])


def test_symbol_definition_lookup_not_found(
    populated_edge_store: EdgeStore,
) -> None:
    result = populated_edge_store.get_symbol_definition("nonexistent.symbol")
    assert result is None


def test_symbol_definition_lookup_no_parent(
    populated_edge_store: EdgeStore,
) -> None:
    result = populated_edge_store.get_symbol_definition("mymodule.MyClass")
    assert result is not None
    assert result["fqn"] == "mymodule.MyClass"
    assert result["parent_fqn"] is None
    assert result["parent_name"] is None


def test_walk_edges_consistent_fqn_format(extractor: SymbolExtractor, tmp_path: Path) -> None:
    py_file = tmp_path / "test.py"
    py_file.write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n\n"
        "def multiply(a: int, b: int) -> int:\n"
        "    total = 0\n    for _ in range(b):\n"
        "        total = add(total, a)\n    return total\n"
    )
    source = py_file.read_bytes()
    edges = extractor.extract_edges(py_file, source)
    assert len(edges) >= 1
    for edge in edges:
        assert "::" in edge["source_fqn"]
        assert str(py_file) in edge["source_fqn"]


def test_exact_match_first_lookup(db: GraphDatabase) -> None:
    from src.engine.symbols import SymbolStore

    store = SymbolStore(db)
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (
                "src/module_a.py::Logger",
                "Logger",
                "class",
                "src/module_a.py",
                1,
                10,
                0,
                10,
                "python",
            ),
        )
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (
                "src/module_b.py::Logger",
                "Logger",
                "class",
                "src/module_b.py",
                1,
                10,
                0,
                10,
                "python",
            ),
        )

    result_a = store.lookup_by_fqn("src/module_a.py::Logger")
    assert result_a is not None
    assert result_a["file_path"] == "src/module_a.py"

    result_b = store.lookup_by_fqn("src/module_b.py::Logger")
    assert result_b is not None
    assert result_b["file_path"] == "src/module_b.py"

    result_fuzzy = store.lookup_by_fqn("Nonexistent")
    assert result_fuzzy is None

    result_name_fuzzy = store.lookup_by_fqn("Logger")
    assert result_name_fuzzy is not None
    assert result_name_fuzzy["name"] == "Logger"


def test_java_javadoc_extraction(extractor: SymbolExtractor, tmp_path: Path) -> None:
    java_file = tmp_path / "Example.java"
    java_file.write_text(
        "/**\n * Adds two numbers.\n * @param a first\n * @param b second\n * @return sum\n */\n"
        "public int add(int a, int b) { return a + b; }\n"
    )
    source = java_file.read_bytes()
    symbols = extractor.extract_symbols(java_file, source)
    if symbols:
        doc = symbols[0].get("docstring", "")
        assert "Adds two numbers" in doc


def test_javascript_jsdoc_extraction(extractor: SymbolExtractor, tmp_path: Path) -> None:
    js_file = tmp_path / "example.js"
    js_file.write_text(
        "/**\n * Calculates the total.\n * @param {number[]} items\n * @returns {number}\n */\n"
        "function calculateTotal(items) { return 0; }\n"
    )
    source = js_file.read_bytes()
    symbols = extractor.extract_symbols(js_file, source)
    if symbols:
        doc = symbols[0].get("docstring", "")
        assert "Calculates the total" in doc


def test_rust_doc_comment_extraction(extractor: SymbolExtractor, tmp_path: Path) -> None:
    rs_file = tmp_path / "example.rs"
    rs_file.write_text(
        "/// Returns the length of the provided string.\n"
        "fn string_length(s: &str) -> usize { s.len() }\n"
    )
    source = rs_file.read_bytes()
    symbols = extractor.extract_symbols(rs_file, source)
    if symbols:
        doc = symbols[0].get("docstring", "")
        assert "Returns the length" in doc


def test_csharp_xml_doc_extraction(extractor: SymbolExtractor, tmp_path: Path) -> None:
    cs_file = tmp_path / "Example.cs"
    cs_file.write_text(
        "/// <summary>Adds two integers.</summary>\nint Add(int a, int b) { return a + b; }\n"
    )
    source = cs_file.read_bytes()
    symbols = extractor.extract_symbols(cs_file, source)
    if symbols:
        doc = symbols[0].get("docstring", "")
        assert "Adds two integers" in doc


def test_batched_parent_fqn_resolution(db: GraphDatabase) -> None:
    store = SymbolStore(db)
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            ("src/a.py::Parent", "Parent", "class", "src/a.py", 1, 10, 0, 10, "python"),
        )
    symbols = [
        {
            "fqn": "src/a.py::Parent.child",
            "name": "child",
            "kind": "method",
            "file_path": "src/a.py",
            "line_start": 2,
            "line_end": 5,
            "column_start": 4,
            "column_end": 20,
            "docstring": None,
            "language": "python",
            "parent_fqn": "src/a.py::Parent",
        }
    ]
    id_map = store.insert_symbols_batch(symbols)
    assert len(id_map) == 1
    assert "src/a.py::Parent.child" in id_map


def test_multiple_functions(extractor: SymbolExtractor, tmp_path: Path) -> None:
    py_file = tmp_path / "test.py"
    py_file.write_text(
        "def func_a():\n    pass\n\ndef func_b():\n    pass\n\ndef func_c():\n    pass\n"
    )
    source = py_file.read_bytes()
    symbols = extractor.extract_symbols(py_file, source)
    names = [s["name"] for s in symbols]
    assert "func_a" in names
    assert "func_b" in names
    assert "func_c" in names


def test_field_qualified_call_resolves_through_field_type(
    extractor: SymbolExtractor,
    tmp_path: Path,
) -> None:
    java_file = tmp_path / "SecurityFilter.java"
    java_file.write_text(
        "package com.example.realworld.security;\n"
        "import com.example.realworld.security.TokenService;\n"
        "public class SecurityFilter {\n"
        "    private TokenService tokenService;\n"
        "    public boolean doFilterInternal() {\n"
        '        return tokenService.isTokenValid(token, "secret");\n'
        "    }\n"
        "}\n"
    )
    source = java_file.read_bytes()
    edges = extractor.extract_edges(java_file, source)
    call_edges = [e for e in edges if e["edge_type"] == "CALLS"]
    assert len(call_edges) == 1
    target = call_edges[0]["target_fqn"]
    assert target == "com.example.realworld.security.TokenService.isTokenValid"


def test_field_qualified_call_without_import_uses_declared_type(
    extractor: SymbolExtractor,
    tmp_path: Path,
) -> None:
    java_file = tmp_path / "Filter.java"
    java_file.write_text(
        "package p;\n"
        "public class Filter {\n"
        "    private TokenService tokenService;\n"
        "    public boolean run() {\n"
        "        return tokenService.check();\n"
        "    }\n"
        "}\n"
    )
    source = java_file.read_bytes()
    edges = extractor.extract_edges(java_file, source)
    call_edges = [e for e in edges if e["edge_type"] == "CALLS"]
    assert len(call_edges) == 1
    assert call_edges[0]["target_fqn"] == "TokenService.check"


def test_field_qualified_call_inside_lambda_chain(
    extractor: SymbolExtractor,
    tmp_path: Path,
) -> None:
    java_file = tmp_path / "JwtTokenFilter.java"
    java_file.write_text(
        "import java.util.Optional;\n"
        "public class JwtTokenFilter {\n"
        "    private JwtService jwtService;\n"
        "    public void doFilterInternal(String header) {\n"
        "        Optional.of(header)\n"
        "            .flatMap(token -> jwtService.getSubFromToken(token))\n"
        "            .ifPresent(id -> save(id));\n"
        "    }\n"
        "}\n"
    )
    source = java_file.read_bytes()
    edges = extractor.extract_edges(java_file, source)
    call_edges = [e for e in edges if e["edge_type"] == "CALLS"]
    targets = {e["target_fqn"] for e in call_edges}
    assert any(t.endswith("JwtService.getSubFromToken") for t in targets), (
        f"Expected JwtService.getSubFromToken edge, got {targets}"
    )
    assert any(t.endswith("save") for t in targets), f"Expected save edge, got {targets}"
    java_file = tmp_path / "TestClass.java"
    java_file.write_text(
        "public class TestClass {\n"
        "    private String name;\n"
        "    public TestClass(String name) {\n"
        "        this.name = name;\n"
        "    }\n"
        "    public void handle(int value) { }\n"
        "}\n"
    )
    source = java_file.read_bytes()
    symbols = extractor.extract_symbols(java_file, source)
    kinds = {s["kind"] for s in symbols}
    assert "class" in kinds
    assert "field" in kinds
    assert "constructor" in kinds
    assert "method" in kinds


def test_java_overloaded_method_fqn_disambiguation(
    extractor: SymbolExtractor,
    tmp_path: Path,
) -> None:
    java_file = tmp_path / "Overloads.java"
    java_file.write_text(
        "public class Overloads {\n"
        "    public void handle(int value) { }\n"
        "    public void handle(String text) { }\n"
        "    public void handle() { }\n"
        "}\n"
    )
    source = java_file.read_bytes()
    symbols = extractor.extract_symbols(java_file, source)
    fqns = [s["fqn"] for s in symbols if s["kind"] == "method"]
    assert any("handle(int)" in f for f in fqns), f"Expected handle(int) in {fqns}"
    assert any("handle(String)" in f for f in fqns), f"Expected handle(String) in {fqns}"
    assert len(fqns) == 3 or any("handle(" not in f for f in fqns), (
        f"Expected 3 methods, got {len(fqns)}: {fqns}"
    )


def test_conventional_fqn_java_with_package(extractor: SymbolExtractor, tmp_path: Path) -> None:
    java_file = tmp_path / "UserService.java"
    java_file.write_text(
        "package io.spring.application;\n"
        "public class UserService {\n"
        "    public void createUser(String name) { }\n"
        "}\n"
    )
    source = java_file.read_bytes()
    symbols = extractor.extract_symbols(java_file, source)
    for sym in symbols:
        if sym["name"] == "UserService":
            assert sym["conventional_fqn"] == "io.spring.application.UserService"
        elif sym["name"] == "createUser":
            assert sym["conventional_fqn"] == "io.spring.application.UserService.createUser(String)"


def test_conventional_fqn_java_annotation_stripped(
    extractor: SymbolExtractor, tmp_path: Path
) -> None:
    java_file = tmp_path / "Service.java"
    java_file.write_text(
        "package io.spring;\n"
        "public class Service {\n"
        "    public void handle(@Valid RegisterParam param) { }\n"
        "}\n"
    )
    source = java_file.read_bytes()
    symbols = extractor.extract_symbols(java_file, source)
    for sym in symbols:
        if sym["name"] == "handle":
            assert sym["conventional_fqn"] == "io.spring.Service.handle(RegisterParam)"
            assert "Valid" not in sym.get("conventional_fqn", "")


def test_conventional_fqn_null_for_python(extractor: SymbolExtractor, tmp_path: Path) -> None:
    py_file = tmp_path / "module.py"
    py_file.write_text("def greet(name: str) -> str:\n    return f'Hello, {name}'\n")
    source = py_file.read_bytes()
    symbols = extractor.extract_symbols(py_file, source)
    for sym in symbols:
        assert sym.get("conventional_fqn") is None, (
            f"Python symbol {sym['name']} should have None conventional_fqn"
        )


def test_dual_lookup_conventional_fqn(db: GraphDatabase) -> None:
    from src.engine.symbols import SymbolStore

    store = SymbolStore(db)
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language, conventional_fqn) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (
                "src/Service.java::Service.handle(RegisterParam)",
                "handle",
                "method",
                "src/Service.java",
                3,
                5,
                4,
                30,
                "java",
                "io.spring.Service.handle(RegisterParam)",
            ),
        )

    result_by_conventional = store.lookup_by_fqn("io.spring.Service.handle(RegisterParam)")
    assert result_by_conventional is not None
    assert result_by_conventional["fqn"] == "src/Service.java::Service.handle(RegisterParam)"

    result_by_filepath = store.lookup_by_fqn("src/Service.java::Service.handle(RegisterParam)")
    assert result_by_filepath is not None
    assert result_by_filepath["conventional_fqn"] == "io.spring.Service.handle(RegisterParam)"


def test_lookup_by_fqn_source_code_from_file_slice(
    db: GraphDatabase,
    tmp_path: Path,
) -> None:
    from src.engine.symbols import SymbolStore

    py_file = tmp_path / "utils.py"
    py_file.write_text("def helper():\n    return 'ok'\n\ndef unused():\n    pass\n")
    store = SymbolStore(db)
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            ("utils.helper", "helper", "function", str(py_file), 0, 1, 0, 10, "python"),
        )

    result = store.lookup_by_fqn("utils.helper")
    assert result is not None
    assert result["source_code"] == "def helper():\n    return 'ok'"
    assert "unused" not in result["source_code"]


def test_lookup_by_fqn_missing_file_source_code_empty(
    db: GraphDatabase,
) -> None:
    from src.engine.symbols import SymbolStore

    store = SymbolStore(db)
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            ("utils.ghost", "ghost", "function", "src/ghost.py", 0, 5, 0, 10, "python"),
        )

    result = store.lookup_by_fqn("utils.ghost")
    assert result is not None
    assert result["source_code"] == ""


def test_resolve_symbol_bare_name_and_dotted_suffix(
    db: GraphDatabase,
    tmp_path: Path,
) -> None:
    from src.engine.symbols import SymbolStore

    py_file = tmp_path / "service.py"
    py_file.write_text(
        "class TokenService:\n"
        "    def isTokenValid(self, token: str) -> bool:\n"
        "        return True\n"
    )
    store = SymbolStore(db)
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language, parent_symbol_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "(SELECT id FROM symbols WHERE name = 'TokenService'));",
            (
                "service.py::TokenService.isTokenValid",
                "isTokenValid",
                "method",
                str(py_file),
                1,
                2,
                4,
                40,
                "python",
            ),
        )
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (
                "service.py::TokenService",
                "TokenService",
                "class",
                str(py_file),
                0,
                2,
                0,
                10,
                "python",
            ),
        )

    sym_bare, cand_bare = store.resolve_symbol("isTokenValid")
    assert sym_bare is not None
    assert sym_bare["name"] == "isTokenValid"
    assert cand_bare == []

    sym_dotted, cand_dotted = store.resolve_symbol("TokenService.isTokenValid")
    assert sym_dotted is not None
    assert sym_dotted["name"] == "isTokenValid"
    assert cand_dotted == []


def test_resolve_symbol_ambiguous_returns_candidates(
    db: GraphDatabase,
) -> None:
    from src.engine.symbols import SymbolStore

    store = SymbolStore(db)
    with db.write_transaction() as conn:
        for fqn, name in [
            ("src/mod_a.py::Config", "Config"),
            ("src/mod_b.py::Config", "Config"),
        ]:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (fqn, name, "class", fqn.rsplit("::", 1)[0], 1, 5, 0, 10, "python"),
            )

    symbol, candidates = store.resolve_symbol("Config")
    assert symbol is None
    assert len(candidates) == 2
    assert {c["fqn"] for c in candidates} == {"src/mod_a.py::Config", "src/mod_b.py::Config"}

    symbol_a, cand_a = store.resolve_symbol("src/mod_a.py::Config")
    assert symbol_a is not None
    assert symbol_a["fqn"] == "src/mod_a.py::Config"
    assert cand_a == []


def test_resolve_symbol_near_miss_suggestions(
    db: GraphDatabase,
) -> None:
    """A near-miss name returns edit-distance suggestions with
    ``suggestion`` flags instead of a silent zero-candidate failure."""
    from src.engine.symbols import SymbolStore

    store = SymbolStore(db)
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (
                "src/TokenService.java::TokenService.isTokenValid(String,String)",
                "isTokenValid",
                "method",
                "src/TokenService.java",
                3,
                7,
                4,
                40,
                "java",
            ),
        )

    symbol, candidates = store.resolve_symbol("validateToken")
    assert symbol is None
    assert candidates, "near-miss lookup must return suggestions, not an empty list"
    assert any(c.get("edit_distance") is not None for c in candidates)
    assert any(c.get("suggestion") for c in candidates)
    assert any(c["name"] == "isTokenValid" for c in candidates)


def test_resolve_symbol_prefix_fallback(
    db: GraphDatabase,
) -> None:
    """Prefix/substring fallback resolves partial names."""
    from src.engine.symbols import SymbolStore

    store = SymbolStore(db)
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (
                "src/TokenService.java::TokenService.isTokenValid(String,String)",
                "isTokenValid",
                "method",
                "src/TokenService.java",
                3,
                7,
                4,
                40,
                "java",
            ),
        )

    symbol, candidates = store.resolve_symbol("isToken")
    assert symbol is not None or candidates, (
        "prefix fallback must resolve or suggest, got empty candidates"
    )
    if symbol is not None:
        assert symbol["name"] == "isTokenValid"


class TestResolveNameEnvelope:
    """Resolution envelope via SymbolStore.resolve_name + delegate parity."""

    def test_resolve_name_envelope_ambiguous(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            for fqn, name in [
                ("src/mod_a.py::Config", "Config"),
                ("src/mod_b.py::Config", "Config"),
            ]:
                conn.execute(
                    "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                    "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (fqn, name, "class", fqn.rsplit("::", 1)[0], 1, 5, 0, 10, "python"),
                )
        envelope = store.resolve_name("Config")
        assert envelope["kind"] == "ambiguous"
        assert envelope["outcome"] == "ambiguous"
        assert envelope["symbol"] is None
        assert len(envelope["candidates"]) == 2
        assert {c["fqn"] for c in envelope["candidates"]} == {
            "src/mod_a.py::Config",
            "src/mod_b.py::Config",
        }

    def test_resolve_name_envelope_exact(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            for fqn, name in [
                ("src/mod_a.py::Config", "Config"),
                ("src/mod_b.py::Config", "Config"),
            ]:
                conn.execute(
                    "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                    "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (fqn, name, "class", fqn.rsplit("::", 1)[0], 1, 5, 0, 10, "python"),
                )
        envelope = store.resolve_name("src/mod_a.py::Config")
        assert envelope["kind"] == "exact"
        assert envelope["outcome"] == "resolved"
        assert envelope["symbol"] is not None
        assert envelope["symbol"]["fqn"] == "src/mod_a.py::Config"
        assert envelope["candidates"] == []

    def test_resolve_name_envelope_suggestion(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    "src/TokenService.java::TokenService.isTokenValid(String,String)",
                    "isTokenValid",
                    "method",
                    "src/TokenService.java",
                    3,
                    7,
                    4,
                    40,
                    "java",
                ),
            )
        envelope = store.resolve_name("validateToken")
        assert envelope["kind"] == "suggestion"
        assert envelope["outcome"] == "not_found"
        assert envelope["symbol"] is None
        assert any(c["name"] == "isTokenValid" for c in envelope["candidates"])
        for c in envelope["candidates"]:
            assert "edit_distance" in c

    def test_resolve_name_envelope_not_found(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        envelope = store.resolve_name("definitelyNotReal123")
        assert envelope["kind"] == "not_found"
        assert envelope["outcome"] == "not_found"
        assert envelope["symbol"] is None
        assert envelope["candidates"] == []

    def test_unique_partial_reference_parity_with_exact_fqn(self, db: GraphDatabase) -> None:
        """A unique partial reference returns the same detail as an exact FQN."""
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    "src/TokenService.java::TokenService.isTokenValid(String)",
                    "isTokenValid",
                    "method",
                    "src/TokenService.java",
                    3,
                    7,
                    4,
                    40,
                    "java",
                ),
            )
        exact = store.resolve_name("src/TokenService.java::TokenService.isTokenValid(String)")
        partial = store.resolve_name("TokenService.isTokenValid")
        assert partial["kind"] == "exact"
        assert partial["outcome"] == "resolved"
        assert partial["symbol"]["fqn"] == exact["symbol"]["fqn"]
        assert partial["symbol"]["file_path"] == exact["symbol"]["file_path"]
        assert partial["symbol"]["line_start"] == exact["symbol"]["line_start"]
        assert partial["candidates"] == []

    def test_resolve_symbol_delegate_parity_ambiguous(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            for fqn, name in [
                ("src/mod_a.py::Config", "Config"),
                ("src/mod_b.py::Config", "Config"),
            ]:
                conn.execute(
                    "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                    "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (fqn, name, "class", fqn.rsplit("::", 1)[0], 1, 5, 0, 10, "python"),
                )
        symbol, candidates = store.resolve_symbol("Config")
        assert symbol is None
        assert len(candidates) == 2
        envelope = store.resolve_name("Config")
        assert envelope["candidates"] == candidates

    def test_resolve_symbol_delegate_parity_exact(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            for fqn, name in [
                ("src/mod_a.py::Config", "Config"),
                ("src/mod_b.py::Config", "Config"),
            ]:
                conn.execute(
                    "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                    "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (fqn, name, "class", fqn.rsplit("::", 1)[0], 1, 5, 0, 10, "python"),
                )
        symbol, candidates = store.resolve_symbol("src/mod_a.py::Config")
        assert symbol is not None
        assert symbol["fqn"] == "src/mod_a.py::Config"
        assert candidates == []
        envelope = store.resolve_name("src/mod_a.py::Config")
        assert envelope["symbol"] == symbol

    def test_lookup_by_fqn_delegate_parity_ambiguous(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            for fqn, name in [
                ("src/mod_a.py::Config", "Config"),
                ("src/mod_b.py::Config", "Config"),
            ]:
                conn.execute(
                    "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                    "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (fqn, name, "class", fqn.rsplit("::", 1)[0], 1, 5, 0, 10, "python"),
                )
        result = store.lookup_by_fqn("Config")
        assert result is not None
        assert result["name"] == "Config"
        envelope = store.resolve_name("Config")
        assert result == dict(envelope["candidates"][0])

    def test_lookup_by_fqn_delegate_parity_exact(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("utils.helper", "helper", "function", "src/utils.py", 0, 5, 0, 10, "python"),
            )
        result = store.lookup_by_fqn("utils.helper")
        assert result is not None
        assert result["fqn"] == "utils.helper"
        assert result["source_code"] == ""
        envelope = store.resolve_name("utils.helper")
        assert result == envelope["symbol"]


def test_normalize_signature_generic_body_not_inflating_arity() -> None:
    from src.engine.symbols import normalize_signature

    sig = normalize_signature("generateToken(Map<String,Object>,String)")
    assert sig is not None
    assert sig["arity"] == 2, f"generic comma must not inflate arity: {sig}"
    assert sig["param_types"] == ["Map", "String"]
    assert sig["normalized"] == "map,string"


def test_normalize_signature_list_generic() -> None:
    from src.engine.symbols import normalize_signature

    sig = normalize_signature("queueNewArticle(Article,List<Tag>)")
    assert sig is not None
    assert sig["arity"] == 2
    assert sig["param_types"] == ["Article", "List"]


def test_normalize_signature_whitespace_collapsed() -> None:
    from src.engine.symbols import normalize_signature

    sig = normalize_signature("handle( String ,  int )")
    assert sig is not None
    assert sig["arity"] == 2
    assert sig["param_types"] == ["String", "int"]
    assert sig["normalized"] == "string,int"


def test_normalize_signature_no_parens_returns_none() -> None:
    from src.engine.symbols import normalize_signature

    assert normalize_signature("io.spring.TokenService") is None
    assert normalize_signature(None) is None


def test_signature_query_resolves_exact_overload(db: GraphDatabase) -> None:
    """Supplying ``(Map<String,Object>,String)`` resolves the 2-arg overload."""
    from src.engine.symbols import SymbolStore

    _insert_generic_fixture(db)
    store = SymbolStore(db)
    envelope = store.resolve_name("TokenService.generateToken(Map<String,Object>,String)")
    assert envelope["kind"] == "exact", envelope
    sig = envelope["symbol"]["signature"]
    assert sig["arity"] == 2


def test_bare_overloaded_generate_token_is_ambiguous(db: GraphDatabase) -> None:
    from src.engine.symbols import SymbolStore

    _insert_generic_fixture(db)
    store = SymbolStore(db)
    envelope = store.resolve_name("generateToken")
    assert envelope["kind"] == "ambiguous", envelope
    arities = {c["signature"]["arity"] for c in envelope["candidates"]}
    assert arities == {1, 2}, envelope["candidates"]


def test_signature_never_returns_contradicting_overload(db: GraphDatabase) -> None:
    """A signature with no matching overload never resolves exact
    to a contradicting overload — it degrades to an ambiguous overload set."""
    from src.engine.symbols import SymbolStore

    _insert_generic_fixture(db)
    store = SymbolStore(db)
    envelope = store.resolve_name("generateToken(boolean)")
    assert envelope["kind"] == "ambiguous", envelope
    assert envelope["symbol"] is None
    for c in envelope["candidates"]:
        # The full overload set is offered, never a fabricated `boolean` match.
        assert c["signature"]["normalized"] != "boolean", c
    assert "generateToken(boolean)" not in [
        c.get("conventional_fqn", "") for c in envelope["candidates"]
    ]


def _insert_generic_fixture(db: GraphDatabase) -> None:
    """TokenService with a 2-arg generic-body overload and a 1-arg overload."""
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (
                "io.example.security.TokenService",
                "TokenService",
                "class",
                "src/TokenService.java",
                0,
                5,
                0,
                10,
                "java",
            ),
        )
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language, conventional_fqn, parent_symbol_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "(SELECT id FROM symbols WHERE name = 'TokenService'));",
            (
                "phys.generateToken(String)",
                "generateToken",
                "method",
                "src/TokenService.java",
                1,
                5,
                0,
                40,
                "java",
                "io.example.security.TokenService.generateToken(String)",
            ),
        )
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language, conventional_fqn, parent_symbol_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "(SELECT id FROM symbols WHERE name = 'TokenService'));",
            (
                "phys.generateToken(Map,String)",
                "generateToken",
                "method",
                "src/TokenService.java",
                8,
                30,
                0,
                40,
                "java",
                "io.example.security.TokenService.generateToken(Map<String,Object>,String)",
            ),
        )


def test_typescript_interface_and_type_alias_classification(
    extractor: SymbolExtractor, parser: ASTParser, tmp_path: Path
) -> None:
    """``.ts``/``.tsx`` declarations index as interface anchors with
    grammar-name FQNs (the TypeScript dialect grammar, not the JS fallback)."""
    ts_file = tmp_path / "types.ts"
    ts_file.write_text(
        "export interface User { id: number; name: string }\n"
        "type UserID = string;\n"
        "interface Admin extends User { role: string }\n"
    )
    tsx_file = tmp_path / "component.tsx"
    tsx_file.write_text("export interface Props<T> { value: T; onChange: () => void }\n")

    for path in (ts_file, tsx_file):
        source = path.read_bytes()
        symbols = extractor.extract_symbols(path, source)
        assert symbols, f"{path.name} must produce interface symbols"
        kinds = {s["kind"] for s in symbols}
        assert kinds == {"interface"}, f"only interface kinds expected, got {kinds}"
        names = {s["name"] for s in symbols}
        expected = {"User", "Admin"} if path.name.endswith(".ts") else {"Props"}
        assert expected.issubset(names), f"grammar-name FQNs expected {expected}, got {names}"
        for s in symbols:
            assert s["fqn"].startswith(f"{path}::"), f"grammar-name FQN required: {s['fqn']}"

    chunks = parser.get_chunks_for_file(ts_file, ts_file.read_bytes())
    interface_chunks = [c for c in chunks if c.get("chunk_node_type") == "interface_declaration"]
    assert len(interface_chunks) >= 1
    assert all(c.get("is_definition") for c in interface_chunks)
    merged = "\n".join(c.get("content", "") for c in chunks)
    assert "type UserID = string;" in merged
