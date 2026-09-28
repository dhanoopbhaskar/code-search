"""AST-based symbol extraction and SQLite-backed symbol store.

Walks tree-sitter ASTs to discover function/method/class/interface/enum
definitions, their FQN-qualified hierarchy, call-graph edges, import
relationships, and inheritance edges.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, cast

from src.engine.config import Settings
from src.engine.graph import (
    GraphDatabase,
    _candidate_summary,
    _rank_symbol_candidates,
    _resolve_symbol_candidates,
    read_source_slice,
)
from src.engine.parser import LANGUAGE_MAP, ASTParser
from src.engine.symbol_resolution import (
    ResolutionResult,
    normalize_signature,
    outcome_for_kind,
    parse_reference,
    resolve_with_signature,
)

logger = logging.getLogger(__name__)

_IMPORT_NODES = {"import_statement", "import_from_statement", "call_expression"}
_REFERENCE_PATTERNS: set[str] = {
    "identifier",
    "attribute",
    "subscript",
}

# Definition nodes carrying a type declaration (used by symbol and edge walkers).
_DEFINITION_NODES: set[str] = {
    "function_definition",
    "method_definition",
    "class_definition",
    "class_declaration",
    "interface_declaration",
    "enum_declaration",
    "method_declaration",
    "constructor_declaration",
    "field_declaration",
    "class_specifier",
    "struct_specifier",
    "function_declaration",
    "method",
    "method_signature",
    "abstract_method_signature",
    "class",
}

# Object-creation nodes that may carry an inline anonymous class body. A Java
# ``new Animal() { ... }`` is a class declaration without a name; it is
# extracted as a synthetic type so its INHERITS edge and methods are reachable
# by implementation lookup instead of being silently dropped.
_ANONYMOUS_CLASS_NODES: set[str] = {"object_creation_expression"}

# Type-declaration nodes whose base clauses are read into INHERITS edges.
_INHERITANCE_DEF_NODES: set[str] = {
    "class_definition",
    "class_declaration",
    "interface_declaration",
    "class_specifier",
    "struct_specifier",
    "class",
}

# Clause nodes that directly hold (or wrap) a base-type reference.
_INHERITANCE_CLAUSE_NODES: set[str] = {
    "argument_list",
    "superclass",
    "super_interfaces",
    "extends_interfaces",
    "class_heritage",
    "extends_type_clause",
    "base_list",
    "base_class_clause",
    "delegation_specifiers",
}

# Wrapper nodes the base-clause reader drills through to the leaf name.
_INHERITANCE_WRAPPER_NODES: set[str] = {
    "type_list",
    "base_list",
    "class_heritage",
    "extends_clause",
    "implements_clause",
    "extends_type_clause",
    "super_interfaces",
    "extends_interfaces",
    "base_class_clause",
    "delegation_specifiers",
    "delegation_specifier",
    "constructor_invocation",
    "user_type",
    "generic_type",
    "type_arguments",
}

# Leaf nodes whose text is a base-type name (possibly qualified/generic).
_INHERITANCE_LEAF_NODES: set[str] = {
    "identifier",
    "type_identifier",
    "scoped_type_identifier",
    "qualified_name",
    "generic_name",
    "attribute",
    "constant",
    "field_identifier",
}


def build_symbol_fqn(
    file_path: str,
    parent_fqn: str | None,
    name: str,
    param_types: list[str] | None = None,
) -> str:
    """Unified symbol FQN construction shared by symbol and edge extraction.

    Produces the ``{file_path}::{parent_chain}.{name}({params})`` form so that
    edge ``source_fqn``/``target_fqn`` values byte-match the ``symbols.fqn``
    keys in ``id_map`` — fixing the source-side silent drop where the two
    independent constructions disagreed.
    """
    if parent_fqn:
        parent_part = parent_fqn.split("::", 1)[1] if "::" in parent_fqn else parent_fqn
        fqn = f"{file_path}::{parent_part}.{name}"
    else:
        fqn = f"{file_path}::{name}"
    if param_types:
        fqn = f"{fqn}({','.join(param_types)})"
    return fqn


def _attach_row_signature(row: dict[str, Any]) -> dict[str, Any]:
    """Return *row* with a parsed ``signature`` object attached.

    Parses the stored signature from the row's ``conventional_fqn`` (falling
    back to ``fqn``) using :func:`normalize_signature`. Symbols without a
    ``(params)`` part (classes, fields) keep no ``signature`` key.
    """
    out = dict(row)
    for candidate in (out.get("conventional_fqn"), out.get("fqn")):
        if not candidate:
            continue
        sig = normalize_signature(candidate)
        if sig is not None:
            out["signature"] = sig
            break
    return out


class SymbolExtractor:
    """Extracts symbols (definitions) and edges (calls, imports, inheritance) from ASTs."""

    def __init__(self, parser: ASTParser) -> None:
        """Initialize the extractor with the parser used to build ASTs.

        Args:
            parser: The :class:`~src.engine.parser.ASTParser` used for both
                parsing source files and reading node text/ranges.
        """
        self._parser = parser

    @staticmethod
    def _extract_package_name(root_node: Any, source_bytes: bytes) -> str | None:
        """Extract the Java package name from the AST root node."""
        try:
            for child in root_node.children:
                if child.type == "package_declaration":
                    for sub in child.children:
                        if sub.type == "scoped_identifier" or sub.type == "identifier":
                            return ASTParser.get_node_text(sub, source_bytes)
                    text = ASTParser.get_node_text(child, source_bytes)
                    if text:
                        return text.replace("package ", "").replace(";", "").strip()
        except Exception:
            pass
        return None

    def extract_symbols(self, file_path: Path, source_bytes: bytes) -> list[dict[str, Any]]:
        """Return all symbol definitions found in *file_path*."""
        tree = self._parser.parse_file(file_path, source_bytes=source_bytes)
        if tree is None:
            return []
        root_node = tree.root_node
        package_name = self._extract_package_name(root_node, source_bytes)
        symbols: list[dict[str, Any]] = []
        self._walk_node(
            root_node, source_bytes, file_path, symbols, parent_fqn=None, package_name=package_name
        )
        return symbols

    def _walk_node(
        self,
        node: Any,
        source_bytes: bytes,
        file_path: Path,
        symbols: list[dict[str, Any]],
        parent_fqn: str | None = None,
        package_name: str | None = None,
        declared_rules: str = "",
    ) -> None:
        """Recursively walk the AST, collecting definition nodes.

        *declared_rules* carries rule text from an enclosing Python
        ``decorated_definition`` into the wrapped definition symbol.
        """
        try:
            node_type = node.type
        except Exception:
            return

        if node_type in _DEFINITION_NODES:
            sym = self._extract_symbol(
                node,
                source_bytes,
                file_path,
                node_type,
                parent_fqn,
                package_name=package_name,
                declared_rules=declared_rules,
            )
            if sym is not None:
                symbols.append(sym)
                new_parent = sym["fqn"]
                try:
                    for child in node.children:
                        self._walk_node(
                            child,
                            source_bytes,
                            file_path,
                            symbols,
                            new_parent,
                            package_name=package_name,
                        )
                except Exception:
                    pass
                return

        if node_type == "decorated_definition":
            rules = self._parser._decorator_rules(node, source_bytes)
            try:
                for child in node.children:
                    self._walk_node(
                        child,
                        source_bytes,
                        file_path,
                        symbols,
                        parent_fqn,
                        package_name=package_name,
                        declared_rules=rules,
                    )
            except Exception:
                pass
            return

        if node_type in _ANONYMOUS_CLASS_NODES and self._has_class_body(node):
            anon = self._extract_anonymous_symbol(node, source_bytes, file_path, parent_fqn)
            if anon is not None:
                symbols.append(anon)
                try:
                    for child in node.children:
                        self._walk_node(
                            child,
                            source_bytes,
                            file_path,
                            symbols,
                            anon["fqn"],
                            package_name=package_name,
                        )
                except Exception:
                    pass
                return

        try:
            for child in node.children:
                self._walk_node(
                    child, source_bytes, file_path, symbols, parent_fqn, package_name=package_name
                )
        except Exception:
            pass

    def extract_edges(
        self,
        file_path: Path,
        source_bytes: bytes,
        symbol_catalog: dict[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        """Extract call, import, and inheritance edges from *file_path*.

        Uses a two-pass approach: first collects all IMPORTS edges to build
        an import map (unqualified name → FQN), then resolves CALLS edge
        target names against that map and the optional *symbol_catalog*
        for cross-file resolution.
        """
        tree = self._parser.parse_file(file_path, source_bytes=source_bytes)
        if tree is None:
            return []
        root_node = tree.root_node

        # Pass 1: collect only IMPORTS edges
        import_edges: list[dict[str, Any]] = []
        import_fqns: set[str] = set()
        self._walk_imports(root_node, source_bytes, file_path, import_edges, import_fqns)

        # Build import map: simple_name -> FQN
        import_map = self._build_import_map(import_edges)

        # Pass 2: collect CALLS and INHERITS edges with import context
        edges: list[dict[str, Any]] = []
        self._walk_calls_and_inherits(
            root_node,
            source_bytes,
            file_path,
            edges,
            import_map=import_map,
            symbol_catalog=symbol_catalog,
        )

        return import_edges + edges

    def _walk_edges(
        self,
        node: Any,
        source_bytes: bytes,
        file_path: Path,
        edges: list[dict[str, Any]],
        current_fqn: str | None = None,
    ) -> None:
        """Recursively walk the AST, collecting call/import/inheritance edges."""
        try:
            node_type = node.type
        except Exception:
            return

        if node_type in _DEFINITION_NODES:
            name_node = self._find_name_node(node)
            if name_node is not None:
                name = self._parser.get_node_text(name_node, source_bytes)
                if name:
                    new_fqn = f"{current_fqn}.{name}" if current_fqn else f"{file_path}::{name}"
                    if node_type in _INHERITANCE_DEF_NODES:
                        self._extract_inheritance_edges(
                            node, source_bytes, edges, new_fqn, import_map=None
                        )
                    try:
                        for child in node.children:
                            self._walk_edges(child, source_bytes, file_path, edges, new_fqn)
                    except Exception:
                        pass
                    return

        if node_type == "call" or node_type == "call_expression":
            if current_fqn:
                rng = self._parser.get_node_range(node)
                source_range = json.dumps([rng[0], rng[1], rng[2], rng[3]])
                target_name = self._resolve_call_target(node, source_bytes)
                if target_name and target_name != current_fqn:
                    edges.append(
                        {
                            "source_fqn": current_fqn,
                            "target_fqn": target_name,
                            "edge_type": "CALLS",
                            "source_range": source_range,
                        }
                    )
            return

        if node_type == "import_statement":
            self._extract_import_edges(node, source_bytes, edges, current_fqn)
            return

        if node_type == "import_from_statement":
            self._extract_import_edges(node, source_bytes, edges, current_fqn, is_from=True)
            return

        try:
            for child in node.children:
                self._walk_edges(child, source_bytes, file_path, edges, current_fqn)
        except Exception:
            pass

    @staticmethod
    def _build_import_map(import_edges: list[dict[str, Any]]) -> dict[str, str]:
        """Build an import map from IMPORTS edges: unqualified name -> FQN.

        From an edge targeting ``foo.bar`` produces ``{"bar": "foo.bar"}``.
        """
        imp_map: dict[str, str] = {}
        for edge in import_edges:
            tgt = edge.get("target_fqn", "")
            if not tgt:
                continue
            parts = tgt.rsplit(".", 1)
            simple_name = parts[-1]
            if simple_name and simple_name not in imp_map:
                imp_map[simple_name] = tgt
        return imp_map

    def _walk_imports(
        self,
        node: Any,
        source_bytes: bytes,
        file_path: Path,
        edges: list[dict[str, Any]],
        import_fqns: set[str],
    ) -> None:
        """Walk AST collecting only IMPORTS edges into *edges*."""
        try:
            node_type = node.type
        except Exception:
            return
        if node_type == "import_statement":
            self._extract_import_edges(node, source_bytes, edges, current_fqn=str(file_path))
            return
        if node_type == "import_from_statement":
            self._extract_import_edges(
                node, source_bytes, edges, current_fqn=str(file_path), is_from=True
            )
            return
        if node_type == "import_declaration":
            self._extract_import_edges(node, source_bytes, edges, current_fqn=str(file_path))
            return
        try:
            for child in node.children:
                self._walk_imports(child, source_bytes, file_path, edges, import_fqns)
        except Exception:
            pass

    def _collect_field_types(self, node: Any, source_bytes: bytes) -> dict[str, str]:
        """Collect ``{field_name: type_simple_name}`` from a class declaration node.

        Scans ``field_declaration`` children for a ``type_identifier`` (the
        declared type) and ``variable_declarator`` names (the field names).
        """
        field_types: dict[str, str] = {}
        try:
            for child in node.children:
                if child.type == "class_body":
                    for field in child.named_children:
                        if field.type == "field_declaration":
                            self._collect_field_decl(field, source_bytes, field_types)
                elif child.type == "field_declaration":
                    self._collect_field_decl(child, source_bytes, field_types)
        except Exception:
            pass
        return field_types

    @staticmethod
    def _collect_field_decl(field: Any, source_bytes: bytes, field_types: dict[str, str]) -> None:
        """Extract type + variable names from a single field_declaration node."""
        try:
            type_name: str | None = None
            for sub in field.children:
                if sub.type in (
                    "type_identifier",
                    "scoped_type_identifier",
                    "generic_type",
                    "array_type",
                ):
                    type_name = ASTParser.get_node_text(sub, source_bytes)
                    break
            if not type_name:
                return
            for sub in field.children:
                if sub.type != "variable_declarator":
                    continue
                for name_node in sub.children:
                    if name_node.type == "identifier":
                        field_name = ASTParser.get_node_text(name_node, source_bytes)
                        if field_name:
                            field_types[field_name] = type_name
        except Exception:
            pass

    @staticmethod
    def _collect_local_var_types(node: Any, source_bytes: bytes) -> dict[str, str]:
        """Collect ``{local_name: type_simple_name}`` within a method body.

        Enables receiver-qualified CALLS resolution for locals like
        ``CalleeA helper = new CalleeA(); helper.transform(...)``: without the
        declared type the call target ``helper.transform`` cannot be matched to
        ``CalleeA.transform``, so such in-corpus calls would be misreported as
        unresolved/external callees.

        Args:
            node: The method/function node whose body is scanned.
            source_bytes: Raw source bytes for text extraction.

        Returns:
            Mapping of local variable name -> declared type simple name.
        """
        local_types: dict[str, str] = {}

        def visit(n: Any) -> None:
            try:
                if n.type == "local_variable_declaration":
                    type_name: str | None = None
                    for sub in n.children:
                        if sub.type in (
                            "type_identifier",
                            "scoped_type_identifier",
                            "generic_type",
                            "array_type",
                            "integral_type",
                            "floating_point_type",
                            "boolean_type",
                        ):
                            type_name = ASTParser.get_node_text(sub, source_bytes)
                            if type_name and type_name != "var":
                                break
                            type_name = None
                    if type_name:
                        for sub in n.children:
                            if sub.type != "variable_declarator":
                                continue
                            for name_node in sub.children:
                                if name_node.type == "identifier":
                                    var_name = ASTParser.get_node_text(name_node, source_bytes)
                                    if var_name:
                                        local_types[var_name] = type_name
                                    break
            except Exception:
                pass
            try:
                for child in n.children:
                    visit(child)
            except Exception:
                pass

        visit(node)
        return local_types

    def _walk_calls_and_inherits(
        self,
        node: Any,
        source_bytes: bytes,
        file_path: Path,
        edges: list[dict[str, Any]],
        current_fqn: str | None = None,
        import_map: dict[str, str] | None = None,
        symbol_catalog: dict[str, int] | None = None,
        field_types: dict[str, str] | None = None,
    ) -> None:
        """Walk AST collecting CALLS and INHERITS edges with import-map and catalog resolution."""
        try:
            node_type = node.type
        except Exception:
            return

        if node_type in _DEFINITION_NODES:
            name_node = self._find_name_node(node)
            if name_node is not None:
                name = self._parser.get_node_text(name_node, source_bytes)
                if name:
                    new_fqn = build_symbol_fqn(str(file_path), current_fqn, name)
                    if node_type in (
                        "method_declaration",
                        "method_definition",
                        "constructor_declaration",
                        "function_definition",
                        "function_declaration",
                        "method",
                        "method_signature",
                        "abstract_method_signature",
                    ):
                        param_types = self._extract_param_types(node, source_bytes)
                        if param_types:
                            new_fqn = f"{new_fqn}({','.join(param_types)})"
                    if node_type in _INHERITANCE_DEF_NODES:
                        self._extract_inheritance_edges(
                            node, source_bytes, edges, new_fqn, import_map=import_map
                        )
                    class_field_types = field_types
                    if node_type in (
                        "class_definition",
                        "class_declaration",
                        "interface_declaration",
                        "enum_declaration",
                    ):
                        collected = self._collect_field_types(node, source_bytes)
                        if collected:
                            class_field_types = dict(field_types or {})
                            class_field_types.update(collected)
                    # Method bodies may reference receiver-qualified calls on
                    # local variables; fold their declared types into the scope
                    # so ``Type helper = new Type(); helper.method()`` resolves.
                    if node_type in (
                        "method_declaration",
                        "method_definition",
                        "constructor_declaration",
                        "function_definition",
                    ):
                        local_types = self._collect_local_var_types(node, source_bytes)
                        if local_types:
                            scoped = dict(class_field_types or {})
                            scoped.update(local_types)
                            class_field_types = scoped
                    try:
                        for child in node.children:
                            self._walk_calls_and_inherits(
                                child,
                                source_bytes,
                                file_path,
                                edges,
                                current_fqn=new_fqn,
                                import_map=import_map,
                                symbol_catalog=symbol_catalog,
                                field_types=class_field_types,
                            )
                    except Exception:
                        pass
                    return

        # An anonymous class (``new Base() { ... }``) is a subtype of its base;
        # emit the INHERITS edge from its synthetic symbol and walk the body
        # under that symbol so its methods are attributed to the anonymous type.
        anon_fqn: str | None = None
        if node_type in _ANONYMOUS_CLASS_NODES and self._has_class_body(node):
            anon_fqn = self._anonymous_fqn(node, source_bytes, file_path, current_fqn)
            base = self._anonymous_base_name(node, source_bytes)
            if anon_fqn and base:
                rng = self._parser.get_node_range(node)
                edges.append(
                    {
                        "source_fqn": anon_fqn,
                        "target_fqn": (import_map or {}).get(base, base),
                        "target_raw": base,
                        "edge_type": "INHERITS",
                        "source_range": json.dumps([rng[0], rng[1], rng[2], rng[3]]),
                    }
                )

        if (
            node_type
            in (
                "call",
                "call_expression",
                "method_invocation",
                "object_creation_expression",
            )
            and current_fqn
        ):
            rng = self._parser.get_node_range(node)
            source_range = json.dumps([rng[0], rng[1], rng[2], rng[3]])
            target_name = self._resolve_call_target(
                node, source_bytes, import_map, symbol_catalog, field_types=field_types
            )
            if target_name and target_name != current_fqn:
                edges.append(
                    {
                        "source_fqn": current_fqn,
                        "target_fqn": target_name,
                        "target_raw": self._raw_call_text(node, source_bytes),
                        "edge_type": "CALLS",
                        "source_range": source_range,
                    }
                )

        try:
            for child in node.children:
                self._walk_calls_and_inherits(
                    child,
                    source_bytes,
                    file_path,
                    edges,
                    current_fqn=anon_fqn or current_fqn,
                    import_map=import_map,
                    symbol_catalog=symbol_catalog,
                    field_types=field_types,
                )
        except Exception:
            pass

    def _raw_call_text(self, node: Any, source_bytes: bytes) -> str:
        """Return the raw callee reference text of a call node.

        Strips the argument list from the node text so ``repository.save(...)``
        yields ``repository.save`` (the text a consumer sees at the call site),
        which unresolved edges carry as ``target_raw``.
        """
        try:
            text = self._parser.get_node_text(node, source_bytes) or ""
        except Exception:
            return ""
        open_paren = text.find("(")
        if open_paren != -1:
            text = text[:open_paren]
        return text.strip()

    def _resolve_call_target(
        self,
        node: Any,
        source_bytes: bytes,
        import_map: dict[str, str] | None = None,
        symbol_catalog: dict[str, int] | None = None,
        field_types: dict[str, str] | None = None,
    ) -> str | None:
        """Resolve the name of the callee from a call/call_expression node.

        Uses *import_map* to resolve unqualified names and attribute prefixes
        to their fully-qualified form for cross-file call graph resolution.
        Additionally consults *symbol_catalog* for cross-file targets and
        *field_types* (field name → declared type) for field-qualified calls.
        """
        try:
            node_type = node.type
        except Exception:
            return None

        if node_type == "method_invocation":
            return self._resolve_method_invocation(
                node, source_bytes, import_map, symbol_catalog, field_types=field_types
            )
        if node_type == "object_creation_expression":
            return self._resolve_object_creation(node, source_bytes, import_map)

        try:
            for child in node.children:
                child_type = child.type
                if child_type == "identifier":
                    text = self._parser.get_node_text(child, source_bytes)
                    if text:
                        if import_map and text in import_map:
                            return import_map[text]
                        if symbol_catalog and text in symbol_catalog:
                            return text
                    return text
                if child_type == "attribute":
                    text = self._parser.get_node_text(child, source_bytes)
                    if text:
                        if import_map:
                            base = text.split(".")[0]
                            if base in import_map:
                                resolved_base = import_map[base]
                                rest = text[len(base) :]
                                return resolved_base + rest
                        if symbol_catalog and text in symbol_catalog:
                            return text
                    return text
                if child_type == "member_expression":
                    text = self._parser.get_node_text(child, source_bytes)
                    if text:
                        if import_map:
                            base = text.split(".")[0]
                            if base in import_map:
                                resolved_base = import_map[base]
                                rest = text[len(base) :]
                                return resolved_base + rest
                        if symbol_catalog and text in symbol_catalog:
                            return text
                    return text
            return None
        except Exception:
            return None

    def _resolve_method_invocation(
        self,
        node: Any,
        source_bytes: bytes,
        import_map: dict[str, str] | None = None,
        _catalog: dict[str, int] | None = None,
        field_types: dict[str, str] | None = None,
    ) -> str | None:
        """Resolve a Java method_invocation node to a fully-qualified target name."""
        try:
            method_name: str | None = None
            object_name: str | None = None
            obj_node = node.child_by_field_name("object")
            if obj_node is not None:
                object_name = self._parser.get_node_text(obj_node, source_bytes)
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                method_name = self._parser.get_node_text(name_node, source_bytes)
            if method_name is None:
                children = list(node.children)
                ids = [
                    self._parser.get_node_text(c, source_bytes)
                    for c in children
                    if c.type == "identifier"
                ]
                if len(ids) >= 2:
                    object_name = ids[0]
                    method_name = ids[1]
                elif len(ids) == 1:
                    method_name = ids[0]
            if method_name is None:
                full_text = self._parser.get_node_text(node, source_bytes) or ""
                if "." in full_text:
                    parts = full_text.rsplit(".", 1)
                    object_name = parts[0]
                    method_name = parts[1]
                else:
                    method_name = full_text
            resolved = f"{object_name}.{method_name}" if object_name else method_name
            if import_map and object_name and object_name in import_map:
                resolved = f"{import_map[object_name]}.{method_name}"
            elif field_types and object_name and object_name in field_types:
                declared_type = field_types[object_name]
                if import_map and declared_type in import_map:
                    resolved = f"{import_map[declared_type]}.{method_name}"
                else:
                    resolved = f"{declared_type}.{method_name}"
            return resolved
        except Exception:
            return None

    def _resolve_object_creation(
        self,
        node: Any,
        source_bytes: bytes,
        import_map: dict[str, str] | None = None,
    ) -> str | None:
        """Resolve a Java object_creation_expression (new ClassName())."""
        try:
            for child in node.children:
                if child.type in ("type_identifier", "identifier", "scoped_type_identifier"):
                    type_name = self._parser.get_node_text(child, source_bytes)
                    if type_name:
                        if import_map and type_name in import_map:
                            return import_map[type_name]
                        return type_name
            return None
        except Exception:
            return None

    def _extract_import_edges(
        self,
        node: Any,
        source_bytes: bytes,
        edges: list[dict[str, Any]],
        current_fqn: str | None = None,
        is_from: bool = False,
    ) -> None:
        """Append ``IMPORTS`` edges from an import AST node.

        Handles both ``import x`` (or comma-separated ``import a, b``) and
        ``from module import name`` forms, stripping ``as`` aliases and
        trailing semicolons. Each imported name becomes an ``IMPORTS`` edge
        with ``source_fqn`` set to *current_fqn* (the enclosing file/symbol).

        Args:
            node: An ``import_statement`` / ``import_from_statement`` node.
            source_bytes: Raw source bytes for node text extraction.
            edges: Output list the new ``IMPORTS`` edges are appended to.
            current_fqn: FQN of the importing scope; the edge source. When
                ``None`` no edges are emitted.
            is_from: Whether the statement is the ``from ... import ...`` form.
        """
        try:
            rng = self._parser.get_node_range(node)
            source_range = json.dumps([rng[0], rng[1], rng[2], rng[3]])
            text = self._parser.get_node_text(node, source_bytes)
            if is_from:
                parts = text.replace("from ", "").split(" import ")
                if len(parts) == 2:
                    module = parts[0].strip()
                    names_str = parts[1].strip()
                    for name in names_str.split(","):
                        name = name.strip().split(" as ")[0].strip()
                        if name:
                            target_fqn = f"{module}.{name}"
                            if current_fqn:
                                edges.append(
                                    {
                                        "source_fqn": current_fqn,
                                        "target_fqn": target_fqn,
                                        "edge_type": "IMPORTS",
                                        "source_range": source_range,
                                    }
                                )
            else:
                after_import = text.replace("import ", "").strip().rstrip(";").strip()
                for name in after_import.split(","):
                    name = name.strip().split(" as ")[0].strip()
                    if name and current_fqn:
                        edges.append(
                            {
                                "source_fqn": current_fqn,
                                "target_fqn": name,
                                "edge_type": "IMPORTS",
                                "source_range": source_range,
                            }
                        )
        except Exception:
            pass

    def _extract_inheritance_edges(
        self,
        node: Any,
        source_bytes: bytes,
        edges: list[dict[str, Any]],
        class_fqn: str | None = None,
        import_map: dict[str, str] | None = None,
    ) -> None:
        """Append ``INHERITS`` edges from a type declaration's base clauses.

        Grammar-tolerant reader for every supported language: it matches the
        clause nodes in :data:`_INHERITANCE_CLAUSE_NODES`, drills through the
        wrapper nodes in :data:`_INHERITANCE_WRAPPER_NODES` to a leaf name in
        :data:`_INHERITANCE_LEAF_NODES`, reduces each base reference to its
        simple leaf name (stripping qualifiers and generics), and resolves it
        through *import_map* when present. Runs for classes **and** interfaces.

        Args:
            node: A class/interface declaration AST node.
            source_bytes: Raw source bytes for node text extraction.
            edges: Output list the new ``INHERITS`` edges are appended to.
            class_fqn: FQN of the declaring type; the edge source.
            import_map: Simple name -> imported FQN for the enclosing file.
        """
        if not class_fqn:
            return
        class_leaf = class_fqn.rsplit("::", 1)[-1].rsplit(".", 1)[-1]
        try:
            clause_nodes = [c for c in node.children if c.type in _INHERITANCE_CLAUSE_NODES]
        except Exception:
            return
        seen: set[str] = set()
        for clause in clause_nodes:
            for base in self._collect_base_names(clause, source_bytes):
                if not base or base == class_leaf or base in seen:
                    continue
                seen.add(base)
                target_fqn = (import_map or {}).get(base, base)
                edges.append(
                    {
                        "source_fqn": class_fqn,
                        "target_fqn": target_fqn,
                        "target_raw": base,
                        "edge_type": "INHERITS",
                        "source_range": json.dumps(self._parser.get_node_range(node)),
                    }
                )

    def _collect_base_names(self, node: Any, source_bytes: bytes) -> list[str]:
        """Return the simple base names reachable from an inheritance *node*.

        Recurses through the wrapper nodes in
        :data:`_INHERITANCE_WRAPPER_NODES` and stops at the leaf nodes in
        :data:`_INHERITANCE_LEAF_NODES`, reducing each leaf's text to its
        simple name. ``extends`` / ``implements`` keywords, punctuation, and
        type-argument lists are ignored.
        """
        names: list[str] = []
        try:
            node_type = node.type
        except Exception:
            return names
        if node_type in _INHERITANCE_LEAF_NODES:
            simple = self._base_leaf_name(self._parser.get_node_text(node, source_bytes))
            if simple:
                names.append(simple)
            return names
        if node_type in ("type_arguments", "value_arguments"):
            return names
        try:
            children = node.children
        except Exception:
            return names
        for child in children:
            if child.type in _INHERITANCE_WRAPPER_NODES or child.type in _INHERITANCE_LEAF_NODES:
                names.extend(self._collect_base_names(child, source_bytes))
        return names

    @staticmethod
    def _base_leaf_name(raw: str | None) -> str:
        """Reduce a base-type reference to its simple leaf name.

        Strips generic arguments (``List<Tag>`` -> ``List``), then takes the
        last dotted / ``::`` segment (``mixins.M`` -> ``M``, ``A.B`` -> ``B``).
        """
        if not raw:
            return ""
        text = raw.strip()
        if "<" in text:
            text = text.split("<", 1)[0].strip()
        for sep in ("::", "."):
            if sep in text:
                text = text.rsplit(sep, 1)[-1]
        return text.strip()

    @staticmethod
    def _has_class_body(node: Any) -> bool:
        """Return whether *node* carries an inline class body (an anonymous class)."""
        try:
            return any(child.type == "class_body" for child in node.children)
        except Exception:
            return False

    def _anonymous_base_name(self, node: Any, source_bytes: bytes) -> str | None:
        """Return the simple base-type name an anonymous class instantiates.

        Reads the ``type`` field (falling back to a scan of the node's children)
        and reduces it to its simple leaf name; returns ``None`` when no base
        type can be read.
        """
        raw: str | None = None
        try:
            type_node = node.child_by_field_name("type")
            if type_node is not None:
                raw = self._parser.get_node_text(type_node, source_bytes)
        except Exception:
            raw = None
        if not raw:
            try:
                for child in node.children:
                    if child.type in _INHERITANCE_LEAF_NODES:
                        raw = self._parser.get_node_text(child, source_bytes)
                        if raw:
                            break
            except Exception:
                raw = None
        leaf = self._base_leaf_name(raw)
        return leaf or None

    def _anonymous_symbol_name(self, node: Any, source_bytes: bytes) -> str | None:
        """Build a deterministic, file-unique name for an anonymous class.

        The name combines the base leaf with the node's starting line so two
        anonymous classes in one file never collide on the unique FQN index.
        """
        base = self._anonymous_base_name(node, source_bytes)
        if not base:
            return None
        try:
            line = self._parser.get_node_range(node)[0]
        except Exception:
            line = 0
        return f"{base}Anonymous{line}"

    def _anonymous_fqn(
        self, node: Any, source_bytes: bytes, file_path: Path, parent_fqn: str | None
    ) -> str | None:
        """Return the synthetic FQN of an anonymous class, or ``None``."""
        name = self._anonymous_symbol_name(node, source_bytes)
        if not name:
            return None
        return build_symbol_fqn(str(file_path), parent_fqn, name)

    def _extract_anonymous_symbol(
        self,
        node: Any,
        source_bytes: bytes,
        file_path: Path,
        parent_fqn: str | None,
    ) -> dict[str, Any] | None:
        """Build a symbol for an anonymous class body (``new Base() { ... }``).

        The synthetic type is navigable (it carries the creation site's line
        range) and is parented to the enclosing scope so an implementation
        lookup can address it rather than silently dropping the implementer.
        """
        try:
            name = self._anonymous_symbol_name(node, source_bytes)
            if not name:
                return None
            line_start, col_start, line_end, col_end = self._parser.get_node_range(node)
            lang = LANGUAGE_MAP.get(file_path.suffix.lower(), "unknown")
            return {
                "fqn": build_symbol_fqn(str(file_path), parent_fqn, name),
                "conventional_fqn": None,
                "name": name,
                "kind": "class",
                "file_path": str(file_path),
                "line_start": line_start,
                "line_end": line_end,
                "column_start": col_start,
                "column_end": col_end,
                "docstring": None,
                "declared_rules": None,
                "language": lang,
                "parent_fqn": parent_fqn,
            }
        except Exception as exc:
            logger.debug("Failed to extract anonymous symbol: %s", exc)
            return None

    def _build_conventional_fqn(
        self,
        node: Any,
        file_path: Path,
        source_bytes: bytes,
        parent_fqn: str | None = None,
        package_name: str | None = None,
    ) -> str | None:
        """Build conventional dotted FQN for Java symbols.

        Format: ``{package}.{outer_class}.{inner_class}.{method}({param_types})``
        Returns None for non-Java files.
        """
        lang_suffix = file_path.suffix.lower()
        if lang_suffix != ".java":
            return None
        name_node = self._find_name_node(node)
        if name_node is None:
            return None
        name = self._parser.get_node_text(name_node, source_bytes)
        if not name:
            return None

        parts: list[str] = []
        if package_name:
            parts.append(package_name)

        if parent_fqn and "::" in parent_fqn:
            parent_part = parent_fqn.split("::", 1)[1]
            parent_classes = parent_part.split(".")
            parts.extend(parent_classes)

        parts.append(name)

        param_types = self._extract_param_types(node, source_bytes, strip_annotations=True)
        if param_types:
            return f"{'.'.join(parts)}({','.join(param_types)})"
        return ".".join(parts)

    def _extract_symbol(
        self,
        node: Any,
        source_bytes: bytes,
        file_path: Path,
        node_type: str,
        parent_fqn: str | None = None,
        package_name: str | None = None,
        declared_rules: str = "",
    ) -> dict[str, Any] | None:
        """Build a symbol dict from an AST definition node.

        *declared_rules* is carried from a Python ``decorated_definition``;
        when empty, Java annotations are extracted from the node itself.
        """
        try:
            name_node = self._find_name_node(node)
            if name_node is None:
                return None
            name = self._parser.get_node_text(name_node, source_bytes)
            if not name:
                return None
            line_start, col_start, line_end, col_end = self._parser.get_node_range(node)
            lang_suffix = file_path.suffix.lower()
            lang = LANGUAGE_MAP.get(lang_suffix, "unknown")
            docstring = self._extract_docstring(node, source_bytes, lang)
            kind = self._map_kind(node_type)
            if kind == "function" and parent_fqn is not None:
                kind = "method"

            rel_path = str(file_path)
            full_parent_fqn = parent_fqn
            param_types = self._extract_param_types(node, source_bytes)
            fqn = build_symbol_fqn(rel_path, parent_fqn, name, param_types)

            conventional_fqn = self._build_conventional_fqn(
                node,
                file_path,
                source_bytes,
                parent_fqn=parent_fqn,
                package_name=package_name,
            )

            rules = declared_rules or self._parser._annotation_rules(node, source_bytes)

            return {
                "fqn": fqn,
                "conventional_fqn": conventional_fqn,
                "name": name,
                "kind": kind,
                "file_path": str(file_path),
                "line_start": line_start,
                "line_end": line_end,
                "column_start": col_start,
                "column_end": col_end,
                "docstring": docstring,
                "declared_rules": rules or None,
                "language": lang,
                "parent_fqn": full_parent_fqn,
            }
        except Exception as exc:
            logger.debug("Failed to extract symbol: %s", exc)
            return None

    @staticmethod
    def _extract_param_types(
        node: Any, source_bytes: bytes, strip_annotations: bool = False
    ) -> list[str]:
        """Extract parameter type names from a method/constructor AST node.

        Looks for a ``formal_parameters`` child node and extracts type names
        from its ``parameter`` or ``formal_parameter`` children. Uses the
        first non-identifier named child within each parameter as the type.

        When *strip_annotations* is True (Java), skips ``annotation`` subnodes
        and only extracts ``type_identifier`` children.
        """
        try:
            for child in node.children:
                if child.type == "formal_parameters":
                    param_types: list[str] = []
                    for param in child.named_children:
                        if param.type in ("parameter", "formal_parameter"):
                            if strip_annotations:
                                for sub in param.named_children:
                                    if sub.type not in ("identifier", "annotation", "modifiers"):
                                        tname = ASTParser.get_node_text(sub, source_bytes)
                                        if tname:
                                            param_types.append(tname)
                                        break
                            else:
                                for sub in param.named_children:
                                    if sub.type not in ("identifier", "modifiers", "annotation"):
                                        tname = ASTParser.get_node_text(sub, source_bytes)
                                        if tname:
                                            param_types.append(tname)
                                        break
                                else:
                                    if param.named_children:
                                        tname = ASTParser.get_node_text(
                                            param.named_children[0], source_bytes
                                        )
                                        if tname:
                                            param_types.append(tname)
                    return param_types
        except Exception:
            pass
        return []

    @staticmethod
    def _find_name_node(node: Any) -> Any:
        """Return the child AST node holding a definition's name, or ``None``.

        Prefers the grammar's ``name`` field (which tree-sitter exposes for
        every definition node, including TypeScript classes/interfaces whose
        name node is a ``type_identifier``). Falls back to scanning children
        for ``name``/``identifier`` nodes, inside a ``variable_declarator``,
        and as the first named child — covering functions, methods, classes,
        interfaces, and field declarations across grammars.
        """
        try:
            field = node.child_by_field_name("name")
            if field is not None:
                return field
        except Exception:
            pass
        # C++ declares the name on a nested ``declarator`` (function_declarator
        # -> field_identifier), not as a direct name field.
        try:
            declarator = node.child_by_field_name("declarator")
            guard = 0
            while declarator is not None and guard < 5:
                name_field = declarator.child_by_field_name("name")
                if name_field is not None:
                    return name_field
                if declarator.type in (
                    "field_identifier",
                    "identifier",
                    "destructor_name",
                    "operator_name",
                ):
                    return declarator
                declarator = declarator.child_by_field_name("declarator")
                guard += 1
        except Exception:
            pass
        try:
            for child in node.children:
                if child.type in ("name", "identifier"):
                    return child
                if child.type == "variable_declarator":
                    for sub in child.children:
                        if sub.type in ("name", "identifier"):
                            return sub
            named = node.named_children
            if named:
                first = named[0]
                if first.type in ("name", "identifier"):
                    return first
                if first.type == "variable_declarator":
                    for sub in first.children:
                        if sub.type in ("name", "identifier"):
                            return sub
        except Exception:
            pass
        return None

    @staticmethod
    def _extract_docstring(node: Any, source_bytes: bytes, language: str = "python") -> str | None:
        """Return the docstring/comment preceding a definition, or ``None``.

        Strategies are language-specific: the first string expression in a
        Python ``block``; a preceding ``block_comment`` for Java; a preceding
        ``comment`` / ``attribute_item`` / doc-comment for JavaScript,
        TypeScript, Rust, and C#. Returns ``None`` when no matching comment
        node exists or the language has no strategy.
        """
        try:
            if language == "python":
                block = None
                for child in node.children:
                    if child.type == "block":
                        block = child
                        break
                if block is not None:
                    first = block.children[0]
                    if first.type == "expression_statement":
                        expr = first.children[0]
                        if expr.type == "string":
                            return ASTParser.get_node_text(expr, source_bytes)

            elif language == "java":
                try:
                    prev = node.prev_sibling
                    if prev is not None and prev.type == "block_comment":
                        return ASTParser.get_node_text(prev, source_bytes)
                    prev = node.prev_named_sibling
                    if prev is not None and prev.type == "block_comment":
                        return ASTParser.get_node_text(prev, source_bytes)
                except Exception:
                    pass
                prev = None
                for child in node.children:
                    if child.type == "block_comment":
                        prev = child
                    elif child.type in (
                        "function_definition",
                        "method_definition",
                        "class_definition",
                        "class_declaration",
                        "interface_declaration",
                        "method_declaration",
                        "constructor_declaration",
                    ):
                        if prev and prev.type == "block_comment":
                            return ASTParser.get_node_text(prev, source_bytes)
                    else:
                        prev = None

            elif language in ("javascript", "typescript"):
                for sibling in (node.prev_sibling, node.prev_named_sibling):
                    if sibling is not None and sibling.type == "comment":
                        return ASTParser.get_node_text(sibling, source_bytes)
                prev = None
                for child in node.children:
                    if child.type == "comment":
                        prev = child
                    elif child.type in (
                        "function_definition",
                        "method_definition",
                        "class_definition",
                        "arrow_function",
                        "export_statement",
                    ):
                        if prev and prev.type == "comment":
                            return ASTParser.get_node_text(prev, source_bytes)
                    else:
                        prev = None

            elif language == "rust":
                prev = None
                for child in node.children:
                    if child.type == "attribute_item":
                        prev = child
                    elif child.type in (
                        "function_definition",
                        "method_definition",
                        "class_definition",
                        "trait_item",
                    ):
                        if prev and prev.type == "attribute_item":
                            return ASTParser.get_node_text(prev, source_bytes)
                    else:
                        prev = None

            elif language == "c_sharp":
                prev = None
                for child in node.children:
                    if child.type in ("xml_doc_comment", "comment"):
                        prev = child
                    elif child.type in (
                        "function_definition",
                        "method_definition",
                        "class_definition",
                        "interface_declaration",
                    ):
                        if prev:
                            return ASTParser.get_node_text(prev, source_bytes)
                    else:
                        prev = None

            else:
                logger.debug("No docstring extraction strategy for language: %s", language)

        except Exception:
            pass
        return None

    @staticmethod
    def _map_kind(node_type: str) -> str:
        """Map a tree-sitter definition node type to a symbol kind.

        Returns ``function``, ``method``, ``class``, ``interface``, ``enum``,
        ``constructor``, or ``field``; anything unrecognised maps to
        ``variable``.
        """
        mapping: dict[str, str] = {
            "function_definition": "function",
            "method_definition": "method",
            "class_definition": "class",
            "class_declaration": "class",
            "class_specifier": "class",
            "struct_specifier": "class",
            "class": "class",
            "interface_declaration": "interface",
            "enum_declaration": "enum",
            "method_declaration": "method",
            "constructor_declaration": "constructor",
            "field_declaration": "field",
            "function_declaration": "function",
            "method": "method",
            "method_signature": "method",
            "abstract_method_signature": "method",
        }
        return mapping.get(node_type, "variable")


class SymbolStore:
    """SQLite-backed CRUD for symbol records."""

    def __init__(self, db: GraphDatabase, settings: Settings | None = None) -> None:
        """Initialize the symbol store over a graph database.

        Args:
            db: The :class:`~src.engine.graph.GraphDatabase` whose ``symbols``
                table backs this store.
            settings: Engine settings; defaults to ``Settings.from_env()``
                (used for the resolution-candidate bound).
        """
        self._db = db
        self._settings = settings or Settings.from_env()

    def insert_symbol(self, symbol: dict[str, Any]) -> int | None:
        """Insert a single symbol record, linking to its parent.

        Resolves ``parent_fqn`` to the parent row id (when present), inserts
        the row, and returns the new row id.

        Args:
            symbol: The symbol dict from :meth:`SymbolExtractor.extract_symbols`.

        Returns:
            The new ``symbols.id``, or ``None`` when the insert fails.
        """
        with self._db.write_transaction() as conn:
            parent_id: int | None = None
            if symbol.get("parent_fqn"):
                row = conn.execute(
                    "SELECT id FROM symbols WHERE fqn = ?;", (symbol["parent_fqn"],)
                ).fetchone()
                if row:
                    parent_id = row["id"]
            try:
                cursor = conn.execute(
                    "INSERT INTO symbols "
                    "(fqn, name, kind, file_path, line_start, line_end, column_start, column_end, "
                    "docstring, declared_rules, language, parent_symbol_id, conventional_fqn) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (
                        symbol["fqn"],
                        symbol["name"],
                        symbol["kind"],
                        symbol["file_path"],
                        symbol["line_start"],
                        symbol["line_end"],
                        symbol["column_start"],
                        symbol["column_end"],
                        symbol.get("docstring"),
                        symbol.get("declared_rules"),
                        symbol.get("language", "unknown"),
                        parent_id,
                        symbol.get("conventional_fqn"),
                    ),
                )
                return cursor.lastrowid
            except Exception as exc:
                logger.warning("Failed to insert symbol %s: %s", symbol.get("fqn"), exc)
                return None

    def insert_symbols_batch(self, symbols: list[dict[str, Any]]) -> dict[str, int]:
        """Insert a batch of symbols, returning ``{fqn: db_id}`` map.

        Batches parent FQN lookups into a single SELECT with IN clause
        (avoids N+1 query pattern), falling back to per-query for parents
        that are inserted earlier in the same batch.
        """
        result: dict[str, int] = {}
        parent_fqns: set[str] = {sym["parent_fqn"] for sym in symbols if sym.get("parent_fqn")}
        parent_map: dict[str, int] = {}
        with self._db.write_transaction() as conn:
            if parent_fqns:
                placeholders = ",".join("?" for _ in parent_fqns)
                rows = conn.execute(
                    f"SELECT fqn, id FROM symbols WHERE fqn IN ({placeholders});",
                    list(parent_fqns),
                ).fetchall()
                parent_map = {r["fqn"]: r["id"] for r in rows}

            for sym in symbols:
                parent_fqn = sym.get("parent_fqn")
                if parent_fqn and parent_fqn not in parent_map:
                    if parent_fqn in result:
                        parent_map[parent_fqn] = result[parent_fqn]
                    else:
                        row = conn.execute(
                            "SELECT id FROM symbols WHERE fqn = ?;", (parent_fqn,)
                        ).fetchone()
                        if row:
                            parent_map[parent_fqn] = row["id"]
                parent_id = parent_map.get(parent_fqn) if parent_fqn else None
                try:
                    cursor = conn.execute(
                        "INSERT INTO symbols "
                        "(fqn, name, kind, file_path, line_start, "
                        "line_end, column_start, column_end, "
                        "docstring, declared_rules, language, parent_symbol_id, conventional_fqn) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                        (
                            sym["fqn"],
                            sym["name"],
                            sym["kind"],
                            sym["file_path"],
                            sym["line_start"],
                            sym["line_end"],
                            sym["column_start"],
                            sym["column_end"],
                            sym.get("docstring"),
                            sym.get("declared_rules"),
                            sym.get("language", "unknown"),
                            parent_id,
                            sym.get("conventional_fqn"),
                        ),
                    )
                    result[sym["fqn"]] = cast(int, cursor.lastrowid)
                    if parent_fqn and parent_id is None:
                        parent_map[parent_fqn] = result[sym["fqn"]]
                except Exception as exc:
                    logger.warning("Failed to insert symbol %s: %s", sym.get("fqn"), exc)
        return result

    def resolve_name(self, query: str, max_candidates: int | None = None) -> dict[str, Any]:
        """Resolve *query* to a resolution envelope (the ONE shared rule).

        Returns ``{"kind", "symbol", "candidates", "overloads", "ambiguous",
        "outcome"}`` where ``kind`` is one of ``exact``, ``ambiguous``,
        ``suggestion``, or ``not_found`` and ``outcome`` is the additive
        user-visible classification (``resolved`` | ``ambiguous`` |
        ``not_found``):

        - ``exact``: a single symbol resolved (exact FQN / exact conventional
          FQN / unique bare name / parent-qualified ``Class.method``);
          ``symbol`` is the full row (with ``source_code``) and ``candidates``
          is empty.
        - ``ambiguous``: >= 2 matches; ``symbol`` is ``None`` and
          ``candidates`` are the ranked, evidence-carrying
          ``_candidate_summary`` rows capped at ``max_candidates``. A
          multi-match reference is never auto-selected.
        - ``suggestion``: no exact-name match; only prefix / subword /
          edit-distance fallback candidates (each carries ``edit_distance``
          and ``suggestion`` when applicable). Classified ``not_found``.
        - ``not_found``: zero candidates.

        ``overloads`` lists every declaration sharing the resolved name within
        its parent scope; ``ambiguous`` is ``true`` exactly when more
        than one such overload is visible in the indexed corpus. Both are
        independent of the ``kind`` signal: a qualified name that resolves to
        one declaration (``kind: exact``) still reports ``ambiguous: true``
        when sibling declarations share the resolved name in the parent scope.

        When ``max_candidates`` is ``None`` the bound is read from
        ``Settings.max_resolution_candidates``
        (``CODE_SEARCH_MAX_RESOLUTION_CANDIDATES``, default 10). Every
        consumer (both MCP tools, both CLI commands) derives from this
        function so the candidate list — content and order — is identical
        everywhere.
        """
        cap = (
            max_candidates
            if max_candidates is not None
            else self._settings.max_resolution_candidates
        )
        with self._db.connect() as conn:
            candidates = [_attach_row_signature(c) for c in _resolve_symbol_candidates(conn, query)]
            reference = parse_reference(query)
            if reference.signature is not None:
                return self._resolve_with_signature(
                    query, candidates, max_candidates=cap, conn=conn
                )
            symbol, ranked, kind = _rank_symbol_candidates(query, candidates, max_candidates=cap)
            result = ResolutionResult(symbol, ranked, kind)
            envelope = self._build_envelope(result)
            envelope["outcome"] = outcome_for_kind(envelope["kind"])
            return self._attach_overload_info(
                conn, envelope, overload_scope=self._overload_scope(result)
            )

    def _build_envelope(self, result: ResolutionResult) -> dict[str, Any]:
        """Shape a policy result into the shared resolution envelope."""
        if result.symbol is not None:
            symbol = result.symbol
            if not symbol.get("source_code"):
                symbol["source_code"] = read_source_slice(
                    symbol.get("file_path", ""),
                    symbol.get("line_start"),
                    symbol.get("line_end"),
                )
            return {"kind": "exact", "symbol": symbol, "candidates": []}
        if result.kind == "ambiguous":
            summaries = [_candidate_summary(c) for c in result.candidates]
            return {"kind": "ambiguous", "symbol": None, "candidates": summaries}
        if result.kind == "suggestion":
            summaries = [_candidate_summary(c) for c in result.candidates[:10]]
            if any(c.get("edit_distance") is not None for c in summaries):
                for candidate in summaries:
                    candidate["suggestion"] = candidate.get("edit_distance") is not None
            return {"kind": "suggestion", "symbol": None, "candidates": summaries}
        return {"kind": "not_found", "symbol": None, "candidates": []}

    @staticmethod
    def _overload_scope(result: ResolutionResult) -> tuple[Any, Any] | None:
        """Return the ``(name, parent_symbol_id)`` scope of an ambiguous list.

        Only a multi-match list whose candidates share a non-null parent is a
        sibling-overload set; the same member name in unrelated top-level
        declarations is not.
        """
        if result.kind != "ambiguous" or not result.candidates:
            return None
        first = result.candidates[0]
        if first.get("parent_symbol_id") is None:
            return None
        return first.get("name"), first.get("parent_symbol_id")

    def _attach_overload_info(
        self,
        conn: sqlite3.Connection | None,
        envelope: dict[str, Any],
        overload_scope: tuple[Any, Any] | None = None,
    ) -> dict[str, Any]:
        """Attach the overload set + ``ambiguous`` flag to a resolution envelope.

        Queries every declaration sharing the resolved symbol's name within
        its parent scope. ``ambiguous`` is ``true`` when more than one
        such declaration exists — independent of the resolution ``kind``
        signal (a ``kind: exact`` resolution over an overloaded name still
        reports ambiguity). An ambiguous multi-match envelope carries the same
        overload set through *overload_scope*. Envelopes without a resolved
        symbol or scope keep an empty overload set and ``ambiguous: false``.
        When *conn* is ``None`` a fresh read connection is opened.
        """
        symbol = envelope.get("symbol")
        name: Any = None
        parent_id: Any = None
        if symbol is not None and symbol.get("name"):
            name = symbol.get("name")
            parent_id = symbol.get("parent_symbol_id")
        elif overload_scope is not None:
            name, parent_id = overload_scope
        overloads: list[dict[str, Any]] = []
        ambiguous = False
        if name is not None:
            query = (
                "SELECT s.*, p.name AS parent_name, p.kind AS parent_kind, "
                "p.fqn AS parent_fqn "
                "FROM symbols s LEFT JOIN symbols p ON s.parent_symbol_id = p.id "
                "WHERE s.name = ? AND s.parent_symbol_id IS ? "
                "ORDER BY s.id;"
            )
            params = (name, parent_id)

            def _fetch(c: sqlite3.Connection) -> list[dict[str, Any]]:
                return [dict(r) for r in c.execute(query, params).fetchall()]

            if conn is not None:
                rows = _fetch(conn)
            else:
                with self._db.connect() as owned:
                    rows = _fetch(owned)
            for row in rows:
                row = _attach_row_signature(dict(row))
                sig = row.get("signature")
                overloads.append(
                    {
                        "fqn": row.get("fqn"),
                        "signature": sig,
                        "arity": sig.get("arity") if sig is not None else None,
                        "file_path": row.get("file_path"),
                        "line_start": row.get("line_start"),
                        "line_end": row.get("line_end"),
                    }
                )
            ambiguous = len(overloads) > 1
        envelope["overloads"] = overloads if ambiguous else []
        envelope["ambiguous"] = ambiguous
        return envelope

    def _resolve_with_signature(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        max_candidates: int | None = None,
        conn: Any | None = None,
    ) -> dict[str, Any]:
        """Signature-aware name resolution (overload disambiguation).

        When the caller supplies a ``(params)`` signature, matches arity then
        normalized parameter types against the stored overloads before any
        bare-name fallback. A unique signature-consistent overload resolves
        ``exact``; several resolve ``ambiguous`` with the ranked overload set;
        a supplied signature with no consistent overload never returns a
        contradicting one — it falls back to the ranked overload set as
        ``ambiguous`` when the bare name exists, else ``not_found``.
        """
        result = resolve_with_signature(
            parse_reference(query), candidates, max_candidates=max_candidates or 10
        )
        envelope = self._build_envelope(result)
        envelope["outcome"] = outcome_for_kind(envelope["kind"])
        return self._attach_overload_info(
            conn, envelope, overload_scope=self._overload_scope(result)
        )

    def resolve_symbol(self, query: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Resolve *query* to ``(symbol, candidates)``.

        Thin wrapper over :meth:`resolve_name` : the exact-name
        ambiguity decision and candidate shaping live in the shared envelope.
        Accepts full file-path FQNs, conventional FQNs, partial / suffix names,
        and dotted ``Class.method`` queries. Ambiguous partial names yield an
        empty symbol and a ``candidates`` disambiguation list. Resolved symbols
        include ``source_code`` (gracefully ``""`` when the file is missing).
        """
        envelope = self.resolve_name(query)
        return envelope["symbol"], envelope["candidates"]

    def lookup_by_fqn(self, fqn: str) -> dict[str, Any] | None:
        """Look up a symbol by FQN, auto-picking the first candidate.

        Thin wrapper over :meth:`resolve_name` preserving the legacy
        convenience behavior: an exact match returns the symbol; an ambiguous
        name returns ``dict(candidates[0])`` so old call sites keep working.
        """
        envelope = self.resolve_name(fqn)
        symbol = envelope["symbol"]
        if symbol is not None:
            return cast(dict[str, Any], symbol)
        candidates = envelope["candidates"]
        if candidates:
            return dict(candidates[0])
        return None

    def lookup_by_file(self, file_path: str) -> list[dict[str, Any]]:
        """Return all symbols declared in *file_path*.

        Queries by exact ``file_path`` first, then falls back to a suffix
        match and finally a bare-filename suffix match so callers can pass a
        path whose spelling differs from what was indexed. Results are
        ordered by ``line_start``.

        Args:
            file_path: The source file path (indexed spelling, relative, or
                bare filename).

        Returns:
            A list of symbol records (as ``dict``) for the file, possibly
            empty.
        """
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM symbols WHERE file_path = ? ORDER BY line_start;",
                (file_path,),
            ).fetchall()
            if not rows:
                rows = conn.execute(
                    "SELECT * FROM symbols WHERE file_path LIKE '%' || ? ORDER BY line_start;",
                    (file_path,),
                ).fetchall()
            if not rows and "/" in file_path:
                suffix = "/" + file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
                rows = conn.execute(
                    "SELECT * FROM symbols WHERE file_path LIKE '%' || ? ORDER BY line_start;",
                    (suffix,),
                ).fetchall()
            return [dict(r) for r in rows]

    def get_by_id(self, symbol_id: int) -> dict[str, Any] | None:
        """Return the symbol row for *symbol_id*, or ``None``.

        The row carries the stored identity/location fields plus the enclosing
        type's ``parent_name`` / ``parent_kind`` / ``parent_fqn``, and a parsed
        ``signature`` when the declaration has one.
        """
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT s.*, p.name AS parent_name, p.kind AS parent_kind, "
                "p.fqn AS parent_fqn "
                "FROM symbols s LEFT JOIN symbols p ON s.parent_symbol_id = p.id "
                "WHERE s.id = ?;",
                (symbol_id,),
            ).fetchone()
        return _attach_row_signature(dict(row)) if row is not None else None

    def methods_of(self, parent_symbol_id: int, name: str | None = None) -> list[dict[str, Any]]:
        """Return the member declarations of type *parent_symbol_id*.

        Optionally filters to a single method *name*. Each returned row
        carries the enclosing type's ``parent_name`` / ``parent_kind`` /
        ``parent_fqn`` plus a parsed ``signature`` (when present).
        """
        return self.methods_of_many([parent_symbol_id], name).get(parent_symbol_id, [])

    def methods_of_many(
        self, parent_symbol_ids: list[int], name: str | None = None
    ) -> dict[int, list[dict[str, Any]]]:
        """Return member declarations for many parent types in one query.

        Batches the lookup so an interface with many implementers does not
        issue one query per subtype (the implementation-lookup performance
        budget). Each returned row carries the enclosing type's ``parent_name``
        / ``parent_kind`` / ``parent_fqn`` plus a parsed ``signature``.

        Args:
            parent_symbol_ids: The enclosing type ids to fetch members for.
            name: Optional single method name filter.

        Returns:
            A mapping ``parent_symbol_id -> [member rows]`` ordered by id.
        """
        grouped: dict[int, list[dict[str, Any]]] = {pid: [] for pid in parent_symbol_ids}
        if not parent_symbol_ids:
            return grouped
        placeholders = ",".join("?" for _ in parent_symbol_ids)
        sql = (
            "SELECT s.*, p.name AS parent_name, p.kind AS parent_kind, "
            "p.fqn AS parent_fqn "
            "FROM symbols s LEFT JOIN symbols p ON s.parent_symbol_id = p.id "
            f"WHERE s.parent_symbol_id IN ({placeholders})"
        )
        params: list[Any] = list(parent_symbol_ids)
        if name is not None:
            sql += " AND s.name = ?"
            params.append(name)
        sql += " ORDER BY s.id;"
        with self._db.connect() as conn:
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        for row in rows:
            pid = row.get("parent_symbol_id")
            if pid in grouped:
                grouped[pid].append(_attach_row_signature(row))
        return grouped

    def build_symbol_catalog(self) -> dict[str, int]:
        """Query all symbols and build in-memory catalog: fqn/conventional_fqn → id."""
        catalog: dict[str, int] = {}
        with self._db.connect() as conn:
            rows = conn.execute("SELECT id, fqn, conventional_fqn FROM symbols;").fetchall()
            for row in rows:
                symbol_id = row["id"]
                fqn = row["fqn"]
                conventional_fqn = row["conventional_fqn"]
                if fqn:
                    catalog[fqn] = symbol_id
                if conventional_fqn:
                    catalog[conventional_fqn] = symbol_id
        return catalog
