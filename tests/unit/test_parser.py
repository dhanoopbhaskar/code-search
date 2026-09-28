from pathlib import Path

import pytest

from src.engine.config import Settings
from src.engine.parser import SUPPORTED_LANGUAGES, ASTParser


@pytest.fixture
def parser() -> ASTParser:
    return ASTParser()


def test_detect_language_python(parser: ASTParser) -> None:
    assert parser.detect_language(Path("test.py")) == "python"
    assert parser.detect_language(Path("src/module.py")) == "python"


def test_detect_language_javascript(parser: ASTParser) -> None:
    assert parser.detect_language(Path("app.js")) == "javascript"
    assert parser.detect_language(Path("component.jsx")) == "javascript"


def test_detect_language_typescript(parser: ASTParser) -> None:
    assert parser.detect_language(Path("app.ts")) == "typescript"
    assert parser.detect_language(Path("component.tsx")) == "typescript"


def test_detect_language_java(parser: ASTParser) -> None:
    assert parser.detect_language(Path("Main.java")) == "java"


def test_detect_language_csharp(parser: ASTParser) -> None:
    assert parser.detect_language(Path("Program.cs")) == "c_sharp"


def test_detect_language_cpp(parser: ASTParser) -> None:
    assert parser.detect_language(Path("main.cpp")) == "cpp"
    assert parser.detect_language(Path("header.hpp")) == "cpp"
    assert parser.detect_language(Path("source.c")) == "cpp"


def test_detect_language_unsupported(parser: ASTParser) -> None:
    assert parser.detect_language(Path("Gemfile")) is None
    assert parser.detect_language(Path("Makefile")) is None
    assert parser.detect_language(Path("script.lua")) is None


def test_supported_languages_complete() -> None:
    assert "python" in SUPPORTED_LANGUAGES
    assert "java" in SUPPORTED_LANGUAGES
    assert "javascript" in SUPPORTED_LANGUAGES
    assert "typescript" in SUPPORTED_LANGUAGES
    assert "c_sharp" in SUPPORTED_LANGUAGES
    assert "cpp" in SUPPORTED_LANGUAGES


def test_discover_files(parser: ASTParser, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "main.py").write_text("x = 1")
    (tmp_path / "src" / "utils.js").write_text("function f() {}")
    pkg_dir = tmp_path / "node_modules" / "pkg"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "index.js").write_text("module.exports = {}")
    pycache_dir = tmp_path / "__pycache__"
    pycache_dir.mkdir(parents=True)
    (pycache_dir / "main.cpython-311.pyc").write_text("")

    files = parser.discover_files(tmp_path)
    paths = [str(f.relative_to(tmp_path)) for f in files]
    assert "src/main.py" in paths
    assert "src/utils.js" in paths
    assert "node_modules/pkg/index.js" not in paths
    assert "__pycache__/main.cpython-311.pyc" not in paths


