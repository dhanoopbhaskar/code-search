"""Unit tests for the semantic representation builder.

Covers the pure derivation of a chunk's enclosing context and the bounded embed
text: method chunks name their declaring type and module, a type chunk excludes
its own name, free functions fall back to the module, non-code chunks get no
code-type chain, and recomputation is byte-identical regardless of symbol
ordering.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.engine.embed_representation import (
    REPRESENTATION_SCHEME_VERSION,
    EnclosingContext,
    build_embed_text,
    derive_enclosing_context,
)

_PATH = "src/main/java/com/acme/orders/OrderService.java"


def _symbol(
    fqn: str,
    name: str,
    *,
    parent: str | None = None,
    kind: str = "class",
    start: int = 1,
    end: int = 100,
    file_path: str = _PATH,
) -> dict[str, Any]:
    return {
        "fqn": fqn,
        "name": name,
        "kind": kind,
        "file_path": file_path,
        "line_start": start,
        "line_end": end,
        "parent_fqn": parent,
    }


def _chunk(
    content: str,
    *,
    start: int,
    end: int | None = None,
    file_path: str = _PATH,
    chunk_type: str = "ast",
    content_type: str = "code",
) -> dict[str, Any]:
    return {
        "file_path": file_path,
        "line_start": start,
        "line_end": end if end is not None else start + 5,
        "content": content,
        "chunk_type": chunk_type,
        "content_type": content_type,
    }


def _method_fixture() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cls_fqn = f"{_PATH}::OrderService"
    method_fqn = f"{_PATH}::OrderService.save"
    symbols = [
        _symbol(cls_fqn, "OrderService", start=1, end=100),
        _symbol(method_fqn, "save", parent=cls_fqn, kind="method", start=10, end=20),
    ]
    chunk = _chunk("public void save() {\n    repository.persist();\n}", start=10, end=20)
    return chunk, symbols


# --- Core derivation ----------------------------------------------------------


def test_scheme_version_constant_is_positive_int() -> None:
    assert isinstance(REPRESENTATION_SCHEME_VERSION, int)
    assert REPRESENTATION_SCHEME_VERSION >= 1


def test_method_chunk_names_class_and_module() -> None:
    chunk, symbols = _method_fixture()
    context = derive_enclosing_context(chunk, symbols)
    assert context.module == "orders"
    assert context.chain == ("OrderService",)
    assert context.kind == "code"


def test_method_embed_text_contains_module_and_declaring_type() -> None:
    chunk, symbols = _method_fixture()
    context = derive_enclosing_context(chunk, symbols)
    text = build_embed_text(context, chunk["content"], budget=2000)
    assert "OrderService" in text
    assert "orders" in text
    assert chunk["content"] in text


def test_class_chunk_excludes_its_own_name_from_chain() -> None:
    cls_fqn = f"{_PATH}::OrderService"
    symbols = [_symbol(cls_fqn, "OrderService", start=1, end=100)]
    chunk = _chunk("public class OrderService {\n}", start=1, end=100)
    context = derive_enclosing_context(chunk, symbols)
    assert context.chain == ()
    assert context.module == "orders"


def test_identical_bodies_in_different_classes_produce_different_text() -> None:
    body = "public void handle() {\n    doWork();\n}"
    symbols_a = [
        _symbol("a/Alpha.java::Alpha", "Alpha", file_path="a/Alpha.java"),
        _symbol(
            "a/Alpha.java::Alpha.handle",
            "handle",
            parent="a/Alpha.java::Alpha",
            kind="method",
            file_path="a/Alpha.java",
        ),
    ]
    symbols_b = [
        _symbol("b/Beta.java::Beta", "Beta", file_path="b/Beta.java"),
        _symbol(
            "b/Beta.java::Beta.handle",
            "handle",
            parent="b/Beta.java::Beta",
            kind="method",
            file_path="b/Beta.java",
        ),
    ]
    chunk_a = _chunk(body, start=10, file_path="a/Alpha.java")
    chunk_b = _chunk(body, start=10, file_path="b/Beta.java")
    text_a = build_embed_text(derive_enclosing_context(chunk_a, symbols_a), body, budget=2000)
    text_b = build_embed_text(derive_enclosing_context(chunk_b, symbols_b), body, budget=2000)
    assert text_a != text_b


# --- Uniform context across languages and chunk kinds -------------------------


@pytest.mark.parametrize(
    ("language", "path", "module", "cls", "method"),
    [
        ("python", "app/services/order.py", "services", "OrderService", "save"),
        ("java", "OrderService.java", "OrderService", "OrderService", "save"),
        ("typescript", "order.service.ts", "order.service", "OrderService", "save"),
        ("csharp", "OrderService.cs", "OrderService", "OrderService", "Save"),
        ("cpp", "order_service.cpp", "order_service", "OrderService", "save"),
    ],
)
def test_method_chunk_context_across_languages(
    language: str, path: str, module: str, cls: str, method: str
) -> None:
    cls_fqn = f"{path}::{cls}"
    method_fqn = f"{cls_fqn}.{method}"
    symbols = [
        _symbol(cls_fqn, cls, file_path=path, start=1, end=200),
        _symbol(
            method_fqn, method, parent=cls_fqn, kind="method", file_path=path, start=10, end=20
        ),
    ]
    chunk = _chunk("void body() {}", start=10, end=20, file_path=path)
    context = derive_enclosing_context(chunk, symbols)
    assert context.chain == (cls,), language
    assert context.module == module, language


def test_free_function_falls_back_to_module() -> None:
    path = "app/util.py"
    symbols = [_symbol(f"{path}::helper", "helper", kind="function", file_path=path)]
    chunk = _chunk("def helper():\n    pass", start=1, file_path=path)
    context = derive_enclosing_context(chunk, symbols)
    assert context.chain == ()
    assert context.module == "app"
    text = build_embed_text(context, chunk["content"], budget=2000)
    assert "app" in text
    assert text.strip() != ""


def test_nested_class_member_carries_full_chain() -> None:
    path = "app/nested.ts"
    outer = f"{path}::Outer"
    inner = f"{outer}.Inner"
    method = f"{inner}.run"
    symbols = [
        _symbol(outer, "Outer", file_path=path, start=1, end=200),
        _symbol(inner, "Inner", parent=outer, file_path=path, start=20, end=100),
        _symbol(method, "run", parent=inner, kind="method", file_path=path, start=30, end=40),
    ]
    chunk = _chunk("run() { work(); }", start=30, end=40, file_path=path)
    context = derive_enclosing_context(chunk, symbols)
    assert context.chain == ("Outer", "Inner")


def test_interface_and_abstract_method_context() -> None:
    path = "app/Port.java"
    iface = f"{path}::Port"
    method = f"{iface}.execute"
    symbols = [
        _symbol(iface, "Port", kind="interface", file_path=path),
        _symbol(method, "execute", parent=iface, kind="method", file_path=path, start=5, end=5),
    ]
    chunk = _chunk("void execute();", start=5, end=5, file_path=path)
    assert derive_enclosing_context(chunk, symbols).chain == ("Port",)


def test_enum_and_record_method_context() -> None:
    path = "app/Status.java"
    enum = f"{path}::Status"
    method = f"{enum}.label"
    symbols = [
        _symbol(enum, "Status", kind="enum", file_path=path),
        _symbol(method, "label", parent=enum, kind="method", file_path=path, start=8, end=9),
    ]
    chunk = _chunk('String label() { return "x"; }', start=8, end=9, file_path=path)
    assert derive_enclosing_context(chunk, symbols).chain == ("Status",)


def test_config_chunk_gets_no_code_type_context() -> None:
    path = "config/application.properties"
    chunk = _chunk(
        "spring.datasource.url=jdbc:mysql://db/app",
        start=1,
        file_path=path,
        chunk_type="resource",
        content_type="config",
    )
    context = derive_enclosing_context(chunk, [])
    assert context.chain == ()
    assert context.module == "config"
    assert context.kind == "config"
    text = build_embed_text(context, chunk["content"], budget=2000)
    assert "config" in text


def test_resource_and_docs_chunks_get_no_code_type_context() -> None:
    resource = _chunk(
        "CREATE TABLE t (id INT);",
        start=1,
        file_path="db/migration/V1__init.sql",
        chunk_type="resource",
        content_type="config",
    )
    docs = _chunk(
        "# Guide\nHow to use the service.",
        start=1,
        file_path="docs/guide.md",
        chunk_type="raw_text",
        content_type="docs",
    )
    for chunk, kind, module in (
        (resource, "config", "migration"),
        (docs, "docs", "docs"),
    ):
        context = derive_enclosing_context(chunk, [])
        assert context.chain == ()
        assert context.kind == kind
        assert context.module == module


# --- Truncation precedence ----------------------------------------------------


def test_build_embed_text_keeps_content_when_prefix_truncated() -> None:
    context = EnclosingContext(
        module="a/very/long/module/path.py", chain=("Outer", "Inner"), kind="code"
    )
    content = "def method():\n    return 1"
    budget = len(content) + 5
    text = build_embed_text(context, content, budget=budget)
    assert content in text
    assert len(text) <= budget


def test_build_embed_text_truncates_content_head_first_when_content_exceeds_budget() -> None:
    context = EnclosingContext(module="m.py", chain=(), kind="code")
    content = "x" * 500
    text = build_embed_text(context, content, budget=100)
    assert len(text) == 100
    assert text == content[:100]


def test_build_embed_text_handles_empty_content_and_no_context() -> None:
    empty = build_embed_text(EnclosingContext(module="m.py", chain=(), kind="code"), "", budget=100)
    assert isinstance(empty, str)
    no_context = build_embed_text(None, "body", budget=100)
    assert no_context == "body"


# --- Determinism --------------------------------------------------------------


def test_derivation_is_order_independent() -> None:
    chunk, symbols = _method_fixture()
    forward = derive_enclosing_context(chunk, symbols)
    reverse = derive_enclosing_context(chunk, list(reversed(symbols)))
    assert forward == reverse
    assert build_embed_text(forward, chunk["content"], 2000) == build_embed_text(
        reverse, chunk["content"], 2000
    )


def test_module_identity_is_checkout_independent() -> None:
    """The module identity is the immediate package name, so absolute and
    relative paths (different checkouts) yield the same representation."""
    relative = _chunk("def f():\n    pass", start=1, file_path="src/app/orders/svc.py")
    absolute = _chunk("def f():\n    pass", start=1, file_path="/home/u/proj/src/app/orders/svc.py")
    symbols = [_symbol("orders/svc.py::f", "f", kind="function", file_path="orders/svc.py")]
    ctx_relative = derive_enclosing_context(relative, symbols)
    ctx_absolute = derive_enclosing_context(absolute, symbols)
    assert ctx_relative.module == ctx_absolute.module == "orders"


def test_repeated_computation_is_byte_identical() -> None:
    path = "app/nested.ts"
    outer = f"{path}::Outer"
    inner = f"{outer}.Inner"
    method = f"{inner}.run"
    symbols = [
        _symbol(outer, "Outer", file_path=path, start=1, end=200),
        _symbol(inner, "Inner", parent=outer, file_path=path, start=20, end=100),
        _symbol(method, "run", parent=inner, kind="method", file_path=path, start=30, end=40),
    ]
    chunk = _chunk("run() { work(); }", start=30, end=40, file_path=path)
    first = build_embed_text(derive_enclosing_context(chunk, symbols), chunk["content"], 2000)
    for _ in range(5):
        again = build_embed_text(derive_enclosing_context(chunk, symbols), chunk["content"], 2000)
        assert again == first
