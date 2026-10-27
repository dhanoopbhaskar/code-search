"""Read-only Cypher subset over the SQLite code graph.

The graph surfaces answer fixed questions (schema, outline, structural search,
dead code, architecture, coverage). This module adds a small, deliberately
strict Cypher reader so an agent can ask multi-hop and aggregate questions
without learning the internal SQLite schema.

The implementation is a hand-written lexer, recursive-descent parser, semantic
checker, and parameterized SQL compiler. It never interpolates caller text into
SQL: literals become named parameters, labels and edge types are validated
against the stored vocabulary, and user aliases never reach the SQL text. The
only dynamic SQL fragments are generated aliases such as ``n0`` and ``e1`` and
validated property keys inside ``json_extract``.

The supported subset is documented in ``README.md``. Unsupported syntax raises
an error that starts with ``unsupported``; it never silently returns an empty
result. Statements are read-only and execute under a progress-handler deadline
with row and byte caps.

Node mapping:

* Symbol labels map to ``symbols.kind``: ``Function``, ``Method``, ``Class``,
  ``Interface``, ``Enum``, ``Constructor``, ``Field``, ``Variable``,
  ``Import``, and ``TypeAlias``.
* ``File`` nodes are synthetic (one per indexed file path).
* ``Module`` nodes are synthetic (one per distinct directory).
* ``Unresolved`` nodes are synthetic evidence for an unresolved raw target.
* ``CONTAINS`` edges are synthetic from ``symbols.parent_symbol_id``.
* ``IMPORTS`` edges between ``File`` nodes come from ``module_edges``.

Absence is not proof of completeness. An empty result means the current index
contains no matching row, not that the code is absent.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from code_search.engine.graph import GRAPH_EDGE_TYPES, GraphDatabase

#: Hard cap on returned rows for any one request.
MAX_ROWS = 500
#: Default response size when the query has no ``LIMIT``.
DEFAULT_ROWS = 100
#: Hard cap on the wall-clock deadline.
MAX_TIMEOUT_MS = 30_000
#: Default wall-clock deadline.
DEFAULT_TIMEOUT_MS = 5_000
#: Soft cap on the JSON encoded rows in one response.
MAX_BYTES = 200_000
#: Maximum query text accepted (bytes of source).
MAX_QUERY_CHARS = 20_000
#: Maximum variable-length path bound. Unbounded ``*`` means ``1..3``.
MAX_VARIABLE_LENGTH = 5
#: Default upper bound for an unbounded ``*``.
DEFAULT_VARIABLE_LENGTH = 3
#: Maximum regex pattern length. Python's regex engine has no timeout.
MAX_REGEX_CHARS = 500

_AGGREGATE_FUNCTIONS = frozenset({"count", "sum", "avg", "min", "max", "collect"})
_SCALAR_FUNCTIONS = frozenset(
    {
        "labels",
        "type",
        "id",
        "coalesce",
        "tolower",
        "toupper",
        "tostring",
        "size",
        "length",
        "substring",
        "replace",
        "trim",
    }
)

#: Labels accepted in patterns, mapped to the stored ``nodes.label`` spelling.
_NODE_LABELS: dict[str, str] = {
    "function": "Function",
    "method": "Method",
    "class": "Class",
    "interface": "Interface",
    "enum": "Enum",
    "constructor": "Constructor",
    "field": "Field",
    "variable": "Variable",
    "import": "Import",
    "typealias": "TypeAlias",
    "file": "File",
    "module": "Module",
    "unresolved": "Unresolved",
}

#: Canonical label → stored ``symbols.kind`` for the non-synthetic labels.
_KIND_BY_LABEL: dict[str, str] = {
    "Function": "function",
    "Method": "method",
    "Class": "class",
    "Interface": "interface",
    "Enum": "enum",
    "Constructor": "constructor",
    "Field": "field",
    "Variable": "variable",
    "Import": "import",
    "TypeAlias": "type_alias",
}

#: Edge types accepted in patterns. ``CONTAINS`` is synthetic and structural.
_EDGE_TYPES: frozenset[str] = frozenset(GRAPH_EDGE_TYPES) | {"CONTAINS"}

#: Node columns an inline property map or property access may address.
_NODE_PROPERTIES: dict[str, str] = {
    "id": "id",
    "label": "label",
    "name": "name",
    "kind": "kind",
    "fqn": "fqn",
    "canonical_fqn": "canonical_fqn",
    "conventional_fqn": "conventional_fqn",
    "file_path": "file_path",
    "line_start": "line_start",
    "line_end": "line_end",
    "importance": "importance",
    "is_entry_point": "is_entry_point",
    "is_test": "is_test",
    "visibility": "visibility",
}

#: Edge columns a property map or property access may address directly.
_EDGE_COLUMNS: dict[str, str] = {
    "id": "id",
    "source": "source",
    "target": "target",
    "type": "type",
    "resolved": "resolved",
    "tier": "tier",
}

#: Column names when an edge is read straight from ``graph_edges``.
_DIRECT_EDGE_COLUMNS: dict[str, str] = {
    "id": "id",
    "source": "source_symbol_id",
    "target": "target_symbol_id",
    "type": "edge_type",
    "resolved": "resolved",
    "tier": "resolution_tier",
}

#: Cypher clauses that mutate the graph. They are rejected before parsing.
_WRITE_KEYWORDS = frozenset(
    {
        "CREATE",
        "MERGE",
        "DELETE",
        "DETACH",
        "SET",
        "REMOVE",
        "CALL",
        "LOAD",
        "FOREACH",
        "START",
        "USE",
        "GRANT",
        "DENY",
        "REVOKE",
        "DROP",
        "ALTER",
        "INSERT",
        "UPDATE",
    }
)

_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_COMMENT_LINE = re.compile(r"//[^\n]*")

#: Edge types that constitute a proven incoming production reference. Shared
#: with the dedicated ``find_dead_code`` surface so both answers use the same
#: vocabulary.
DEAD_CODE_EDGE_TYPES: tuple[str, ...] = (
    "CALLS",
    "USAGE",
    "CALL_REFERENCE",
    "REFERENCES",
    "IMPLEMENTS",
    "INHERITS",
)

#: Canonical dead-code query. The dedicated ``find_dead_code`` surface shares
#: the edge-type vocabulary and this predicate, so the two answers can be
#: compared directly in tests and documentation.
DEAD_CODE_CYPHER = (
    "MATCH (f:Function|Method|Constructor)\n"
    "WHERE NOT EXISTS { (f)<-[:"
    + "|".join(DEAD_CODE_EDGE_TYPES)
    + "]-(src) WHERE src.is_test = 0 }\n"
    "  AND NOT EXISTS { (:Interface)-[:CONTAINS]->(f) }\n"
    "  AND f.is_entry_point = 0\n"
    "  AND f.is_test = 0\n"
    "RETURN f.name AS name, f.fqn AS fqn, f.file_path AS file_path,\n"
    "       f.line_start AS line_start, f.importance AS importance\n"
    "ORDER BY f.fqn"
)


class CypherError(Exception):
    """A parse, semantic, or execution error with an agent-facing message."""

    def __init__(self, message: str, *, kind: str = "syntax", position: int | None = None) -> None:
        """Create an error.

        Args:
            message: Human-readable explanation. Unsupported syntax starts with
                ``unsupported``.
            kind: ``syntax``, ``semantic``, ``unsupported``, ``stale_cursor``,
                or ``execution``.
            position: Zero-based character offset in the query, when known.
        """
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.position = position

    def as_dict(self) -> dict[str, Any]:
        """Return the error as an additive payload fragment."""
        return {
            "outcome": "invalid_argument",
            "error_kind": self.kind,
            "error": self.message,
            "position": self.position,
        }


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    """One lexical token."""

    kind: str
    value: str
    pos: int


_PUNCTUATION = set("()[]{},.:-|*+/%<>=;$")
_MULTI_PUNCTUATION = ("..", "<=", ">=", "<>", "!=", "=~")
_WHITESPACE = set(" \t\r\n")


def tokenize(text: str) -> list[Token]:
    """Split *text* into tokens, discarding comments.

    Args:
        text: Cypher query text.

    Returns:
        Tokens ending with an ``EOF`` token.

    Raises:
        CypherError: On an unterminated string/backtick identifier or a
            character that is not part of the subset.
    """
    cleaned = _COMMENT_BLOCK.sub(" ", text)
    cleaned = _COMMENT_LINE.sub(" ", cleaned)
    tokens: list[Token] = []
    index = 0
    length = len(cleaned)
    while index < length:
        char = cleaned[index]
        if char in _WHITESPACE:
            index += 1
            continue
        if char in ("'", '"'):
            value, index = _read_string(cleaned, index)
            tokens.append(Token("STRING", value, index - len(value) - 1))
            continue
        if char == "`":
            value, index = _read_backtick(cleaned, index)
            tokens.append(Token("IDENT", value, index - len(value) - 2))
            continue
        if char.isdigit():
            value, index = _read_number(cleaned, index)
            tokens.append(Token("NUMBER", value, index - len(value)))
            continue
        if char.isalpha() or char == "_":
            start = index
            while index < length and (cleaned[index].isalnum() or cleaned[index] == "_"):
                index += 1
            tokens.append(Token("IDENT", cleaned[start:index], start))
            continue
        matched = next(
            (symbol for symbol in _MULTI_PUNCTUATION if cleaned.startswith(symbol, index)), None
        )
        if matched is not None:
            tokens.append(Token("PUNCT", matched, index))
            index += len(matched)
            continue
        if char in _PUNCTUATION:
            tokens.append(Token("PUNCT", char, index))
            index += 1
            continue
        raise CypherError(f"unsupported character {char!r}", kind="unsupported", position=index)
    tokens.append(Token("EOF", "", length))
    return tokens


def _read_string(text: str, index: int) -> tuple[str, int]:
    """Read a quoted Cypher string starting at *index*."""
    quote = text[index]
    index += 1
    chars: list[str] = []
    while index < len(text):
        char = text[index]
        if char == "\\":
            if index + 1 >= len(text):
                break
            escaped = text[index + 1]
            chars.append(
                {
                    "n": "\n",
                    "t": "\t",
                    "r": "\r",
                    "\\": "\\",
                    "'": "'",
                    '"': '"',
                }.get(escaped, escaped)
            )
            index += 2
            continue
        if char == quote:
            return "".join(chars), index + 1
        chars.append(char)
        index += 1
    raise CypherError("unterminated string literal", position=index)


def _read_backtick(text: str, index: int) -> tuple[str, int]:
    """Read a backtick-quoted identifier starting at *index*."""
    end = text.find("`", index + 1)
    if end < 0:
        raise CypherError("unterminated backtick identifier", position=index)
    return text[index + 1 : end], end + 1


def _read_number(text: str, index: int) -> tuple[str, int]:
    """Read an integer or decimal number starting at *index*."""
    start = index
    while index < len(text) and text[index].isdigit():
        index += 1
    if (
        index < len(text)
        and text[index] == "."
        and index + 1 < len(text)
        and text[index + 1].isdigit()
    ):
        index += 1
        while index < len(text) and text[index].isdigit():
            index += 1
    return text[start:index], index


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------


class Expr:
    """Base class for expression nodes."""


@dataclass(frozen=True)
class Literal(Expr):
    """A string, number, boolean, or null literal."""

    value: Any


@dataclass(frozen=True)
class Variable(Expr):
    """A variable reference."""

    name: str


@dataclass(frozen=True)
class Property(Expr):
    """A ``variable.property`` access."""

    base: Variable
    name: str


@dataclass(frozen=True)
class LabelTest(Expr):
    """A ``variable:Label`` predicate."""

    base: Variable
    labels: tuple[str, ...]


@dataclass(frozen=True)
class FunctionCall(Expr):
    """A scalar or aggregate function call."""

    name: str
    args: tuple[Expr, ...]
    distinct: bool = False
    star: bool = False


@dataclass(frozen=True)
class BinaryOp(Expr):
    """A binary expression."""

    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class UnaryOp(Expr):
    """A unary ``NOT`` or arithmetic sign."""

    op: str
    operand: Expr


@dataclass(frozen=True)
class ListLiteral(Expr):
    """A list literal."""

    items: tuple[Expr, ...]


@dataclass(frozen=True)
class MapLiteral(Expr):
    """A map literal."""

    entries: tuple[tuple[str, Expr], ...]


@dataclass(frozen=True)
class CaseExpr(Expr):
    """A simple or searched ``CASE`` expression."""

    operand: Expr | None
    whens: tuple[tuple[Expr, Expr], ...]
    default: Expr | None


@dataclass(frozen=True)
class ExistsExpr(Expr):
    """An ``EXISTS { ... }`` predicate."""

    patterns: tuple[PathPattern, ...]
    where: Expr | None


@dataclass(frozen=True)
class NodePattern:
    """A node pattern ``(var:Label {props})``."""

    var: str | None
    labels: tuple[str, ...]
    props: tuple[tuple[str, Expr], ...]


@dataclass(frozen=True)
class RelPattern:
    """A relationship pattern with direction, types, and optional length."""

    var: str | None
    types: tuple[str, ...]
    direction: str  # out | in | both
    length: tuple[int, int | None] | None
    props: tuple[tuple[str, Expr], ...]


@dataclass(frozen=True)
class PathPattern:
    """A node/relationship path pattern."""

    nodes: tuple[NodePattern, ...]
    rels: tuple[RelPattern, ...]


@dataclass(frozen=True)
class MatchClause:
    """A ``MATCH`` or ``OPTIONAL MATCH`` clause."""

    optional: bool
    patterns: tuple[PathPattern, ...]
    where: Expr | None


@dataclass(frozen=True)
class UnwindClause:
    """An ``UNWIND expr AS var`` clause."""

    expr: Expr
    var: str


@dataclass(frozen=True)
class Projection:
    """One ``RETURN``/``WITH`` item, or ``*`` when ``star`` is true."""

    expr: Expr | None
    alias: str | None
    star: bool = False


@dataclass(frozen=True)
class OrderItem:
    """One ``ORDER BY`` item."""

    expr: Expr
    descending: bool = False


@dataclass(frozen=True)
class WithClause:
    """A ``WITH`` clause."""

    distinct: bool
    items: tuple[Projection, ...]
    where: Expr | None
    order_by: tuple[OrderItem, ...]
    skip: int
    limit: int | None


@dataclass(frozen=True)
class ReturnClause:
    """A ``RETURN`` clause."""

    distinct: bool
    items: tuple[Projection, ...]
    order_by: tuple[OrderItem, ...]
    skip: int
    limit: int | None


@dataclass(frozen=True)
class SingleQuery:
    """A linear clause sequence."""

    clauses: tuple[MatchClause | UnwindClause | WithClause | ReturnClause, ...]


@dataclass(frozen=True)
class UnionQuery:
    """One or more single queries combined with ``UNION [ALL]``."""

    parts: tuple[SingleQuery, ...]
    union_all: tuple[bool, ...]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class _Parser:
    """Recursive-descent parser for the supported Cypher subset."""

    def __init__(self, text: str) -> None:
        self._tokens = tokenize(text)
        self._index = 0

    def parse(self) -> UnionQuery:
        """Parse the whole query text."""
        parts = [self._parse_single_query()]
        union_all: list[bool] = []
        while self._at_keyword("UNION"):
            self._advance()
            union_all.append(self._eat_keyword("ALL"))
            parts.append(self._parse_single_query())
        self._expect_kind("EOF")
        return UnionQuery(parts=tuple(parts), union_all=tuple(union_all))

    def _parse_single_query(self) -> SingleQuery:
        """Parse clauses up to ``UNION`` or end of input."""
        clauses: list[MatchClause | UnwindClause | WithClause | ReturnClause] = []
        while True:
            token = self._peek()
            if token.kind == "EOF" or self._at_keyword("UNION"):
                break
            if clauses and isinstance(clauses[-1], ReturnClause):
                raise CypherError(
                    "unsupported: clauses after RETURN",
                    kind="unsupported",
                    position=token.pos,
                )
            clauses.append(self._parse_clause())
        if not clauses:
            raise CypherError("empty query", position=self._peek().pos)
        if not isinstance(clauses[-1], ReturnClause):
            raise CypherError(
                "query must end with RETURN", kind="semantic", position=self._peek().pos
            )
        return SingleQuery(clauses=tuple(clauses))

    def _parse_clause(self) -> MatchClause | UnwindClause | WithClause | ReturnClause:
        """Parse one clause at the current position."""
        token = self._peek()
        if self._at_keyword("OPTIONAL") or self._at_keyword("MATCH"):
            return self._parse_match()
        if self._at_keyword("UNWIND"):
            return self._parse_unwind()
        if self._at_keyword("WITH"):
            return self._parse_with()
        if self._at_keyword("RETURN"):
            return self._parse_return()
        if token.kind == "IDENT" and token.value.upper() in _WRITE_KEYWORDS:
            raise CypherError(
                f"unsupported read-only query: {token.value.upper()} is not allowed",
                kind="unsupported",
                position=token.pos,
            )
        raise CypherError(
            f"expected MATCH, OPTIONAL MATCH, UNWIND, WITH, or RETURN; found {token.value!r}",
            position=token.pos,
        )

    def _parse_match(self) -> MatchClause:
        """Parse ``[OPTIONAL] MATCH pattern[, pattern]* [WHERE expr]``."""
        optional = self._eat_keyword("OPTIONAL")
        self._expect_keyword("MATCH")
        patterns = [self._parse_path()]
        while self._eat_value(","):
            patterns.append(self._parse_path())
        where = self._parse_where() if self._at_keyword("WHERE") else None
        if optional and where is not None:
            raise CypherError(
                "unsupported: WHERE directly after OPTIONAL MATCH; "
                "use WITH ... WHERE after the optional match",
                kind="unsupported",
                position=self._peek().pos,
            )
        return MatchClause(optional=optional, patterns=tuple(patterns), where=where)

    def _parse_unwind(self) -> UnwindClause:
        """Parse ``UNWIND expr AS var``."""
        self._expect_keyword("UNWIND")
        expr = self._parse_expression()
        self._expect_keyword("AS")
        var = self._expect_ident()
        return UnwindClause(expr=expr, var=var)

    def _parse_with(self) -> WithClause:
        """Parse ``WITH [DISTINCT] items [WHERE] [ORDER BY] [SKIP] [LIMIT]``."""
        self._expect_keyword("WITH")
        distinct = self._eat_keyword("DISTINCT")
        items = self._parse_projections()
        where = self._parse_where() if self._at_keyword("WHERE") else None
        order_by = self._parse_order_by()
        skip = self._parse_skip()
        limit = self._parse_limit()
        return WithClause(
            distinct=distinct,
            items=tuple(items),
            where=where,
            order_by=tuple(order_by),
            skip=skip,
            limit=limit,
        )

    def _parse_return(self) -> ReturnClause:
        """Parse ``RETURN [DISTINCT] items [ORDER BY] [SKIP] [LIMIT]``."""
        self._expect_keyword("RETURN")
        distinct = self._eat_keyword("DISTINCT")
        items = self._parse_projections()
        order_by = self._parse_order_by()
        skip = self._parse_skip()
        limit = self._parse_limit()
        return ReturnClause(
            distinct=distinct, items=tuple(items), order_by=tuple(order_by), skip=skip, limit=limit
        )

    def _parse_projections(self) -> list[Projection]:
        """Parse a comma-separated projection list, including ``*``."""
        items = [self._parse_projection()]
        while self._eat_value(","):
            items.append(self._parse_projection())
        return items

    def _parse_projection(self) -> Projection:
        """Parse one projection item."""
        if self._at_value("*"):
            self._advance()
            return Projection(expr=None, alias=None, star=True)
        expr = self._parse_expression()
        alias = None
        if self._eat_keyword("AS"):
            alias = self._expect_ident()
        return Projection(expr=expr, alias=alias)

    def _parse_order_by(self) -> list[OrderItem]:
        """Parse an optional ``ORDER BY`` list."""
        if not self._at_keyword("ORDER"):
            return []
        self._advance()
        self._expect_keyword("BY")
        items = [self._parse_order_item()]
        while self._eat_value(","):
            items.append(self._parse_order_item())
        return items

    def _parse_order_item(self) -> OrderItem:
        """Parse one ``ORDER BY`` item."""
        expr = self._parse_expression()
        descending = False
        if self._eat_keyword("DESC"):
            descending = True
        else:
            self._eat_keyword("ASC")
        return OrderItem(expr=expr, descending=descending)

    def _parse_skip(self) -> int:
        """Parse ``SKIP n``; defaults to zero."""
        if not self._eat_keyword("SKIP"):
            return 0
        return self._expect_non_negative_int("SKIP")

    def _parse_limit(self) -> int | None:
        """Parse ``LIMIT n``; defaults to ``None``."""
        if not self._eat_keyword("LIMIT"):
            return None
        return self._expect_non_negative_int("LIMIT")

    def _parse_where(self) -> Expr:
        """Parse ``WHERE expr``."""
        self._expect_keyword("WHERE")
        return self._parse_expression()

    def _parse_path(self) -> PathPattern:
        """Parse one node/relationship path."""
        nodes = [self._parse_node()]
        rels: list[RelPattern] = []
        while self._at_value("-") or self._at_value("<"):
            rels.append(self._parse_relationship())
            nodes.append(self._parse_node())
        return PathPattern(nodes=tuple(nodes), rels=tuple(rels))

    def _parse_node(self) -> NodePattern:
        """Parse ``(var:Label {props})``."""
        self._expect_value("(")
        var = None
        if self._peek().kind == "IDENT":
            var = self._advance().value
        labels: list[str] = []
        if self._eat_value(":"):
            labels.append(self._expect_ident())
            while self._eat_value("|"):
                labels.append(self._expect_ident())
        props: tuple[tuple[str, Expr], ...] = ()
        if self._at_value("{"):
            props = tuple(self._parse_map_entries())
        self._expect_value(")")
        return NodePattern(var=var, labels=tuple(labels), props=props)

    def _parse_relationship(self) -> RelPattern:
        """Parse a relationship pattern in any supported direction."""
        if self._eat_value("<"):
            self._expect_value("-")
            detail = self._parse_rel_detail() if self._at_value("[") else (None, (), None, ())
            self._expect_value("-")
            return RelPattern(
                var=detail[0],
                types=detail[1],
                direction="in",
                length=detail[2],
                props=detail[3],
            )
        self._expect_value("-")
        detail = self._parse_rel_detail() if self._at_value("[") else (None, (), None, ())
        self._expect_value("-")
        direction = "out" if self._eat_value(">") else "both"
        return RelPattern(
            var=detail[0],
            types=detail[1],
            direction=direction,
            length=detail[2],
            props=detail[3],
        )

    def _parse_rel_detail(
        self,
    ) -> tuple[
        str | None, tuple[str, ...], tuple[int, int | None] | None, tuple[tuple[str, Expr], ...]
    ]:
        """Parse ``[...]`` between relationship dashes."""
        self._expect_value("[")
        var = None
        if self._peek().kind == "IDENT":
            var = self._advance().value
        types: list[str] = []
        if self._eat_value(":"):
            types.append(self._expect_ident())
            while self._eat_value("|"):
                types.append(self._expect_ident())
        length = None
        if self._eat_value("*"):
            lower = 1
            upper: int | None = None
            saw_lower = False
            if self._peek().kind == "NUMBER":
                lower = int(self._peek().value)
                saw_lower = True
                self._advance()
            if self._eat_value(".."):
                if self._peek().kind == "NUMBER":
                    upper = int(self._peek().value)
                    self._advance()
            elif saw_lower:
                upper = lower
            length = (lower, upper)
        props: tuple[tuple[str, Expr], ...] = ()
        if self._at_value("{"):
            props = tuple(self._parse_map_entries())
        self._expect_value("]")
        return var, tuple(types), length, props

    def _parse_map_entries(self) -> list[tuple[str, Expr]]:
        """Parse ``{key: expr, ...}``."""
        self._expect_value("{")
        entries: list[tuple[str, Expr]] = []
        if not self._at_value("}"):
            entries.append(self._parse_map_entry())
            while self._eat_value(","):
                entries.append(self._parse_map_entry())
        self._expect_value("}")
        return entries

    def _parse_map_entry(self) -> tuple[str, Expr]:
        """Parse one map entry."""
        token = self._peek()
        if token.kind not in ("IDENT", "STRING"):
            raise CypherError("expected a map key", position=token.pos)
        key = self._advance().value
        self._expect_value(":")
        return key, self._parse_expression()

    # -- expressions --------------------------------------------------------

    def _parse_expression(self) -> Expr:
        """Parse a full expression."""
        return self._parse_or()

    def _parse_or(self) -> Expr:
        """Parse ``OR`` expressions."""
        expr = self._parse_xor()
        while self._eat_keyword("OR"):
            expr = BinaryOp("OR", expr, self._parse_xor())
        return expr

    def _parse_xor(self) -> Expr:
        """Parse ``XOR`` expressions."""
        expr = self._parse_and()
        while self._eat_keyword("XOR"):
            expr = BinaryOp("XOR", expr, self._parse_and())
        return expr

    def _parse_and(self) -> Expr:
        """Parse ``AND`` expressions."""
        expr = self._parse_not()
        while self._eat_keyword("AND"):
            expr = BinaryOp("AND", expr, self._parse_not())
        return expr

    def _parse_not(self) -> Expr:
        """Parse ``NOT`` expressions."""
        if self._eat_keyword("NOT"):
            return UnaryOp("NOT", self._parse_not())
        return self._parse_comparison()

    def _parse_comparison(self) -> Expr:
        """Parse comparisons, ``IN``, string predicates, and ``IS NULL``."""
        expr = self._parse_additive()
        while True:
            token = self._peek()
            if token.kind == "PUNCT" and token.value in (
                "=",
                "<",
                ">",
                "<=",
                ">=",
                "<>",
                "!=",
                "=~",
            ):
                self._advance()
                right = self._parse_additive()
                op = "<>" if token.value == "!=" else token.value
                expr = BinaryOp(op, expr, right)
                continue
            if self._at_keyword("IN"):
                self._advance()
                expr = BinaryOp("IN", expr, self._parse_additive())
                continue
            if self._at_keyword("CONTAINS"):
                self._advance()
                expr = BinaryOp("CONTAINS", expr, self._parse_additive())
                continue
            if self._at_keyword("STARTS"):
                self._advance()
                self._expect_keyword("WITH")
                expr = BinaryOp("STARTS WITH", expr, self._parse_additive())
                continue
            if self._at_keyword("ENDS"):
                self._advance()
                self._expect_keyword("WITH")
                expr = BinaryOp("ENDS WITH", expr, self._parse_additive())
                continue
            if self._at_keyword("IS"):
                self._advance()
                negated = self._eat_keyword("NOT")
                self._expect_keyword("NULL")
                expr = UnaryOp("IS NOT NULL" if negated else "IS NULL", expr)
                continue
            return expr

    def _parse_additive(self) -> Expr:
        """Parse ``+``/``-`` expressions."""
        expr = self._parse_multiplicative()
        while self._at_value("+") or self._at_value("-"):
            op = self._advance().value
            expr = BinaryOp(op, expr, self._parse_multiplicative())
        return expr

    def _parse_multiplicative(self) -> Expr:
        """Parse ``*``/``/``/``%`` expressions."""
        expr = self._parse_unary()
        while self._at_value("*") or self._at_value("/") or self._at_value("%"):
            op = self._advance().value
            expr = BinaryOp(op, expr, self._parse_unary())
        return expr

    def _parse_unary(self) -> Expr:
        """Parse unary signs."""
        if self._at_value("-"):
            self._advance()
            return UnaryOp("-", self._parse_unary())
        if self._at_value("+"):
            self._advance()
            return UnaryOp("+", self._parse_unary())
        return self._parse_postfix()

    def _parse_postfix(self) -> Expr:
        """Parse property access and label tests after a primary expression."""
        expr = self._parse_primary()
        while True:
            if self._eat_value("."):
                if not isinstance(expr, Variable):
                    raise CypherError(
                        "unsupported: property access is only supported on variables",
                        kind="unsupported",
                        position=self._peek().pos,
                    )
                expr = Property(base=expr, name=self._expect_ident())
                continue
            if self._at_value(":"):
                if not isinstance(expr, Variable):
                    raise CypherError(
                        "unsupported: label tests are only supported on variables",
                        kind="unsupported",
                        position=self._peek().pos,
                    )
                self._advance()
                labels = [self._expect_ident()]
                while self._eat_value("|"):
                    labels.append(self._expect_ident())
                expr = LabelTest(base=expr, labels=tuple(labels))
                continue
            return expr

    def _parse_primary(self) -> Expr:
        """Parse a literal, variable, function call, list, map, CASE, or EXISTS."""
        token = self._peek()
        if token.kind == "NUMBER":
            self._advance()
            return Literal(_number(token.value))
        if token.kind == "STRING":
            self._advance()
            return Literal(token.value)
        if token.kind == "PUNCT" and token.value == "$":
            raise CypherError(
                "unsupported: query parameters; use inline literals",
                kind="unsupported",
                position=token.pos,
            )
        if token.kind == "PUNCT" and token.value == "(":
            self._advance()
            expr = self._parse_expression()
            self._expect_value(")")
            return expr
        if token.kind == "PUNCT" and token.value == "[":
            return self._parse_list()
        if token.kind == "PUNCT" and token.value == "{":
            return MapLiteral(entries=tuple(self._parse_map_entries()))
        if token.kind == "IDENT":
            upper = token.value.upper()
            if upper == "CASE":
                return self._parse_case()
            if upper == "EXISTS":
                return self._parse_exists()
            if upper == "TRUE":
                self._advance()
                return Literal(True)
            if upper == "FALSE":
                self._advance()
                return Literal(False)
            if upper == "NULL":
                self._advance()
                return Literal(None)
            self._advance()
            if self._at_value("("):
                return self._parse_function(token.value)
            return Variable(token.value)
        raise CypherError(
            f"expected an expression; found {token.value!r}",
            position=token.pos,
        )

    def _parse_list(self) -> ListLiteral:
        """Parse ``[a, b, ...]``."""
        self._expect_value("[")
        items: list[Expr] = []
        if not self._at_value("]"):
            items.append(self._parse_expression())
            while self._eat_value(","):
                items.append(self._parse_expression())
        self._expect_value("]")
        return ListLiteral(items=tuple(items))

    def _parse_function(self, name: str) -> FunctionCall:
        """Parse a function call after its name."""
        self._expect_value("(")
        distinct = self._eat_keyword("DISTINCT")
        if self._at_value("*"):
            self._advance()
            self._expect_value(")")
            return FunctionCall(name=name.lower(), args=(), distinct=distinct, star=True)
        args: list[Expr] = []
        if not self._at_value(")"):
            args.append(self._parse_expression())
            while self._eat_value(","):
                args.append(self._parse_expression())
        self._expect_value(")")
        return FunctionCall(name=name.lower(), args=tuple(args), distinct=distinct)

    def _parse_case(self) -> CaseExpr:
        """Parse simple and searched ``CASE`` expressions."""
        self._expect_keyword("CASE")
        operand = None if self._at_keyword("WHEN") else self._parse_expression()
        whens: list[tuple[Expr, Expr]] = []
        while self._eat_keyword("WHEN"):
            condition = self._parse_expression()
            self._expect_keyword("THEN")
            whens.append((condition, self._parse_expression()))
        if not whens:
            raise CypherError("CASE requires at least one WHEN", position=self._peek().pos)
        default = self._parse_expression() if self._eat_keyword("ELSE") else None
        self._expect_keyword("END")
        return CaseExpr(operand=operand, whens=tuple(whens), default=default)

    def _parse_exists(self) -> ExistsExpr:
        """Parse ``EXISTS { pattern[, pattern]* [WHERE expr] }``."""
        self._expect_keyword("EXISTS")
        if not self._at_value("{"):
            raise CypherError(
                "unsupported: use EXISTS { pattern }",
                kind="unsupported",
                position=self._peek().pos,
            )
        self._advance()
        patterns = [self._parse_path()]
        while self._eat_value(","):
            patterns.append(self._parse_path())
        where = self._parse_where() if self._at_keyword("WHERE") else None
        self._expect_value("}")
        return ExistsExpr(patterns=tuple(patterns), where=where)

    # -- token helpers ------------------------------------------------------

    def _peek(self, offset: int = 0) -> Token:
        """Return the token at *offset* from the current position."""
        return self._tokens[min(self._index + offset, len(self._tokens) - 1)]

    def _advance(self) -> Token:
        """Consume and return the current token."""
        token = self._peek()
        self._index += 1
        return token

    def _at_keyword(self, keyword: str) -> bool:
        """Return whether the current token is *keyword* (case-insensitive)."""
        token = self._peek()
        return token.kind == "IDENT" and token.value.upper() == keyword

    def _eat_keyword(self, keyword: str) -> bool:
        """Consume *keyword* if present."""
        if self._at_keyword(keyword):
            self._advance()
            return True
        return False

    def _expect_keyword(self, keyword: str) -> None:
        """Consume *keyword* or raise."""
        if not self._eat_keyword(keyword):
            token = self._peek()
            raise CypherError(f"expected {keyword}; found {token.value!r}", position=token.pos)

    def _at_value(self, value: str) -> bool:
        """Return whether the current token is punctuation *value*."""
        token = self._peek()
        return token.kind == "PUNCT" and token.value == value

    def _eat_value(self, value: str) -> bool:
        """Consume punctuation *value* if present."""
        if self._at_value(value):
            self._advance()
            return True
        return False

    def _expect_value(self, value: str) -> None:
        """Consume punctuation *value* or raise."""
        if not self._eat_value(value):
            token = self._peek()
            raise CypherError(f"expected {value!r}; found {token.value!r}", position=token.pos)

    def _expect_kind(self, kind: str) -> None:
        """Consume a token of *kind* or raise."""
        token = self._peek()
        if token.kind != kind:
            raise CypherError(f"expected {kind}; found {token.value!r}", position=token.pos)
        self._advance()

    def _expect_ident(self) -> str:
        """Consume and return an identifier."""
        token = self._peek()
        if token.kind != "IDENT":
            raise CypherError(f"expected an identifier; found {token.value!r}", position=token.pos)
        self._advance()
        return token.value

    def _expect_non_negative_int(self, label: str) -> int:
        """Consume a non-negative integer literal."""
        token = self._peek()
        if token.kind != "NUMBER" or "." in token.value:
            raise CypherError(f"{label} requires a non-negative integer", position=token.pos)
        value = int(token.value)
        if value < 0:
            raise CypherError(f"{label} requires a non-negative integer", position=token.pos)
        self._advance()
        return value


def _number(text: str) -> int | float:
    """Convert a numeric token to ``int`` or ``float``."""
    return float(text) if "." in text else int(text)


# ---------------------------------------------------------------------------
# SQL compiler
# ---------------------------------------------------------------------------


@dataclass
class _Binding:
    """A variable binding in the current query scope."""

    kind: str  # node | edge | scalar
    alias: str = ""
    expr: str = ""
    direct_edge: bool = False
    endpoint: str | None = None
    direct_node: bool = False


@dataclass
class _NodeRef:
    """A node pattern already joined into the current select."""

    alias: str
    created: bool


@dataclass
class _PartResult:
    """A compiled single-query part."""

    sql: str
    columns: list[str]
    skip: int
    limit: int | None
    order_items: tuple[OrderItem, ...]


@dataclass
class CompiledQuery:
    """A compiled, parameterized query ready for execution."""

    sql: str
    params: dict[str, Any]
    columns: list[str]
    skip: int
    limit: int | None
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    order_items: tuple[OrderItem, ...] = field(default_factory=tuple)


@dataclass
class _Usage:
    """Graph vocabulary a query needs, used to keep the base CTEs small.

    ``labels``/``edge_types`` are ``None`` when the query contains an
    unlabelled node or an untyped relationship, which means every label or type
    is in scope.
    """

    labels: set[str] | None = field(default_factory=set)
    edge_types: set[str] | None = field(default_factory=set)
    needs_nodes: bool = False
    needs_edges: bool = False


def _collect_usage(parsed: UnionQuery) -> _Usage:
    """Walk the AST and collect the labels, edge types, and base CTEs needed."""
    usage = _Usage()

    def walk_path(path: PathPattern) -> None:
        usage.needs_nodes = True
        for node in path.nodes:
            if not node.labels:
                usage.labels = None
            elif usage.labels is not None:
                usage.labels.update(_Compiler._canonical_labels(node.labels))
            for _key, value in node.props:
                walk_expr(value)
        for rel in path.rels:
            if rel.length is None:
                usage.needs_edges = True
            if not rel.types:
                usage.edge_types = None
            elif usage.edge_types is not None:
                usage.edge_types.update(_Compiler._canonical_edge_types(rel.types))
            for _key, value in rel.props:
                walk_expr(value)

    def walk_expr(expr: Expr) -> None:
        if isinstance(expr, ExistsExpr):
            for path in expr.patterns:
                walk_path(path)
            if expr.where is not None:
                walk_expr(expr.where)
            return
        if isinstance(expr, BinaryOp):
            walk_expr(expr.left)
            walk_expr(expr.right)
            return
        if isinstance(expr, UnaryOp):
            walk_expr(expr.operand)
            return
        if isinstance(expr, ListLiteral):
            for item in expr.items:
                walk_expr(item)
            return
        if isinstance(expr, MapLiteral):
            for _key, value in expr.entries:
                walk_expr(value)
            return
        if isinstance(expr, CaseExpr):
            if expr.operand is not None:
                walk_expr(expr.operand)
            for condition, result in expr.whens:
                walk_expr(condition)
                walk_expr(result)
            if expr.default is not None:
                walk_expr(expr.default)
            return
        if isinstance(expr, FunctionCall):
            for arg in expr.args:
                walk_expr(arg)

    for part in parsed.parts:
        for clause in part.clauses:
            if isinstance(clause, MatchClause):
                for pattern in clause.patterns:
                    walk_path(pattern)
                if clause.where is not None:
                    walk_expr(clause.where)
            elif isinstance(clause, UnwindClause):
                walk_expr(clause.expr)
            elif isinstance(clause, WithClause):
                for item in clause.items:
                    if item.expr is not None:
                        walk_expr(item.expr)
                if clause.where is not None:
                    walk_expr(clause.where)
                for order in clause.order_by:
                    walk_expr(order.expr)
            else:
                for item in clause.items:
                    if item.expr is not None:
                        walk_expr(item.expr)
                for order in clause.order_by:
                    walk_expr(order.expr)
    return usage


class _AliasFactory:
    """Generate unique, injection-safe SQL aliases."""

    def __init__(self) -> None:
        self._next = 0

    def new(self, prefix: str) -> str:
        """Return a fresh alias such as ``n3``."""
        alias = f"{prefix}{self._next}"
        self._next += 1
        return alias


class _Compiler:
    """Compile one parsed query part to parameterized SQL."""

    def __init__(self, usage: _Usage | None = None) -> None:
        self.aliases = _AliasFactory()
        self.params: dict[str, Any] = {}
        self.ctes: list[str] = []
        self.from_sql: list[str] = []
        self.where: list[str] = []
        self.scope: dict[str, _Binding] = {}
        self.usage = usage or _Usage(labels=None, edge_types=None)
        # Correlated EXISTS predicates read graph_edges directly so SQLite can
        # use the target/source index instead of scanning a materialized CTE.
        self.direct_edges = False

    # -- parameters ---------------------------------------------------------

    def _param(self, value: Any) -> str:
        """Register *value* and return its named placeholder."""
        name = f"p{len(self.params)}"
        self.params[name] = value
        return f":{name}"

    # -- query parts --------------------------------------------------------

    def compile_part(self, part: SingleQuery, *, apply_modifiers: bool) -> _PartResult:
        """Compile one linear clause sequence.

        Args:
            part: The parsed single query.
            apply_modifiers: Apply the final ``RETURN`` order/skip/limit. A
                ``UNION`` applies the last part's modifiers outside the union
                to keep one deterministic order for the combined rows.
        """
        for clause in part.clauses:
            if isinstance(clause, MatchClause):
                self._compile_match(clause)
            elif isinstance(clause, UnwindClause):
                self._compile_unwind(clause)
            elif isinstance(clause, WithClause):
                self._compile_with(clause)
            else:
                return self._compile_return(clause, apply_modifiers=apply_modifiers)
        raise CypherError("query must end with RETURN", kind="semantic")

    def _compile_match(self, clause: MatchClause) -> None:
        """Compile a ``MATCH``/``OPTIONAL MATCH`` clause."""
        if clause.optional and len(clause.patterns) > 1:
            raise CypherError(
                "unsupported: multiple patterns in OPTIONAL MATCH",
                kind="unsupported",
            )
        for pattern in clause.patterns:
            self._compile_path(pattern, optional=clause.optional)
        if clause.where is not None:
            self._add_where(clause.where)

    def _compile_path(self, path: PathPattern, *, optional: bool) -> None:
        """Compile one path pattern into joins and filters."""
        variable_length = [index for index, rel in enumerate(path.rels) if rel.length is not None]
        if variable_length:
            if optional:
                raise CypherError(
                    "unsupported: variable-length paths inside OPTIONAL MATCH",
                    kind="unsupported",
                )
            if len(path.rels) != 1:
                raise CypherError(
                    "unsupported: variable-length relationships must be the only hop in a path",
                    kind="unsupported",
                )
            self._compile_variable_path(path, optional=optional)
            return

        start = self._compile_start_node(path.nodes[0], optional=optional)
        current = start
        for rel, node_pattern in zip(path.rels, path.nodes[1:], strict=True):
            current = self._compile_hop(current, rel, node_pattern, optional=optional)

    @staticmethod
    def _can_use_direct_edge(rel: RelPattern) -> bool:
        """Return whether a relationship can be read straight from ``graph_edges``."""
        if not rel.types:
            return False
        types = {edge_type.upper() for edge_type in rel.types}
        return types.isdisjoint({"CONTAINS", "IMPORTS"}) and types <= set(GRAPH_EDGE_TYPES)

    def _compile_variable_path(self, path: PathPattern, *, optional: bool) -> None:
        """Compile a one-hop variable-length path into a recursive CTE."""
        rel = path.rels[0]
        if rel.var is not None:
            raise CypherError(
                "unsupported: relationship variables on variable-length paths",
                kind="unsupported",
            )
        start_pattern = path.nodes[0]
        end_pattern = path.nodes[1]
        start = self._compile_start_node(start_pattern, optional=optional)
        lower, upper = self._length_bounds(rel.length)
        path_cte = self.aliases.new("p")
        types = self._canonical_edge_types(rel.types)
        synthetic = {"CONTAINS", "IMPORTS"} & set(types)
        if synthetic:
            raise CypherError(
                "unsupported: variable-length paths traverse stored symbol "
                f"edges only; {', '.join(sorted(synthetic))} is synthetic",
                kind="unsupported",
            )
        type_clause = ""
        if types:
            placeholders = ", ".join(self._param(edge_type) for edge_type in types)
            type_clause = f" AND e.edge_type IN ({placeholders})"
        seed_where = self._label_clause(start_pattern, "nodes")
        seed_conditions: list[str] = []
        if seed_where:
            seed_conditions.append(seed_where.removeprefix(" WHERE "))
        else:
            seed_conditions.append("nodes.label NOT IN ('File', 'Module', 'Unresolved')")
        # Anchor the recursive CTE on the start pattern's inline properties.
        # Without this the CTE walks from every node of the label and the outer
        # join discards the unreachable rows afterwards; on a 100k-symbol index
        # a name-filtered two-hop query paid for all 100k seeds.
        for key, value in start_pattern.props:
            seed_conditions.append(self._node_property_condition("nodes", key, value))
        seed_where = " WHERE " + " AND ".join(seed_conditions)
        if rel.direction == "out":
            recursive = (
                f"SELECT {path_cte}.start, e.target_symbol_id, {path_cte}.hops + 1 "
                f"FROM {path_cte} JOIN graph_edges e INDEXED BY idx_edges_source_type "
                f"ON e.source_symbol_id = {path_cte}.node "
                f"AND e.target_symbol_id IS NOT NULL "
                f"WHERE {path_cte}.hops < {upper}{type_clause}"
            )
        elif rel.direction == "in":
            recursive = (
                f"SELECT {path_cte}.start, e.source_symbol_id, {path_cte}.hops + 1 "
                f"FROM {path_cte} JOIN graph_edges e INDEXED BY idx_edges_target_type "
                f"ON e.target_symbol_id = {path_cte}.node "
                f"WHERE {path_cte}.hops < {upper}{type_clause}"
            )
        else:
            recursive = (
                f"SELECT {path_cte}.start, e.target_symbol_id, {path_cte}.hops + 1 "
                f"FROM {path_cte} JOIN graph_edges e INDEXED BY idx_edges_source_type "
                f"ON e.source_symbol_id = {path_cte}.node "
                f"AND e.target_symbol_id IS NOT NULL "
                f"WHERE {path_cte}.hops < {upper}{type_clause} "
                f"UNION SELECT {path_cte}.start, e.source_symbol_id, {path_cte}.hops + 1 "
                f"FROM {path_cte} JOIN graph_edges e INDEXED BY idx_edges_target_type "
                f"ON e.target_symbol_id = {path_cte}.node "
                f"WHERE {path_cte}.hops < {upper}{type_clause}"
            )
        self.ctes.append(
            f"{path_cte}(start, node, hops) AS ("
            f"SELECT id, id, 0 FROM nodes{seed_where} UNION {recursive})"
        )
        on = [
            f"{path_cte}.start = {start.alias}.id",
            f"{path_cte}.hops BETWEEN {self._param(lower)} AND {self._param(upper)}",
        ]
        if end_pattern.var is not None and end_pattern.var in self.scope:
            binding = self.scope[end_pattern.var]
            if binding.kind != "node":
                raise CypherError(f"variable {end_pattern.var!r} is not a node", kind="semantic")
            on.append(f"{binding.alias}.id = {path_cte}.node")
            self._append_join("JOIN", path_cte, on)
            self._apply_node_filters(end_pattern, binding.alias)
            return
        end_alias = self.aliases.new("n")
        self._append_join("JOIN", path_cte, on)
        self._append_join(
            "JOIN",
            f"nodes {end_alias}",
            [
                f"{end_alias}.id = {path_cte}.node",
                *self._node_filter_conditions(end_pattern, end_alias),
            ],
        )
        if end_pattern.var is not None:
            self.scope[end_pattern.var] = _Binding(
                kind="node", alias=end_alias, expr=f"{end_alias}.id"
            )

    def _compile_start_node(self, pattern: NodePattern, *, optional: bool) -> _NodeRef:
        """Join or reuse the first node of a path."""
        if pattern.var is not None and pattern.var in self.scope:
            binding = self.scope[pattern.var]
            if binding.kind != "node":
                raise CypherError(
                    f"variable {pattern.var!r} is not a node",
                    kind="semantic",
                )
            self._apply_node_filters(pattern, binding.alias)
            return _NodeRef(alias=binding.alias, created=False)
        alias = self.aliases.new("n")
        conditions = self._node_conditions(pattern, alias)
        join_kind = "LEFT JOIN" if optional else "JOIN"
        self._append_join(join_kind, f"nodes {alias}", conditions)
        if pattern.var is not None:
            self.scope[pattern.var] = _Binding(kind="node", alias=alias, expr=f"{alias}.id")
        return _NodeRef(alias=alias, created=True)

    def _compile_hop(
        self,
        source: _NodeRef,
        rel: RelPattern,
        target_pattern: NodePattern,
        *,
        optional: bool,
    ) -> _NodeRef:
        """Compile one fixed-length relationship and its target node."""
        edge_alias = self.aliases.new("e")
        direct = self.direct_edges and self._can_use_direct_edge(rel)
        target_bound = target_pattern.var is not None and target_pattern.var in self.scope
        target_alias = (
            self.scope[target_pattern.var].alias
            if target_bound and target_pattern.var is not None
            else self.aliases.new("n")
        )
        conditions = self._edge_conditions(
            rel,
            edge_alias,
            source.alias,
            target_alias,
            direction_known=target_bound,
            direct=direct,
        )
        target_column = "target_symbol_id" if direct else "target"
        source_column = "source_symbol_id" if direct else "source"
        if rel.direction == "out":
            endpoint_column = target_column
        elif rel.direction == "in":
            endpoint_column = source_column
        else:
            endpoint_column = (
                f"CASE WHEN {edge_alias}.{source_column} = {source.alias}.id "
                f"THEN {edge_alias}.{target_column} ELSE {edge_alias}.{source_column} END"
            )
        if direct and not target_bound:
            for key, value in target_pattern.props:
                conditions.append(
                    self._symbol_property_condition(f"({endpoint_column})", key, value)
                )
        if rel.var is not None:
            if rel.var in self.scope:
                raise CypherError(f"variable {rel.var!r} is already bound", kind="semantic")
            self.scope[rel.var] = _Binding(
                kind="edge",
                alias=edge_alias,
                expr=f"{edge_alias}.id",
                direct_edge=direct,
            )
        join_kind = "LEFT JOIN" if optional else "JOIN"
        if direct:
            edge_table = "graph_edges"
            if rel.direction == "out":
                edge_table += f" {edge_alias} INDEXED BY idx_edges_source_type"
            elif rel.direction == "in":
                edge_table += f" {edge_alias} INDEXED BY idx_edges_target_type"
            else:
                edge_table += f" {edge_alias}"
        else:
            edge_table = f"edges {edge_alias}"
        self._append_join(join_kind, edge_table, conditions)
        if target_bound:
            if target_pattern.var is not None:
                self._apply_node_filters(target_pattern, target_alias)
            return _NodeRef(alias=target_alias, created=False)
        node_conditions: list[str] = [f"{target_alias}.id = {endpoint_column}"]
        if direct:
            node_conditions.extend(self._direct_label_conditions(target_pattern, target_alias))
            node_table = "symbols"
        else:
            node_conditions.extend(self._node_filter_conditions(target_pattern, target_alias))
            node_table = "nodes"
        self._append_join(join_kind, f"{node_table} {target_alias}", node_conditions)
        if target_pattern.var is not None:
            self.scope[target_pattern.var] = _Binding(
                kind="node",
                alias=target_alias,
                expr=f"{target_alias}.id",
                endpoint=f"({endpoint_column})" if direct else None,
                direct_node=direct,
            )
        return _NodeRef(alias=target_alias, created=True)

    def _compile_unwind(self, clause: UnwindClause) -> None:
        """Compile ``UNWIND`` as a JSON table-valued join."""
        if clause.var in self.scope:
            raise CypherError(f"variable {clause.var!r} is already bound", kind="semantic")
        if _contains_aggregate(clause.expr):
            raise CypherError(
                "aggregate functions are not allowed in UNWIND; use WITH first",
                kind="semantic",
            )
        expr = self._expr_sql(clause.expr)
        alias = self.aliases.new("u")
        self._append_join("CROSS JOIN", f"json_each({expr}) AS {alias}", [])
        self.scope[clause.var] = _Binding(kind="scalar", expr=f"{alias}.value")

    def _compile_with(self, clause: WithClause) -> None:
        """Compile ``WITH`` into a CTE and rebind the projected variables."""
        selects: list[str] = []
        columns: list[str] = []
        groups: list[str] = []
        rebinds: list[tuple[str, str, str]] = []
        has_aggregate = any(
            not item.star and item.expr is not None and _contains_aggregate(item.expr)
            for item in clause.items
        )
        for item in clause.items:
            if item.star:
                raise CypherError(
                    "unsupported: WITH *; list the variables explicitly", kind="unsupported"
                )
            assert item.expr is not None
            name = self._output_name(item)
            if name in columns:
                raise CypherError(
                    f"duplicate projected name {name!r} in WITH; add AS aliases",
                    kind="semantic",
                )
            if isinstance(item.expr, Variable) and item.expr.name in self.scope:
                binding = self.scope[item.expr.name]
                if binding.kind in ("node", "edge"):
                    column = f"v{len(selects)}"
                    selects.append(f"{binding.expr} AS {column}")
                    columns.append(name)
                    rebinds.append((name, binding.kind, column))
                    continue
            column = f"v{len(selects)}"
            expr_sql = self._value_sql(item.expr)
            selects.append(f"{expr_sql} AS {column}")
            columns.append(name)
            if not _contains_aggregate(item.expr):
                groups.append(expr_sql)
            rebinds.append((name, "scalar", column))
        cte = self.aliases.new("w")
        distinct = "DISTINCT " if clause.distinct else ""
        select_sql = f"SELECT {distinct}{', '.join(selects)}"
        from_sql = self._from_sql()
        where_sql = f" WHERE {' AND '.join(self.where)}" if self.where else ""
        group_sql = f" GROUP BY {', '.join(groups)}" if has_aggregate and groups else ""
        order_sql = self._order_sql_for_with(clause.order_by, columns)
        limit_sql = ""
        if clause.limit is not None:
            limit_sql = f" LIMIT {self._param(clause.limit)} OFFSET {self._param(clause.skip)}"
        elif clause.skip:
            limit_sql = f" LIMIT -1 OFFSET {self._param(clause.skip)}"
        self.ctes.append(
            f"{cte} AS ({select_sql} FROM {from_sql}{where_sql}{group_sql}{order_sql}{limit_sql})"
        )
        self.from_sql = [cte]
        self.where = []
        self.scope = {}
        for name, kind, column in rebinds:
            if kind == "node":
                alias = self.aliases.new("n")
                self._append_join("JOIN", f"nodes {alias}", [f"{alias}.id = {cte}.{column}"])
                self.scope[name] = _Binding(kind="node", alias=alias, expr=f"{alias}.id")
            elif kind == "edge":
                alias = self.aliases.new("e")
                self._append_join("JOIN", f"edges {alias}", [f"{alias}.id = {cte}.{column}"])
                self.scope[name] = _Binding(kind="edge", alias=alias, expr=f"{alias}.id")
            else:
                self.scope[name] = _Binding(kind="scalar", expr=f"{cte}.{column}")
        if clause.where is not None:
            self._add_where(clause.where)

    def _compile_return(self, clause: ReturnClause, *, apply_modifiers: bool) -> _PartResult:
        """Compile the final ``RETURN`` projection."""
        selects: list[str] = []
        columns: list[str] = []
        groups: list[str] = []
        has_aggregate = any(
            not item.star and item.expr is not None and _contains_aggregate(item.expr)
            for item in clause.items
        )
        for item in clause.items:
            if item.star:
                for name, binding in self.scope.items():
                    if name in columns:
                        continue
                    column = f"c{len(selects)}"
                    selects.append(f"{self._binding_sql(binding)} AS {column}")
                    columns.append(name)
                    if not has_aggregate:
                        groups.append(self._binding_sql(binding))
                continue
            assert item.expr is not None
            name = self._output_name(item)
            if name in columns:
                base = name
                suffix = 2
                while f"{base}_{suffix}" in columns:
                    suffix += 1
                name = f"{base}_{suffix}"
            column = f"c{len(selects)}"
            expr_sql = self._value_sql(item.expr)
            selects.append(f"{expr_sql} AS {column}")
            columns.append(name)
            if not _contains_aggregate(item.expr):
                groups.append(expr_sql)
        if not selects:
            raise CypherError("RETURN requires at least one item", kind="semantic")
        distinct = "DISTINCT " if clause.distinct else ""
        select_sql = f"SELECT {distinct}{', '.join(selects)}"
        from_sql = self._from_sql()
        where_sql = f" WHERE {' AND '.join(self.where)}" if self.where else ""
        group_sql = f" GROUP BY {', '.join(groups)}" if has_aggregate and groups else ""
        if apply_modifiers:
            order_sql = self._order_sql(clause.order_by, columns, len(selects))
            skip = clause.skip
            limit = clause.limit
        else:
            order_sql = ""
            skip = 0
            limit = None
        sql = f"{self._with_clause()}{select_sql} FROM {from_sql}{where_sql}{group_sql}{order_sql}"
        return _PartResult(
            sql=sql,
            columns=columns,
            skip=skip,
            limit=limit,
            order_items=clause.order_by,
        )

    # -- joins --------------------------------------------------------------

    def _from_sql(self) -> str:
        """Return the current FROM clause, using a one-row source when empty."""
        return " ".join(self.from_sql) if self.from_sql else "(SELECT 1 AS one)"

    def _append_join(self, kind: str, table: str, conditions: list[str]) -> None:
        """Append a join with optional ``ON`` conditions."""
        if self.from_sql:
            if conditions:
                self.from_sql.append(f"{kind} {table} ON {' AND '.join(conditions)}")
            else:
                self.from_sql.append(f"{kind} {table}")
            return
        if kind == "LEFT JOIN":
            self.from_sql.append(
                f"(SELECT 1 AS one) {kind} {table} ON {' AND '.join(conditions) or '1=1'}"
            )
            return
        self.from_sql.append(table)
        if conditions:
            self.where.extend(conditions)

    def _node_conditions(self, pattern: NodePattern, alias: str) -> list[str]:
        """Return label/property conditions for a new node join."""
        return self._node_filter_conditions(pattern, alias)

    def _node_filter_conditions(
        self, pattern: NodePattern, alias: str, *, include_props: bool = True
    ) -> list[str]:
        """Return label and inline-property conditions for *pattern*."""
        conditions: list[str] = []
        labels = self._canonical_labels(pattern.labels)
        if labels:
            placeholders = ", ".join(self._param(label) for label in labels)
            conditions.append(f"{alias}.label IN ({placeholders})")
        if include_props:
            for key, value in pattern.props:
                conditions.append(self._node_property_condition(alias, key, value))
        return conditions

    def _apply_node_filters(self, pattern: NodePattern, alias: str) -> None:
        """Apply filters to an already-bound node."""
        direct = any(
            binding.kind == "node" and binding.alias == alias and binding.direct_node
            for binding in self.scope.values()
        )
        if not direct:
            self.where.extend(self._node_filter_conditions(pattern, alias))
            return
        self.where.extend(self._direct_label_conditions(pattern, alias))
        for key, value in pattern.props:
            self.where.append(self._symbol_property_condition(f"({alias}.id)", key, value))

    def _direct_label_conditions(self, pattern: NodePattern, alias: str) -> list[str]:
        """Return label filters for a node read straight from ``symbols``."""
        labels = self._canonical_labels(pattern.labels)
        if not labels:
            return []
        kinds = sorted({_KIND_BY_LABEL[label] for label in labels if label in _KIND_BY_LABEL})
        if not kinds:
            return ["0"]
        placeholders = ", ".join(self._param(kind) for kind in kinds)
        return [f"{alias}.kind IN ({placeholders})"]

    @staticmethod
    def _label_sql(alias: str) -> str:
        """Return the canonical-label expression for a raw ``symbols`` row."""
        return (
            "CASE "
            f"{alias}.kind "
            "WHEN 'function' THEN 'Function' "
            "WHEN 'method' THEN 'Method' "
            "WHEN 'class' THEN 'Class' "
            "WHEN 'interface' THEN 'Interface' "
            "WHEN 'enum' THEN 'Enum' "
            "WHEN 'constructor' THEN 'Constructor' "
            "WHEN 'field' THEN 'Field' "
            "WHEN 'variable' THEN 'Variable' "
            "WHEN 'import' THEN 'Import' "
            "WHEN 'type_alias' THEN 'TypeAlias' "
            "END"
        )

    def _edge_conditions(
        self,
        rel: RelPattern,
        edge_alias: str,
        source_alias: str,
        target_alias: str,
        *,
        direction_known: bool,
        direct: bool = False,
    ) -> list[str]:
        """Return direction/type/property conditions for a relationship join."""
        source_column = "source_symbol_id" if direct else "source"
        target_column = "target_symbol_id" if direct else "target"
        type_column = "edge_type" if direct else "type"
        if rel.direction == "out":
            conditions = [f"{edge_alias}.{source_column} = {source_alias}.id"]
            if direction_known:
                conditions.append(f"{edge_alias}.{target_column} = {target_alias}.id")
        elif rel.direction == "in":
            conditions = [f"{edge_alias}.{target_column} = {source_alias}.id"]
            if direction_known:
                conditions.append(f"{edge_alias}.{source_column} = {target_alias}.id")
        elif direction_known:
            conditions = [
                f"(({edge_alias}.{source_column} = {source_alias}.id AND "
                f"{edge_alias}.{target_column} = {target_alias}.id) OR "
                f"({edge_alias}.{source_column} = {target_alias}.id AND "
                f"{edge_alias}.{target_column} = {source_alias}.id))"
            ]
        else:
            conditions = [
                f"({edge_alias}.{source_column} = {source_alias}.id OR "
                f"{edge_alias}.{target_column} = {source_alias}.id)"
            ]
        types = self._canonical_edge_types(rel.types)
        if types:
            placeholders = ", ".join(self._param(edge_type) for edge_type in types)
            conditions.append(f"{edge_alias}.{type_column} IN ({placeholders})")
        for key, value in rel.props:
            conditions.append(self._edge_property_condition(edge_alias, key, value, direct=direct))
        return conditions

    # -- WHERE --------------------------------------------------------------

    def _add_where(self, expr: Expr) -> None:
        """Append a WHERE predicate, rejecting aggregates."""
        if _contains_aggregate(expr):
            raise CypherError(
                "aggregate functions are not allowed in WHERE; use WITH ... WHERE",
                kind="semantic",
            )
        self.where.append(f"({self._expr_sql(expr)})")

    # -- projection helpers -------------------------------------------------

    def _output_name(self, item: Projection) -> str:
        """Derive the output/scope name for a projection item."""
        if item.alias:
            return item.alias
        expr = item.expr
        if isinstance(expr, Variable):
            return expr.name
        if isinstance(expr, Property):
            return expr.name
        if isinstance(expr, FunctionCall):
            return expr.name
        raise CypherError(
            "expression requires an AS alias in WITH/RETURN",
            kind="semantic",
        )

    def _order_sql(
        self, items: tuple[OrderItem, ...], columns: list[str], select_count: int
    ) -> str:
        """Compile a final ORDER BY, defaulting to every output column."""
        if not items:
            return " ORDER BY " + ", ".join(str(index) for index in range(1, select_count + 1))
        parts: list[str] = []
        for item in items:
            direction = " DESC" if item.descending else " ASC"
            if isinstance(item.expr, Variable) and item.expr.name in columns:
                parts.append(f"{columns.index(item.expr.name) + 1}{direction}")
                continue
            if isinstance(item.expr, Property) and item.expr.name in columns:
                parts.append(f"{columns.index(item.expr.name) + 1}{direction}")
                continue
            parts.append(f"{self._expr_sql(item.expr)}{direction}")
        return " ORDER BY " + ", ".join(parts)

    def _order_sql_for_with(self, items: tuple[OrderItem, ...], columns: list[str]) -> str:
        """Compile a WITH ORDER BY using output-column ordinals."""
        if not items:
            return ""
        parts: list[str] = []
        for item in items:
            direction = " DESC" if item.descending else " ASC"
            name = self._order_name(item.expr)
            if name is not None and name in columns:
                parts.append(f"{columns.index(name) + 1}{direction}")
            else:
                parts.append(f"{self._expr_sql(item.expr)}{direction}")
        return " ORDER BY " + ", ".join(parts)

    @staticmethod
    def _order_name(expr: Expr) -> str | None:
        """Return a simple output name for an ORDER BY expression."""
        if isinstance(expr, Variable):
            return expr.name
        if isinstance(expr, Property):
            return expr.name
        if isinstance(expr, FunctionCall):
            return expr.name
        return None

    def _binding_sql(self, binding: _Binding) -> str:
        """Return the value SQL for a bound variable used as a whole value."""
        if binding.kind == "node":
            alias = binding.alias
            label_sql = self._label_sql(alias) if binding.direct_node else f"{alias}.label"
            return (
                "JSON_OBJECT('id', "
                f"{alias}.id, 'label', {label_sql}, 'name', {alias}.name, "
                f"'kind', {alias}.kind, 'fqn', {alias}.fqn, "
                f"'file_path', {alias}.file_path, "
                f"'line_start', {alias}.line_start, 'line_end', {alias}.line_end)"
            )
        if binding.kind == "edge":
            alias = binding.alias
            columns = _DIRECT_EDGE_COLUMNS if binding.direct_edge else _EDGE_COLUMNS
            return (
                "JSON_OBJECT('id', "
                f"{alias}.{columns['id']}, 'type', {alias}.{columns['type']}, "
                f"'source', {alias}.{columns['source']}, "
                f"'target', {alias}.{columns['target']}, "
                f"'resolved', {alias}.{columns['resolved']}, "
                f"'tier', {alias}.{columns['tier']})"
            )
        return binding.expr

    # -- expression compiler ------------------------------------------------

    def _value_sql(self, expr: Expr) -> str:
        """Compile an expression whose whole value is returned or collected."""
        if isinstance(expr, Variable) and expr.name in self.scope:
            binding = self.scope[expr.name]
            if binding.kind in ("node", "edge"):
                return self._binding_sql(binding)
        if isinstance(expr, FunctionCall) and expr.name == "collect":
            return self._function_sql(expr)
        return self._expr_sql(expr)

    def _expr_sql(self, expr: Expr) -> str:
        """Compile an expression to a scalar SQL fragment."""
        if isinstance(expr, Literal):
            if expr.value is None:
                return "NULL"
            if isinstance(expr.value, bool):
                return "1" if expr.value else "0"
            return self._param(expr.value)
        if isinstance(expr, Variable):
            binding = self.scope.get(expr.name)
            if binding is None:
                raise CypherError(f"unknown variable {expr.name!r}", kind="semantic")
            return binding.expr
        if isinstance(expr, Property):
            return self._property_sql(expr)
        if isinstance(expr, LabelTest):
            binding = self._node_binding(expr.base.name)
            labels = self._canonical_labels(expr.labels)
            placeholders = ", ".join(self._param(label) for label in labels)
            return f"({binding.alias}.label IN ({placeholders}))"
        if isinstance(expr, FunctionCall):
            return self._function_sql(expr)
        if isinstance(expr, BinaryOp):
            return self._binary_sql(expr)
        if isinstance(expr, UnaryOp):
            return self._unary_sql(expr)
        if isinstance(expr, ListLiteral):
            values = ", ".join(self._value_sql(item) for item in expr.items)
            return f"json_array({values})"
        if isinstance(expr, MapLiteral):
            parts: list[str] = []
            for key, value in expr.entries:
                parts.append(self._param(key))
                parts.append(self._value_sql(value))
            return f"json_object({', '.join(parts)})"
        if isinstance(expr, CaseExpr):
            return self._case_sql(expr)
        if isinstance(expr, ExistsExpr):
            return self._exists_sql(expr)
        raise CypherError("unsupported expression", kind="unsupported")

    def _property_sql(self, expr: Property) -> str:
        """Compile a variable property access."""
        binding = self.scope.get(expr.base.name)
        if binding is None:
            raise CypherError(f"unknown variable {expr.base.name!r}", kind="semantic")
        if binding.kind == "node":
            if binding.direct_node and expr.name == "label":
                return self._label_sql(binding.alias)
            column = _NODE_PROPERTIES.get(expr.name)
            if column is None:
                raise CypherError(
                    f"unsupported property {expr.name!r} on a node; allowed: "
                    f"{', '.join(sorted(_NODE_PROPERTIES))}",
                    kind="unsupported",
                )
            return f"{binding.alias}.{column}"
        if binding.kind == "edge":
            columns = _DIRECT_EDGE_COLUMNS if binding.direct_edge else _EDGE_COLUMNS
            if expr.name == "line":
                return (
                    f"CAST(COALESCE(json_extract({binding.alias}.properties, '$.line'), 0) "
                    "AS INTEGER)"
                )
            column = columns.get(expr.name)
            if column is not None:
                return f"{binding.alias}.{column}"
            _validate_property_key(expr.name)
            key = self._param(expr.name)
            return f"json_extract({binding.alias}.properties, '$.' || {key})"
        raise CypherError(
            f"property access {expr.base.name}.{expr.name} requires a node or relationship",
            kind="semantic",
        )

    def _function_sql(self, expr: FunctionCall) -> str:
        """Compile a supported aggregate or scalar function."""
        name = expr.name
        args = expr.args
        if name == "count":
            if expr.star:
                return "COUNT(*)"
            self._check_arity(name, args, 1)
            inner = self._value_sql(args[0])
            return f"COUNT(DISTINCT {inner})" if expr.distinct else f"COUNT({inner})"
        if name in ("sum", "avg", "min", "max"):
            self._check_arity(name, args, 1)
            inner = self._value_sql(args[0])
            sql_name = name.upper()
            return f"{sql_name}(DISTINCT {inner})" if expr.distinct else f"{sql_name}({inner})"
        if name == "collect":
            self._check_arity(name, args, 1)
            inner = self._value_sql(args[0])
            return (
                f"json_group_array(DISTINCT {inner})"
                if expr.distinct
                else f"json_group_array({inner})"
            )
        if name == "labels":
            self._check_arity(name, args, 1)
            return self._node_binding_value(args[0], "labels")
        if name == "type":
            self._check_arity(name, args, 1)
            return self._edge_binding_expr(args[0], "type")
        if name == "id":
            self._check_arity(name, args, 1)
            if not isinstance(args[0], Variable):
                raise CypherError("id() requires a variable", kind="semantic")
            id_binding = self.scope.get(args[0].name)
            if id_binding is None or id_binding.kind not in ("node", "edge"):
                raise CypherError("id() requires a node or relationship", kind="semantic")
            return id_binding.expr
        if name == "coalesce":
            if not args:
                raise CypherError("coalesce() requires at least one argument", kind="semantic")
            return f"COALESCE({', '.join(self._value_sql(arg) for arg in args)})"
        if name in ("tolower", "toupper"):
            self._check_arity(name, args, 1)
            sql_name = "LOWER" if name == "tolower" else "UPPER"
            return f"{sql_name}({self._value_sql(args[0])})"
        if name == "tostring":
            self._check_arity(name, args, 1)
            return f"CAST({self._value_sql(args[0])} AS TEXT)"
        if name in ("size", "length"):
            self._check_arity(name, args, 1)
            return f"LENGTH({self._value_sql(args[0])})"
        if name == "substring":
            if len(args) not in (2, 3):
                raise CypherError("substring() requires 2 or 3 arguments", kind="semantic")
            value = self._value_sql(args[0])
            start = self._value_sql(args[1])
            if len(args) == 2:
                return f"SUBSTR({value}, ({start}) + 1)"
            return f"SUBSTR({value}, ({start}) + 1, {self._value_sql(args[2])})"
        if name == "replace":
            self._check_arity(name, args, 3)
            return "REPLACE({}, {}, {})".format(*(self._value_sql(arg) for arg in args))
        if name == "trim":
            self._check_arity(name, args, 1)
            return f"TRIM({self._value_sql(args[0])})"
        if name in _AGGREGATE_FUNCTIONS or name in _SCALAR_FUNCTIONS:
            raise CypherError(f"unsupported function signature {name}()", kind="unsupported")
        raise CypherError(f"unsupported function {name}()", kind="unsupported")

    def _node_binding_value(self, arg: Expr, function: str) -> str:
        """Return the single node label for ``labels()``."""
        if not isinstance(arg, Variable):
            raise CypherError(f"{function}() requires a node variable", kind="semantic")
        binding = self._node_binding(arg.name)
        if binding.direct_node:
            return self._label_sql(binding.alias)
        return binding.alias + ".label"

    def _edge_binding_expr(self, arg: Expr, function: str) -> str:
        """Return the relationship type for ``type()``."""
        if not isinstance(arg, Variable):
            raise CypherError(f"{function}() requires a relationship variable", kind="semantic")
        binding = self.scope.get(arg.name)
        if binding is None or binding.kind != "edge":
            raise CypherError(f"{function}() requires a relationship variable", kind="semantic")
        columns = _DIRECT_EDGE_COLUMNS if binding.direct_edge else _EDGE_COLUMNS
        return f"{binding.alias}.{columns['type']}"

    def _node_binding(self, name: str) -> _Binding:
        """Return a node binding or raise."""
        binding = self.scope.get(name)
        if binding is None:
            raise CypherError(f"unknown variable {name!r}", kind="semantic")
        if binding.kind != "node":
            raise CypherError(f"variable {name!r} is not a node", kind="semantic")
        return binding

    @staticmethod
    def _check_arity(name: str, args: tuple[Expr, ...], expected: int) -> None:
        """Enforce a fixed function arity."""
        if len(args) != expected:
            raise CypherError(f"{name}() requires {expected} argument(s)", kind="semantic")

    def _binary_sql(self, expr: BinaryOp) -> str:
        """Compile a binary operator."""
        if expr.op in ("=", "<", ">", "<=", ">=", "<>"):
            rewritten = self._direct_comparison_sql(expr)
            if rewritten is not None:
                return rewritten
        left = self._expr_sql(expr.left)
        right = self._expr_sql(expr.right)
        op = expr.op
        if op in ("AND", "OR"):
            return f"(({left}) {op} ({right}))"
        if op == "XOR":
            return f"((({left}) AND NOT ({right})) OR (NOT ({left}) AND ({right})))"
        if op == "IN":
            if isinstance(expr.right, ListLiteral):
                if not expr.right.items:
                    return "0"
                values = ", ".join(self._value_sql(item) for item in expr.right.items)
                return f"(({left}) IN ({values}))"
            return f"(({left}) IN (SELECT value FROM json_each({right})))"
        if op == "CONTAINS":
            return f"(INSTR({left}, {right}) > 0)"
        if op == "STARTS WITH":
            return f"(SUBSTR({left}, 1, LENGTH({right})) = {right})"
        if op == "ENDS WITH":
            return f"(({right}) = '' OR SUBSTR({left}, -LENGTH({right})) = {right})"
        if op == "=~":
            return f"(REGEXP({right}, {left}) = 1)"
        return f"(({left}) {op} ({right}))"

    def _direct_comparison_sql(self, expr: BinaryOp) -> str | None:
        """Rewrite a node property comparison onto the edge endpoint.

        Inside ``EXISTS`` a property filter on a freshly joined node is much
        cheaper as ``edge.endpoint IN (SELECT id FROM symbols WHERE col op ?)``
        than as a predicate on the materialized ``nodes`` CTE, which otherwise
        tempts SQLite into building and scanning an automatic index per row.
        """
        if not self.direct_edges:
            return None
        flipped = {"<": ">", ">": "<", "<=": ">=", ">=": "<=", "=": "=", "<>": "<>"}
        for property_expr, other, flip in (
            (expr.left, expr.right, False),
            (expr.right, expr.left, True),
        ):
            if not isinstance(property_expr, Property):
                continue
            binding = self.scope.get(property_expr.base.name)
            if (
                binding is None
                or binding.kind != "node"
                or binding.endpoint is None
                or property_expr.name not in _NODE_PROPERTIES
                or property_expr.name == "label"
            ):
                continue
            column = _NODE_PROPERTIES[property_expr.name]
            operator = flipped[expr.op] if flip else expr.op
            value = self._value_sql(other)
            return (
                f"(({binding.endpoint}) IN (SELECT id FROM symbols "
                f"WHERE {column} {operator} {value}))"
            )
        return None

    def _unary_sql(self, expr: UnaryOp) -> str:
        """Compile a unary operator."""
        operand = self._expr_sql(expr.operand)
        if expr.op == "NOT":
            return f"(NOT ({operand}))"
        if expr.op == "IS NULL":
            return f"(({operand}) IS NULL)"
        if expr.op == "IS NOT NULL":
            return f"(({operand}) IS NOT NULL)"
        return f"({expr.op}{operand})"

    def _case_sql(self, expr: CaseExpr) -> str:
        """Compile a simple or searched CASE."""
        parts = ["CASE"]
        if expr.operand is not None:
            parts.append(self._expr_sql(expr.operand))
        for condition, result in expr.whens:
            parts.append(f"WHEN {self._expr_sql(condition)} THEN {self._value_sql(result)}")
        if expr.default is not None:
            parts.append(f"ELSE {self._value_sql(expr.default)}")
        parts.append("END")
        return "(" + " ".join(parts) + ")"

    def _exists_sql(self, expr: ExistsExpr) -> str:
        """Compile a correlated EXISTS subquery."""
        saved_from = self.from_sql
        saved_where = self.where
        saved_ctes = self.ctes
        saved_scope = self.scope
        saved_direct = self.direct_edges
        self.from_sql = []
        self.where = []
        self.ctes = []
        self.scope = dict(saved_scope)
        self.direct_edges = True
        try:
            for pattern in expr.patterns:
                self._compile_path(pattern, optional=False)
            if expr.where is not None:
                self._add_where(expr.where)
            if self.ctes:
                raise CypherError(
                    "unsupported: variable-length paths inside EXISTS", kind="unsupported"
                )
            if not self.from_sql:
                if self.where:
                    return f"({' AND '.join(self.where)})"
                return "1"
            from_sql = " ".join(self.from_sql)
            where_sql = f" WHERE {' AND '.join(self.where)}" if self.where else ""
            return f"EXISTS (SELECT 1 FROM {from_sql}{where_sql})"
        finally:
            self.from_sql = saved_from
            self.where = saved_where
            self.ctes = saved_ctes
            self.scope = saved_scope
            self.direct_edges = saved_direct

    # -- vocabulary ---------------------------------------------------------

    @staticmethod
    def _canonical_labels(labels: tuple[str, ...]) -> list[str]:
        """Validate and canonicalize pattern labels."""
        result: list[str] = []
        for label in labels:
            key = re.sub(r"[^a-z0-9]", "", label.lower())
            canonical = _NODE_LABELS.get(key)
            if canonical is None:
                raise CypherError(
                    f"unsupported label {label!r}; use one of "
                    f"{', '.join(sorted(set(_NODE_LABELS.values())))}",
                    kind="unsupported",
                )
            result.append(canonical)
        return result

    @staticmethod
    def _canonical_edge_types(types: tuple[str, ...]) -> list[str]:
        """Validate and canonicalize relationship types."""
        result: list[str] = []
        for edge_type in types:
            upper = edge_type.upper()
            if upper not in _EDGE_TYPES:
                raise CypherError(
                    f"unsupported relationship type {edge_type!r}; use one of "
                    f"{', '.join(sorted(_EDGE_TYPES))}",
                    kind="unsupported",
                )
            result.append(upper)
        return result

    @staticmethod
    def _length_bounds(length: tuple[int, int | None] | None) -> tuple[int, int]:
        """Return ``(lower, upper)`` for a variable-length relationship."""
        if length is None:
            return 1, 1
        lower, upper = length
        if upper is None:
            upper = DEFAULT_VARIABLE_LENGTH
        if lower < 1:
            raise CypherError(
                "unsupported: variable-length lower bound must be at least 1",
                kind="unsupported",
            )
        if upper < lower:
            raise CypherError(
                "variable-length upper bound is smaller than the lower bound",
                kind="semantic",
            )
        if upper > MAX_VARIABLE_LENGTH:
            raise CypherError(
                f"unsupported: variable-length upper bound exceeds {MAX_VARIABLE_LENGTH}",
                kind="unsupported",
            )
        return lower, upper

    def _label_clause(self, pattern: NodePattern, alias: str) -> str:
        """Return a label-only WHERE fragment (used inside recursive CTEs)."""
        if not pattern.labels:
            return ""
        labels = self._canonical_labels(pattern.labels)
        placeholders = ", ".join(self._param(label) for label in labels)
        return f" WHERE {alias}.label IN ({placeholders})"

    def _symbol_property_condition(self, endpoint: str, key: str, value: Expr) -> str:
        """Move a node property filter onto an edge endpoint for EXISTS lookups.

        Correlated ``EXISTS`` predicates perform much better when the filter is
        an indexed ``source_symbol_id IN (SELECT id FROM symbols WHERE ...)``
        than when SQLite builds a ``nodes`` automatic index on the property.
        """
        column = _NODE_PROPERTIES.get(key)
        if column is None or key == "label":
            raise CypherError(
                f"unsupported node property {key!r} inside EXISTS",
                kind="unsupported",
            )
        return f"{endpoint} IN (SELECT id FROM symbols WHERE {column} = {self._value_sql(value)})"

    def _node_property_condition(self, alias: str, key: str, value: Expr) -> str:
        """Compile an inline node property equality."""
        column = _NODE_PROPERTIES.get(key)
        if column is None:
            raise CypherError(
                f"unsupported node property {key!r}; allowed: "
                f"{', '.join(sorted(_NODE_PROPERTIES))}",
                kind="unsupported",
            )
        return f"{alias}.{column} = {self._value_sql(value)}"

    def _edge_property_condition(
        self, alias: str, key: str, value: Expr, *, direct: bool = False
    ) -> str:
        """Compile an inline relationship property equality."""
        columns = _DIRECT_EDGE_COLUMNS if direct else _EDGE_COLUMNS
        column = columns.get(key)
        if column is not None:
            return f"{alias}.{column} = {self._value_sql(value)}"
        _validate_property_key(key)
        return (
            f"json_extract({alias}.properties, '$.' || {self._param(key)}) = "
            f"{self._value_sql(value)}"
        )

    # -- assembly -----------------------------------------------------------

    def _with_clause(self) -> str:
        """Render the CTE prefix, including only the base CTEs this query needs."""
        ctes = [*self._base_ctes(), *self.ctes]
        if not ctes:
            return ""
        return "WITH RECURSIVE " + ", ".join(ctes) + " "

    def _base_ctes(self) -> list[str]:
        """Return the shared graph CTEs required by the query vocabulary."""
        labels = self.usage.labels
        need_unresolved = labels is None or "Unresolved" in labels
        ctes: list[str] = []
        if need_unresolved:
            ctes.append(_UNRESOLVED_CTE)
        if self.usage.needs_nodes:
            ctes.append(self._nodes_cte(labels))
        if self.usage.needs_edges:
            ctes.append(self._edges_cte(labels, need_unresolved))
        return ctes

    def _nodes_cte(self, labels: set[str] | None) -> str:
        """Build the ``nodes`` CTE for the labels the query can match."""
        branches: list[str] = []
        kind_names = (
            None
            if labels is None
            else sorted({_KIND_BY_LABEL[label] for label in labels if label in _KIND_BY_LABEL})
        )
        if kind_names is None or kind_names:
            select = _SYMBOL_NODE_SELECT
            if kind_names is not None:
                placeholders = ", ".join(self._param(kind) for kind in kind_names)
                select += f" WHERE s.kind IN ({placeholders})"
            branches.append(select)
        if labels is None or "File" in labels:
            branches.append(_FILE_NODE_SELECT)
        if labels is None or "Module" in labels:
            branches.append(_MODULE_NODE_SELECT)
        if labels is None or "Unresolved" in labels:
            branches.append(_UNRESOLVED_NODE_SELECT)
        return f"nodes({_NODE_COLUMNS}) AS (" + " UNION ALL ".join(branches) + ")"

    def _edges_cte(self, labels: set[str] | None, need_unresolved: bool) -> str:
        """Build the ``edges`` CTE for the types the query can traverse."""
        branches = [_GRAPH_EDGE_SELECT_JOINED if need_unresolved else _GRAPH_EDGE_SELECT_RESOLVED]
        edge_types = self.usage.edge_types
        if edge_types is None or "CONTAINS" in edge_types:
            branches.append(_CONTAINS_EDGE_SELECT)
        if (edge_types is None or "IMPORTS" in edge_types) and (labels is None or "File" in labels):
            branches.append(_MODULE_EDGE_SELECT)
        return f"edges({_EDGE_CTE_COLUMNS}) AS (" + " UNION ALL ".join(branches) + ")"


_NODE_COLUMNS = (
    "id, label, name, kind, fqn, canonical_fqn, conventional_fqn, file_path, "
    "line_start, line_end, importance, is_entry_point, is_test, visibility"
)

_EDGE_CTE_COLUMNS = "id, source, target, type, resolved, tier, properties"

_UNRESOLVED_CTE = """
unresolved_nodes(name, id) AS (
    SELECT name, -(3000000000 + ROW_NUMBER() OVER (ORDER BY name))
    FROM (
        SELECT DISTINCT target_raw AS name
        FROM graph_edges
        WHERE resolved = 0 AND target_symbol_id IS NULL
          AND target_raw IS NOT NULL AND target_raw != ''
    )
)
"""

_SYMBOL_NODE_SELECT = """
    SELECT s.id,
           CASE s.kind
               WHEN 'function' THEN 'Function'
               WHEN 'method' THEN 'Method'
               WHEN 'class' THEN 'Class'
               WHEN 'interface' THEN 'Interface'
               WHEN 'enum' THEN 'Enum'
               WHEN 'constructor' THEN 'Constructor'
               WHEN 'field' THEN 'Field'
               WHEN 'variable' THEN 'Variable'
               WHEN 'import' THEN 'Import'
               WHEN 'type_alias' THEN 'TypeAlias'
           END,
           s.name, s.kind, s.fqn, s.canonical_fqn, s.conventional_fqn, s.file_path,
           s.line_start, s.line_end, COALESCE(s.importance, 0),
           s.is_entry_point, s.is_test, s.visibility
    FROM symbols s