def test_discover_files_exclusion_patterns(parser: ASTParser, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x = 1")
    vendor_dir = tmp_path / "vendor"
    vendor_dir.mkdir(parents=True)
    (vendor_dir / "lib.py").write_text("y = 2")

    files = parser.discover_files(tmp_path, exclusion_patterns={"vendor"})
    paths = [str(f.relative_to(tmp_path)) for f in files]
    assert "src/main.py" in paths
    assert "vendor/lib.py" not in paths


def test_parse_file_nonexistent(parser: ASTParser) -> None:
    result = parser.parse_file(Path("/nonexistent/file.py"))
    assert result is None


def test_parse_file_unsupported_language(parser: ASTParser, tmp_path: Path) -> None:
    lua_file = tmp_path / "script.lua"
    lua_file.write_text("function hello() end")
    result = parser.parse_file(lua_file)
    assert result is None


def test_get_chunks_for_file(parser: ASTParser, tmp_path: Path) -> None:
    py_file = tmp_path / "test.py"
    py_file.write_text(
        "def greet(name):\n"
        '    """Say hello."""\n'
        '    return f"Hello, {name}"\n'
        "\nclass Calculator:\n"
        "    def add(self, a, b):\n"
        "        return a + b\n"
    )
    source = py_file.read_bytes()
    chunks = parser.get_chunks_for_file(py_file, source)
    assert len(chunks) >= 2
    assert any("def greet" in c["content"] for c in chunks)
    assert any("class Calculator" in c["content"] or "def add" in c["content"] for c in chunks)


def test_chunk_variable_declaration(parser: ASTParser, tmp_path: Path) -> None:
    py_file = tmp_path / "vars.py"
    py_file.write_text("MAX_RETRIES = 5\ntimeout = 30\n")
    source = py_file.read_bytes()
    chunks = parser.get_chunks_for_file(py_file, source)
    var_chunks = [c for c in chunks if c.get("chunk_node_type") == "variable_declaration"]
    assert var_chunks == []
    merged_content = "\n".join(c.get("content", "") for c in chunks)
    assert "MAX_RETRIES" in merged_content
    assert "timeout" in merged_content


def test_chunk_import_statement(parser: ASTParser, tmp_path: Path) -> None:
    py_file = tmp_path / "imports.py"
    py_file.write_text("import os\nfrom datetime import datetime\nimport json\n")
    source = py_file.read_bytes()
    chunks = parser.get_chunks_for_file(py_file, source)
    import_chunks = [c for c in chunks if c.get("chunk_node_type") == "import_statement"]
    assert len(import_chunks) == 0
    merged_content = "\n".join(c.get("content", "") for c in chunks)
    assert "import os" in merged_content
    assert "from datetime import datetime" in merged_content


def test_chunk_decorator(parser: ASTParser, tmp_path: Path) -> None:
    py_file = tmp_path / "decorators.py"
    py_file.write_text("@deprecated\ndef old_func():\n    pass\n")
    source = py_file.read_bytes()
    chunks = parser.get_chunks_for_file(py_file, source)
    decorator_chunks = [c for c in chunks if c.get("chunk_node_type") == "decorator"]
    assert len(decorator_chunks) >= 1


def test_chunk_comment(parser: ASTParser, tmp_path: Path) -> None:
    py_file = tmp_path / "comments.py"
    py_file.write_text("# This is a descriptive comment\n# That should be long enough\nx = 1\n")
    source = py_file.read_bytes()
    chunks = parser.get_chunks_for_file(py_file, source)
    comment_chunks = [c for c in chunks if c.get("chunk_node_type") == "comment"]
    assert len(comment_chunks) == 0
    merged_content = "\n".join(c.get("content", "") for c in chunks)
    assert "This is a descriptive comment" in merged_content


def test_chunk_type_alias(parser: ASTParser, tmp_path: Path) -> None:
    py_file = tmp_path / "type_aliases.py"
    py_file.write_text("type UserID = str\nx = 1\n")
    source = py_file.read_bytes()
    chunks = parser.get_chunks_for_file(py_file, source)
    alias_chunks = [c for c in chunks if c.get("chunk_node_type") == "type_alias"]
    assert alias_chunks == []
    merged_content = "\n".join(c.get("content", "") for c in chunks)
    assert "type UserID = str" in merged_content


def test_detect_language_go(parser: ASTParser) -> None:
    assert parser.detect_language(Path("main.go")) == "go"


def test_detect_language_rust(parser: ASTParser) -> None:
    assert parser.detect_language(Path("lib.rs")) == "rust"


def test_detect_language_ruby(parser: ASTParser) -> None:
    assert parser.detect_language(Path("script.rb")) == "ruby"


def test_detect_language_swift(parser: ASTParser) -> None:
    assert parser.detect_language(Path("main.swift")) == "swift"


def test_detect_language_kotlin(parser: ASTParser) -> None:
    assert parser.detect_language(Path("main.kt")) == "kotlin"
    assert parser.detect_language(Path("script.kts")) == "kotlin"


def test_detect_language_php(parser: ASTParser) -> None:
    assert parser.detect_language(Path("index.php")) == "php"


def test_detect_language_shell(parser: ASTParser) -> None:
    assert parser.detect_language(Path("script.sh")) == "shell"
    assert parser.detect_language(Path("script.bash")) == "shell"
    assert parser.detect_language(Path("script.zsh")) == "shell"


def test_detect_language_yaml(parser: ASTParser) -> None:
    assert parser.detect_language(Path("config.yaml")) == "yaml"
    assert parser.detect_language(Path("config.yml")) == "yaml"


def test_detect_language_toml(parser: ASTParser) -> None:
    assert parser.detect_language(Path("config.toml")) == "toml"


def test_warning_deduplication(parser: ASTParser) -> None:
    from src.engine.parser import _reset_warned_keys, _warned_keys

    _reset_warned_keys()
    assert len(_warned_keys) == 0
    _warned_keys.add("grammar:test_lang")
    assert "grammar:test_lang" in _warned_keys
    _reset_warned_keys()
    assert len(_warned_keys) == 0


def test_supported_languages_expanded() -> None:
    assert "python" in SUPPORTED_LANGUAGES
    assert "go" in SUPPORTED_LANGUAGES
    assert "rust" in SUPPORTED_LANGUAGES
    assert "ruby" in SUPPORTED_LANGUAGES
    assert "swift" in SUPPORTED_LANGUAGES
    assert "kotlin" in SUPPORTED_LANGUAGES
    assert "php" in SUPPORTED_LANGUAGES
    assert "shell" in SUPPORTED_LANGUAGES
    assert "yaml" in SUPPORTED_LANGUAGES
    assert "toml" in SUPPORTED_LANGUAGES


def test_detect_language_resource_xml(parser: ASTParser, tmp_path: Path) -> None:
    assert parser.detect_language(Path("test.xml"), resource_extensions=(".xml",)) == "xml"
    assert parser.detect_language(Path("test.sql"), resource_extensions=(".sql",)) == "sql"
    assert (
        parser.detect_language(Path("test.properties"), resource_extensions=(".properties",))
        == "properties"
    )
    assert parser.detect_language(Path("test.gradle"), resource_extensions=(".gradle",)) == "gradle"


def test_detect_language_resource_without_extensions(parser: ASTParser) -> None:
    assert parser.detect_language(Path("test.xml")) is None


def test_discover_files_includes_resources(parser: ASTParser, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "app.py").write_text("x = 1")
    (tmp_path / "src" / "config.xml").write_text("<root />")
    (tmp_path / "src" / "schema.sql").write_text("SELECT 1;")
    files = parser.discover_files(
        tmp_path,
        include_resources=True,
        resource_extensions=(".xml", ".sql"),
    )
    found = [f.name for f in files]
    assert "app.py" in found
    assert "config.xml" in found
    assert "schema.sql" in found


def test_discover_files_excludes_resources_by_default(parser: ASTParser, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "app.py").write_text("x = 1")
    (tmp_path / "src" / "config.xml").write_text("<root />")
    files = parser.discover_files(tmp_path)
    found = [f.name for f in files]
    assert "app.py" in found
    assert "config.xml" not in found


def test_discover_files_includes_extensionless_infra_by_name(
    parser: ASTParser, tmp_path: Path
) -> None:
    """Extension-less infra files (Dockerfile/Makefile) are discovered by
    name when resources are included — they carry no suffix, so the extension
    allowlist alone can never reach them."""
    (tmp_path / "Dockerfile").write_text("FROM eclipse-temurin:17-jdk")
    (tmp_path / "Makefile").write_text("build:\n\tmake")
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "app.py").write_text("x = 1")
    files = parser.discover_files(
        tmp_path,
        include_resources=True,
        resource_extensions=(".xml", ".sql"),
    )
    names = [f.name for f in files]
    assert "app.py" in names
    assert "Dockerfile" in names
    assert "Makefile" in names