"""

_FILE_NODE_SELECT = """
    SELECT -MIN(s.id), 'File', cypher_basename(s.file_path), 'file',
           s.file_path, NULL, NULL, s.file_path, 0, 0, 0, 0, 0, NULL
    FROM symbols s
    GROUP BY s.file_path
"""

_MODULE_NODE_SELECT = """
    SELECT -(1000000000 + ROW_NUMBER() OVER (ORDER BY d.dir)),
           'Module', d.dir, 'module', d.dir, NULL, NULL, d.dir, 0, 0, 0, 0, 0, NULL
    FROM (SELECT DISTINCT cypher_dirname(s.file_path) AS dir FROM symbols s) d
"""

_UNRESOLVED_NODE_SELECT = """
    SELECT u.id, 'Unresolved', u.name, 'unresolved', u.name, NULL, NULL,
           '', 0, 0, 0, 0, 0, NULL
    FROM unresolved_nodes u
"""

_GRAPH_EDGE_SELECT_JOINED = """
    SELECT e.id, e.source_symbol_id,
           COALESCE(e.target_symbol_id, u.id),
           e.edge_type, e.resolved,
           COALESCE(e.resolution_tier, ''), COALESCE(e.properties, '{}')
    FROM graph_edges e
    LEFT JOIN unresolved_nodes u ON u.name = e.target_raw
"""

_GRAPH_EDGE_SELECT_RESOLVED = """
    SELECT e.id, e.source_symbol_id, e.target_symbol_id,
           e.edge_type, e.resolved,
           COALESCE(e.resolution_tier, ''), COALESCE(e.properties, '{}')
    FROM graph_edges e
    WHERE e.target_symbol_id IS NOT NULL
"""

_CONTAINS_EDGE_SELECT = """
    SELECT -(1000000000 + s.id), s.parent_symbol_id, s.id, 'CONTAINS', 1,
           'structural', '{}'
    FROM symbols s
    WHERE s.parent_symbol_id IS NOT NULL
"""

_MODULE_EDGE_SELECT = """
    SELECT -(2000000000 + m.id),
           -(SELECT MIN(s2.id) FROM symbols s2 WHERE s2.file_path = m.source_path),
           -(SELECT MIN(s2.id) FROM symbols s2 WHERE s2.file_path = m.target_path),
           m.relation, m.resolved, 'module', '{}'
    FROM module_edges m
    WHERE m.target_path IS NOT NULL
"""


def _validate_property_key(key: str) -> None:
    """Validate a JSON property key before embedding it in SQL."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        raise CypherError(f"unsupported property key {key!r}", kind="unsupported")


def _contains_aggregate(expr: Expr) -> bool:
    """Return whether *expr* contains an aggregate function call."""
    if isinstance(expr, FunctionCall):
        return expr.name in _AGGREGATE_FUNCTIONS or any(
            _contains_aggregate(arg) for arg in expr.args
        )
    if isinstance(expr, BinaryOp):
        return _contains_aggregate(expr.left) or _contains_aggregate(expr.right)
    if isinstance(expr, UnaryOp):
        return _contains_aggregate(expr.operand)
    if isinstance(expr, ListLiteral):
        return any(_contains_aggregate(item) for item in expr.items)
    if isinstance(expr, MapLiteral):
        return any(_contains_aggregate(value) for _key, value in expr.entries)
    if isinstance(expr, CaseExpr):
        return (
            (expr.operand is not None and _contains_aggregate(expr.operand))
            or any(
                _contains_aggregate(condition) or _contains_aggregate(result)
                for condition, result in expr.whens
            )
            or (expr.default is not None and _contains_aggregate(expr.default))
        )
    if isinstance(expr, LabelTest):
        return False
    if isinstance(expr, ExistsExpr):
        return False
    return False