def test_discover_files_excludes_extensionless_infra_by_default(
    parser: ASTParser, tmp_path: Path
) -> None:
    """Without ``include_resources``, extension-less infra files stay
    out of the index just like other non-code files."""
    (tmp_path / "Dockerfile").write_text("FROM eclipse-temurin:17-jdk")
    (tmp_path / "Makefile").write_text("build:\n\tmake")
    files = parser.discover_files(tmp_path)
    names = [f.name for f in files]
    assert "Dockerfile" not in names
    assert "Makefile" not in names


def test_detect_language_extensionless_infra(parser: ASTParser) -> None:
    """detect_language resolves extension-less infra names to a resource
    language token only when resource extensions are in play."""
    assert parser.detect_language(Path("Dockerfile"), resource_extensions=(".xml",)) == "dockerfile"
    assert parser.detect_language(Path("Makefile"), resource_extensions=(".xml",)) == "makefile"
    assert parser.detect_language(Path("Dockerfile")) is None
    assert parser.detect_language(Path("Makefile")) is None


def test_exclusion_patterns_exclude_build_output_dirs(parser: ASTParser, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "main.py").write_text("x = 1")
    for d in ("target", "out", "bin", ".gradle", ".next", ".output"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
        (tmp_path / d / "gen.py").write_text("x = 1")
    files = parser.discover_files(tmp_path)
    paths = [str(f.relative_to(tmp_path)) for f in files]
    assert "src/main.py" in paths
    for d in ("target", "out", "bin", ".gradle", ".next", ".output"):
        assert not any(p.startswith(f"{d}/") for p in paths), f"{d} should be excluded"


def test_build_generated_excluded_via_build(parser: ASTParser, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "main.py").write_text("x = 1")
    gen_dir = tmp_path / "build" / "generated"
    gen_dir.mkdir(parents=True)
    (gen_dir / "gen.py").write_text("x = 1")
    files = parser.discover_files(tmp_path)
    paths = [str(f.relative_to(tmp_path)) for f in files]
    assert "src/main.py" in paths
    assert not any(p.startswith("build/") for p in paths)


def test_prose_and_shell_not_discovered_by_default(parser: ASTParser, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "main.py").write_text("x = 1")
    (tmp_path / "README.md").write_text("# Readme")
    (tmp_path / "notes.txt").write_text("notes")
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / "script.sh").write_text("echo hi")
    files = parser.discover_files(tmp_path)
    names = [f.name for f in files]
    assert "main.py" in names
    assert "README.md" not in names
    assert "notes.txt" not in names
    assert "package-lock.json" not in names
    assert "script.sh" not in names