def compile_cypher(query: str) -> CompiledQuery:
    """Parse and compile *query* to parameterized SQL.

    Args:
        query: Cypher query text.

    Returns:
        The compiled query. ``limit`` is the query's own ``LIMIT`` (``None``
        when absent), and ``skip`` is its ``SKIP``. The executor adds the
        response cap and any cursor offset.

    Raises:
        CypherError: On syntax, semantic, or unsupported-syntax errors.
    """
    if not query.strip():
        raise CypherError("empty query", kind="syntax")
    if len(query) > MAX_QUERY_CHARS:
        raise CypherError(f"query is longer than {MAX_QUERY_CHARS} characters", kind="syntax")
    parsed = _Parser(query).parse()
    usage = _collect_usage(parsed)
    if len(parsed.parts) == 1:
        compiler = _Compiler(usage)
        result = compiler.compile_part(parsed.parts[0], apply_modifiers=True)
        return CompiledQuery(
            sql=result.sql,
            params=compiler.params,
            columns=result.columns,
            skip=result.skip,
            limit=result.limit,
            order_items=result.order_items,
        )

    compiled: list[_PartResult] = []
    merged: dict[str, Any] = {}
    for index, part in enumerate(parsed.parts):
        compiler = _Compiler(usage)
        result = compiler.compile_part(part, apply_modifiers=False)
        sql, params = _rename_branch_params(result.sql, compiler.params, index)
        result.sql = sql
        compiled.append(result)
        merged.update(params)
    columns = compiled[0].columns
    for item in compiled:
        if len(item.columns) != len(columns):
            raise CypherError(
                "UNION requires every branch to return the same number of columns",
                kind="semantic",
            )
    sql = f"SELECT * FROM ({compiled[0].sql})"
    for index, item in enumerate(compiled[1:]):
        operator = "UNION ALL" if parsed.union_all[index] else "UNION"
        sql += f" {operator} SELECT * FROM ({item.sql})"
    sql += _union_order_sql(parsed.parts[-1].clauses[-1], columns)
    last_clause = parsed.parts[-1].clauses[-1]
    assert isinstance(last_clause, ReturnClause)
    return CompiledQuery(
        sql=sql,
        params=merged,
        columns=columns,
        skip=last_clause.skip,
        limit=last_clause.limit,
        order_items=last_clause.order_by,
    )


def _rename_branch_params(
    sql: str, params: dict[str, Any], branch: int
) -> tuple[str, dict[str, Any]]:
    """Prefix one UNION branch's named parameters so branches cannot collide."""
    renamed = re.sub(r":p(\d+)", lambda match: f":b{branch}_{match.group(1)}", sql)
    return renamed, {f"b{branch}_{name[1:]}": value for name, value in params.items()}


def _union_order_sql(clause: Any, columns: list[str]) -> str:
    """Compile the union-level ORDER BY/SKIP/LIMIT from the last RETURN."""
    if not isinstance(clause, ReturnClause):
        return ""
    if not clause.order_by:
        return " ORDER BY " + ", ".join(str(index) for index in range(1, len(columns) + 1))
    parts: list[str] = []
    for item in clause.order_by:
        name = _Compiler._order_name(item.expr)
        if name is None or name not in columns:
            raise CypherError(
                "unsupported: ORDER BY in a UNION must use a returned column name",
                kind="unsupported",
            )
        direction = " DESC" if item.descending else " ASC"
        parts.append(f"{columns.index(name) + 1}{direction}")
    return " ORDER BY " + ", ".join(parts)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


_REGEX_CACHE: dict[str, re.Pattern[str]] = {}


def _regexp(pattern: Any, value: Any) -> int:
    """SQLite ``REGEXP(pattern, value)`` with a bounded pattern cache."""
    if value is None or pattern is None:
        return 0
    text = str(pattern)
    if len(text) > MAX_REGEX_CHARS:
        raise ValueError(f"regex pattern exceeds {MAX_REGEX_CHARS} characters")
    compiled = _REGEX_CACHE.get(text)
    if compiled is None:
        compiled = re.compile(text)
        if len(_REGEX_CACHE) >= 64:
            _REGEX_CACHE.pop(next(iter(_REGEX_CACHE)))
        _REGEX_CACHE[text] = compiled
    return 1 if compiled.fullmatch(str(value)) is not None else 0