def test_prose_indexable_via_resource_extensions(parser: ASTParser, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "main.py").write_text("x = 1")
    (tmp_path / "README.md").write_text("# Readme")
    files = parser.discover_files(tmp_path, include_resources=True, resource_extensions=(".md",))
    names = [f.name for f in files]
    assert "main.py" in names
    assert "README.md" in names


def test_shell_indexable_when_index_prose(parser: ASTParser, tmp_path: Path) -> None:
    (tmp_path / "script.sh").write_text("echo hi")
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "main.py").write_text("x = 1")
    files = parser.discover_files(tmp_path, index_prose=True)
    names = [f.name for f in files]
    assert "script.sh" in names
    assert "main.py" in names


def test_nested_annotation_java_file_returns_chunk(parser: ASTParser, tmp_path: Path) -> None:
    java_file = tmp_path / "CheckSecurity.java"
    java_file.write_text(
        "@Target({ElementType.METHOD})\n"
        "@Retention(RetentionPolicy.RUNTIME)\n"
        "public @interface CheckSecurity {\n"
        '    String value() default "";\n'
        "}\n"
    )
    source = java_file.read_bytes()
    chunks = parser.get_chunks_for_file(java_file, source)
    assert len(chunks) >= 1
    assert any("CheckSecurity" in c["content"] for c in chunks)
    assert all(c["chunk_type"] == "ast" for c in chunks)


def test_annotated_record_declaration_returns_chunk(parser: ASTParser, tmp_path: Path) -> None:
    java_file = tmp_path / "Product.java"
    java_file.write_text(
        "@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)\n"
        "public record Product(String id, String name) {}\n"
    )
    source = java_file.read_bytes()
    chunks = parser.get_chunks_for_file(java_file, source)
    assert len(chunks) >= 1
    assert any("record Product" in c["content"] for c in chunks)


def test_annotated_declaration_descends_into_methods(parser: ASTParser, tmp_path: Path) -> None:
    java_file = tmp_path / "Controller.java"
    java_file.write_text(
        "@RestController\n"
        "public class Controller {\n"
        '    @GetMapping("/x")\n'
        "    public String get(@RequestParam String q) { return q; }\n"
        "}\n"
    )
    source = java_file.read_bytes()
    chunks = parser.get_chunks_for_file(java_file, source)
    assert len(chunks) >= 1
    assert any("get" in c["content"] for c in chunks)