def _basename(path: Any) -> str:
    """Return the final path component."""
    return Path(str(path)).name


def _dirname(path: Any) -> str:
    """Return the parent directory in POSIX form."""
    return Path(str(path)).parent.as_posix()


def _register_functions(conn: sqlite3.Connection) -> None:
    """Register the deterministic SQLite helpers used by the compiler."""
    conn.create_function("REGEXP", 2, _regexp, deterministic=True)
    conn.create_function("cypher_basename", 1, _basename, deterministic=True)
    conn.create_function("cypher_dirname", 1, _dirname, deterministic=True)


def query_digest(query: str) -> str:
    """Return the stable digest used to key a paging cursor."""
    return hashlib.sha256(" ".join(query.split()).encode("utf-8")).hexdigest()[:16]


def _encode_cursor(generation: str | None, digest: str, offset: int) -> str:
    """Encode a generation-keyed cursor."""
    raw = json.dumps(
        {"g": generation or "", "d": digest, "o": offset}, separators=(",", ":")
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, generation: str | None, digest: str) -> int:
    """Decode and validate a cursor, returning its offset."""
    try:
        padding = "=" * (-len(cursor) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(cursor + padding).decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError
        if decoded.get("d") != digest or decoded.get("g") != (generation or ""):
            raise CypherError(
                "cursor is stale: the index generation or query text changed; "
                "restart from the first page",
                kind="stale_cursor",
            )
        offset = decoded.get("o")
        if not isinstance(offset, int) or offset < 0:
            raise ValueError
        return offset
    except CypherError:
        raise
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CypherError("invalid cursor", kind="stale_cursor") from exc


def _decode_cell(value: Any) -> Any:
    """Decode JSON objects/arrays emitted for whole node/edge values."""
    if isinstance(value, str) and len(value) < 20_000:
        stripped = value.strip()
        if (stripped.startswith("{") and stripped.endswith("}")) or (
            stripped.startswith("[") and stripped.endswith("]")
        ):
            try:
                return json.loads(stripped)
            except (TypeError, ValueError):
                return value
    return value


def _metadata(conn: sqlite3.Connection, key: str) -> str | None:
    """Return one ``index_metadata`` value, or ``None``."""
    row = conn.execute("SELECT value FROM index_metadata WHERE key = ?;", (key,)).fetchone()
    return str(row["value"]) if row is not None and row["value"] is not None else None


def execute_cypher(
    db: GraphDatabase,
    query: str,
    *,
    limit: int = DEFAULT_ROWS,
    offset: int = 0,
    cursor: str = "",
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> dict[str, Any]:
    """Execute a read-only Cypher query with bounded output and a deadline.

    Args:
        db: The graph database to query.
        query: Cypher query text.
        limit: Maximum rows returned in one response (clipped to 500).
        offset: Zero-based row offset. Ignored when *cursor* is set.
        cursor: A cursor from the previous page. It is valid only for the same
            index generation and query text.
        timeout_ms: Wall-clock deadline in milliseconds (clipped to 1..30000).

    Returns:
        A JSON-serialisable payload with columns, rows, paging, generation,
        digest, timing, and a trust note. Errors are returned as
        ``outcome: invalid_argument`` (``error_kind``/``error``) or
        ``outcome: timeout`` rather than raised.
    """
    started = time.perf_counter()
    limit = max(1, min(int(limit), MAX_ROWS))
    timeout_ms = max(1, min(int(timeout_ms), MAX_TIMEOUT_MS))
    digest = query_digest(query)

    with db.connect() as conn:
        generation = _metadata(conn, "index_generation")
        indexed_at = _metadata(conn, "indexed_at") or _metadata(conn, "last_indexed_at")

    start_cursor = bool(cursor)
    if cursor:
        try:
            start_offset = _decode_cursor(cursor, generation, digest)
        except CypherError as exc:
            payload = exc.as_dict()
            payload.update(
                {
                    "query": query,
                    "query_digest": digest,
                    "index_generation": generation,
                    "query_time_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            )
            return payload
    else:
        start_offset = max(0, int(offset))

    try:
        compiled = compile_cypher(query)
    except CypherError as exc:
        payload = exc.as_dict()
        payload.update(
            {
                "query": query,
                "query_digest": digest,
                "index_generation": generation,
                "query_time_ms": round((time.perf_counter() - started) * 1000, 1),
                "note": _NOTE,
            }
        )
        return payload

    effective = limit
    user_bounded = False
    consumed = 0
    if start_cursor:
        consumed = max(0, start_offset - compiled.skip)
    if compiled.limit is not None:
        remaining = max(0, compiled.limit - consumed)
        effective = min(remaining, limit)
        user_bounded = remaining <= limit
    total_offset = start_offset if start_cursor else start_offset + compiled.skip
    deadline = time.monotonic() + (timeout_ms / 1000.0)

    with db.connect() as conn:
        _register_functions(conn)

        def _progress() -> int:
            """Abort the statement when the deadline has passed."""
            return 1 if time.monotonic() > deadline else 0

        conn.set_progress_handler(_progress, 5_000)
        try:
            rows = conn.execute(
                compiled.sql + " LIMIT :cypher_limit OFFSET :cypher_offset",
                {**compiled.params, "cypher_limit": effective + 1, "cypher_offset": total_offset},
            ).fetchall()
        except sqlite3.OperationalError as exc:
            message = str(exc)
            if "interrupted" in message.lower():
                return _timeout_payload(query, digest, generation, started, timeout_ms)
            if "user-defined function raised exception" in message:
                return _error_payload(
                    query,
                    digest,
                    generation,
                    started,
                    "a regular expression in the query could not be evaluated",
                    kind="execution",
                )
            return _error_payload(
                query, digest, generation, started, f"query execution failed: {message}"
            )
        except sqlite3.Error as exc:
            return _error_payload(
                query, digest, generation, started, f"query execution failed: {exc}"
            )
        finally:
            conn.set_progress_handler(None, 0)

    more_rows = len(rows) > effective
    page = rows[:effective]
    truncated = more_rows and not user_bounded
    capped_by = "user" if user_bounded else "server"

    result_rows: list[dict[str, Any]] = []
    byte_count = 0
    for row in page:
        record = {
            column: _decode_cell(row[f"c{index}"]) for index, column in enumerate(compiled.columns)
        }
        encoded = json.dumps(record, default=str)
        if byte_count + len(encoded) > MAX_BYTES and result_rows:
            truncated = True
            capped_by = "bytes"
            break
        byte_count += len(encoded)
        result_rows.append(record)

    next_cursor = None
    if truncated:
        next_cursor = _encode_cursor(generation, digest, total_offset + len(result_rows))

    outcome = "resolved" if result_rows else "no_match"
    return {
        "outcome": outcome,
        "query": query,
        "columns": compiled.columns,
        "rows": result_rows,
        "row_count": len(result_rows),
        "offset": total_offset,
        "limit": limit,
        "truncated": truncated,
        "capped_by": capped_by,
        "next_cursor": next_cursor,
        "index_generation": generation,
        "indexed_at": indexed_at,
        "query_digest": digest,
        "query_time_ms": round((time.perf_counter() - started) * 1000, 1),
        "timeout_ms": timeout_ms,
        "note": _NOTE,
    }


_NOTE = (
    "read-only Cypher subset over the current index generation; "
    "absence is not proof of completeness, so check coverage before trusting a "
    "negative answer. Unresolved references appear as :Unresolved nodes."
)


def _error_payload(
    query: str,
    digest: str,
    generation: str | None,
    started: float,
    message: str,
    *,
    kind: str = "execution",
) -> dict[str, Any]:
    """Return an execution-error payload."""
    return {
        "outcome": "invalid_argument",
        "error_kind": kind,
        "error": message,
        "query": query,
        "query_digest": digest,
        "index_generation": generation,
        "query_time_ms": round((time.perf_counter() - started) * 1000, 1),
        "note": _NOTE,
    }


def _timeout_payload(
    query: str, digest: str, generation: str | None, started: float, timeout_ms: int
) -> dict[str, Any]:
    """Return a timeout payload."""
    return {
        "outcome": "timeout",
        "error_kind": "timeout",
        "error": f"query exceeded the {timeout_ms} ms deadline",
        "query": query,
        "query_digest": digest,
        "index_generation": generation,
        "query_time_ms": round((time.perf_counter() - started) * 1000, 1),
        "timeout_ms": timeout_ms,
        "note": _NOTE,
    }


def render_cypher_text(payload: dict[str, Any]) -> str:
    """Render a Cypher payload as a compact text table."""
    if payload.get("outcome") in ("invalid_argument", "timeout"):
        return f"Cypher {payload.get('outcome')}: {payload.get('error')}"
    columns = payload.get("columns") or []
    rows = payload.get("rows") or []
    if not rows:
        return "No matching rows (absence is not proof of completeness; run 'code-search coverage')"
    lines = [
        f"{payload.get('row_count', 0)} rows (offset {payload.get('offset', 0)})",
        "  " + " | ".join(str(column) for column in columns),
    ]
    for row in rows:
        cells = []
        for column in columns:
            value = row.get(column)
            if isinstance(value, (dict, list)):
                cells.append(json.dumps(value, default=str, sort_keys=True))
            elif value is None:
                cells.append("null")
            else:
                cells.append(str(value))
        lines.append("  " + " | ".join(cells))
    if payload.get("truncated"):
        lines.append("  (truncated; pass next_cursor as the cursor for the next page)")
    return "\n".join(lines)