def test_settings_defaults_index_prose_and_resource_extensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODE_SEARCH_INDEX_PROSE", raising=False)
    monkeypatch.delenv("CODE_SEARCH_RESOURCE_EXTENSIONS", raising=False)
    settings = Settings()
    assert settings.index_prose is True
    assert ".md" not in settings.resource_extensions
    assert ".txt" not in settings.resource_extensions
    assert ".xml" in settings.resource_extensions
    assert ".properties" in settings.resource_extensions


def test_per_definition_chunking_descends_into_method_bodies(
    parser: ASTParser, tmp_path: Path
) -> None:
    py_file = tmp_path / "svc.py"
    py_file.write_text(
        "class ArticleService:\n"
        "    def get_by_slug(self, slug):\n"
        "        return self._repo.find(slug)\n"
        "    def delete(self, slug):\n"
        "        self._repo.remove(slug)\n"
    )
    source = py_file.read_bytes()
    chunks = parser.get_chunks_for_file(py_file, source)
    def_chunks = [c for c in chunks if c.get("is_definition")]
    assert any(c["chunk_node_type"] == "class_definition" for c in def_chunks)
    method_chunks = [
        c
        for c in def_chunks
        if c["chunk_node_type"] in ("function_definition", "method_definition")
    ]
    assert len(method_chunks) >= 2
    assert any("get_by_slug" in c["content"] for c in method_chunks)
    assert any("delete" in c["content"] for c in method_chunks)


def test_per_definition_chunking_java_class(parser: ASTParser, tmp_path: Path) -> None:
    java_file = tmp_path / "TokenService.java"
    java_file.write_text(
        "public class TokenService {\n"
        "    public boolean isTokenValid(String token, String secret) {\n"
        "        return token != null;\n"
        "    }\n"
        "}\n"
    )
    source = java_file.read_bytes()
    chunks = parser.get_chunks_for_file(java_file, source)
    def_chunks = [c for c in chunks if c.get("is_definition")]
    method_chunks = [
        c for c in def_chunks if c["chunk_node_type"] in ("method_declaration", "method_definition")
    ]
    assert any(c["chunk_node_type"] == "class_declaration" for c in def_chunks)
    assert any("isTokenValid" in c["content"] for c in method_chunks)
    for c in method_chunks:
        assert c["is_definition"] is True


def test_us2_no_bare_field_declaration_chunks(parser: ASTParser) -> None:
    py_file = Path(__file__).parent.parent / "fixtures" / "boilerplate_merge" / "UserProfile.java"
    source = py_file.read_bytes()
    chunks = parser.get_chunks_for_file(py_file, source)
    field_chunks = [c for c in chunks if c.get("chunk_node_type") == "field_declaration"]
    assert field_chunks == []
    class_chunks = [c for c in chunks if c.get("chunk_node_type") == "class_declaration"]
    assert len(class_chunks) == 1
    class_chunk = class_chunks[0]
    assert class_chunk["is_definition"] is True
    assert "private Long id" in class_chunk["content"]
    assert "private String name" in class_chunk["content"]


def test_us2_no_bare_import_chunks(parser: ASTParser) -> None:
    py_file = Path(__file__).parent.parent / "fixtures" / "boilerplate_merge" / "user_profile.py"
    source = py_file.read_bytes()
    chunks = parser.get_chunks_for_file(py_file, source)
    import_chunks = [c for c in chunks if c.get("chunk_node_type") == "import_statement"]
    assert import_chunks == []
    region_chunks = [c for c in chunks if c.get("chunk_node_type") == "module"]
    assert len(region_chunks) == 1
    assert "import datetime" in region_chunks[0]["content"]
    assert region_chunks[0]["is_definition"] is False


def test_us2_python_comments_merge_into_class(parser: ASTParser) -> None:
    py_file = Path(__file__).parent.parent / "fixtures" / "boilerplate_merge" / "user_profile.py"
    source = py_file.read_bytes()
    chunks = parser.get_chunks_for_file(py_file, source)
    comment_chunks = [c for c in chunks if c.get("chunk_node_type") == "comment"]
    assert comment_chunks == []
    class_chunks = [c for c in chunks if c.get("chunk_node_type") == "class_definition"]
    assert len(class_chunks) == 1
    assert class_chunks[0]["is_definition"] is True
    assert "Unique identifier assigned on creation" in class_chunks[0]["content"]


def test_us2_definition_anchors_keep_is_definition(parser: ASTParser) -> None:
    py_file = Path(__file__).parent.parent / "fixtures" / "boilerplate_merge" / "UserProfile.java"
    source = py_file.read_bytes()
    chunks = parser.get_chunks_for_file(py_file, source)
    method_chunks = [c for c in chunks if c.get("chunk_node_type") == "method_declaration"]
    assert len(method_chunks) >= 2
    for chunk in method_chunks:
        assert chunk["is_definition"] is True


def test_us2_boilerplate_file_coalesces_into_one_region(parser: ASTParser) -> None:
    py_file = Path(__file__).parent.parent / "fixtures" / "boilerplate_merge" / "__init__.py"
    source = py_file.read_bytes()
    chunks = parser.get_chunks_for_file(py_file, source)
    import_chunks = [c for c in chunks if c.get("chunk_node_type") == "import_statement"]
    assert import_chunks == []
    region_chunks = [c for c in chunks if c.get("chunk_node_type") == "module"]
    assert len(region_chunks) == 1
    assert region_chunks[0]["is_definition"] is False
    assert "from .auth import authenticate" in region_chunks[0]["content"]


def test_grammar_less_file_yields_no_parser_chunks(parser: ASTParser) -> None:
    txt_file = Path(__file__).parent.parent / "fixtures" / "boilerplate_merge" / "notes.txt"
    source = txt_file.read_bytes()
    chunks = parser.get_chunks_for_file(txt_file, source)
    assert chunks == []


def test_us3_expression_and_variable_leaves_merge_into_enclosing_definition(
    parser: ASTParser,
) -> None:
    """Bare expressions never surface as standalone chunks.

    In-function ``trigger()`` / ``cache = build()`` must merge into the
    enclosing definition, and top-level assignments must coalesce into a
    single module region instead of staying standalone variable declarations.
    """
    py_file = Path("m.py")
    source = (
        b"def run():\n"
        b"    trigger()\n"
        b"    cache = build()\n"
        b"    return cache\n"
        b"\n"
        b"A = build_a()\n"
        b"B = build_b()\n"
    )
    chunks = parser.get_chunks_for_file(py_file, source)
    standalone = [
        c
        for c in chunks
        if c.get("chunk_node_type") in ("expression_statement", "variable_declaration")
    ]
    assert standalone == []
    defs = [c for c in chunks if c.get("chunk_node_type") == "function_definition"]
    assert len(defs) == 1
    assert "trigger()" in defs[0]["content"]
    assert "cache = build()" in defs[0]["content"]
    region = [c for c in chunks if c.get("chunk_node_type") == "module"]
    assert any(
        "A = build_a()" in c["content"] and "B = build_b()" in c["content"] for c in region
    ), "top-level assignments must coalesce into a module region"


def test_us3_expression_merge_bounded_by_chunk_target_chars() -> None:
    """With a tiny ``chunk_target_chars``, leaves never leak standalone —
    the whole raw statement region coalesces instead of overflowing."""
    parser_small = ASTParser(settings=Settings(chunk_target_chars=20))
    py_file = Path("m.py")
    source = b"def run():\n    trigger()\n    cache = build()\n    return cache\n"
    chunks = parser_small.get_chunks_for_file(py_file, source)
    standalone = [
        c
        for c in chunks
        if c.get("chunk_node_type") in ("expression_statement", "variable_declaration")
    ]
    assert standalone == []
    merged_content = "\n".join(c.get("content", "") for c in chunks)
    assert "trigger()" in merged_content
    assert "cache = build()" in merged_content
    defs = [c for c in chunks if c.get("chunk_node_type") == "function_definition"]
    assert len(defs) == 1
    assert defs[0]["is_definition"] is True
