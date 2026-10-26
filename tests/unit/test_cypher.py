"""Read-only Cypher subset: lexer, parser, compiler, execution, and safety."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from code_search.engine import cypher
from code_search.engine.cypher import (
    DEAD_CODE_CYPHER,
    CypherError,
    compile_cypher,
    execute_cypher,
    query_digest,
    render_cypher_text,
    tokenize,
)
from code_search.engine.graph import GraphDatabase
from code_search.engine.graph_surface import find_dead_code


def _symbol(
    conn: sqlite3.Connection,
    *,
    fqn: str,
    name: str,
    kind: str,
    file_path: str,
    line: int,
    parent: int | None = None,
    is_test: int = 0,
    is_entry_point: int = 0,
    importance: float = 0.0,
    visibility: str = "public",
) -> int:
    """Insert one symbol and return its id."""
    cursor = conn.execute(
        "INSERT INTO symbols("
        "fqn, name, kind, file_path, line_start, line_end, column_start, column_end, "
        "language, parent_symbol_id, is_test, is_entry_point, importance, visibility, "
        "canonical_fqn, conventional_fqn"
        ") VALUES (?, ?, ?, ?, ?, ?, 0, 0, 'python', ?, ?, ?, ?, ?, ?, ?);",
        (
            fqn,
            name,
            kind,
            file_path,
            line,
            line + 2,
            parent,
            is_test,
            is_entry_point,
            importance,
            visibility,
            fqn.removeprefix("/repo/"),
            fqn.split("::")[-1],
        ),
    )
    return int(cursor.lastrowid)


def _edge(
    conn: sqlite3.Connection,
    source: int,
    target: int | None,
    edge_type: str,
    *,
    resolved: int = 1,
    tier: str = "exact",
    target_raw: str | None = None,
    properties: str = "{}",
) -> None:
    """Insert one graph edge."""
    conn.execute(
        "INSERT INTO graph_edges("
        "source_symbol_id, target_symbol_id, edge_type, resolved, resolution_tier, "
        "target_raw, properties"
        ") VALUES (?, ?, ?, ?, ?, ?, ?);",
        (source, target, edge_type, resolved, tier, target_raw, properties),
    )


@pytest.fixture
def cypher_db(tmp_path: Path) -> GraphDatabase:
    """A small deterministic graph covering every supported construct."""
    db = GraphDatabase(tmp_path / "graph.db")
    db.initialize()
    with db.write_transaction() as conn:
        alpha = _symbol(
            conn,
            fqn="/repo/a.py::alpha",
            name="alpha",
            kind="function",
            file_path="/repo/a.py",
            line=1,
            importance=10.0,
        )
        beta = _symbol(
            conn,
            fqn="/repo/a.py::beta",
            name="beta",
            kind="function",
            file_path="/repo/a.py",
            line=5,
        )
        dead = _symbol(
            conn,
            fqn="/repo/a.py::dead",
            name="dead",
            kind="function",
            file_path="/repo/a.py",
            line=9,
            visibility="private",
        )
        alpha_class = _symbol(
            conn,
            fqn="/repo/a.py::Alpha",
            name="Alpha",
            kind="class",
            file_path="/repo/a.py",
            line=13,
            is_entry_point=1,
        )
        run = _symbol(
            conn,
            fqn="/repo/a.py::Alpha::run",
            name="run",
            kind="method",
            file_path="/repo/a.py",
            line=14,
            parent=alpha_class,
        )
        api = _symbol(
            conn,
            fqn="/repo/api.py::Api",
            name="Api",
            kind="interface",
            file_path="/repo/api.py",
            line=1,
        )
        api_run = _symbol(
            conn,
            fqn="/repo/api.py::Api::run",
            name="run",
            kind="method",
            file_path="/repo/api.py",
            line=2,
            parent=api,
        )
        impl = _symbol(
            conn,
            fqn="/repo/impl.py::Impl",
            name="Impl",
            kind="class",
            file_path="/repo/impl.py",
            line=1,
        )
        base = _symbol(
            conn,
            fqn="/repo/inherit.py::Base",
            name="Base",
            kind="class",
            file_path="/repo/inherit.py",
            line=1,
        )
        child = _symbol(
            conn,
            fqn="/repo/inherit.py::Child",
            name="Child",
            kind="class",
            file_path="/repo/inherit.py",
            line=5,
        )
        test_alpha = _symbol(
            conn,
            fqn="/repo/test_a.py::test_alpha",
            name="test_alpha",
            kind="function",
            file_path="/repo/test_a.py",
            line=1,
            is_test=1,
            is_entry_point=1,
        )
        _symbol(
            conn,
            fqn="/repo/b.py::gamma",
            name="gamma",
            kind="function",
            file_path="/repo/b.py",
            line=1,
        )
        _edge(conn, alpha, beta, "CALLS", properties='{"line": 2, "arg_count": 0}')
        _edge(conn, run, beta, "CALLS", properties='{"line": 15}')
        _edge(conn, impl, api, "IMPLEMENTS")
        _edge(conn, child, base, "INHERITS")
        _edge(conn, test_alpha, alpha, "CALLS", properties='{"line": 2}')
        _edge(
            conn,
            dead,
            None,
            "CALLS",
            resolved=0,
            tier="ambiguous",
            target_raw="loader.orphan",
            properties='{"candidate_count": 2}',
        )
        conn.execute(
            "INSERT INTO module_edges(source_path, target_path, relation) "
            "VALUES ('/repo/a.py', '/repo/b.py', 'IMPORTS');"
        )
        conn.execute("INSERT INTO index_metadata(key, value) VALUES ('index_generation', 'gen-1');")
        conn.execute("INSERT INTO index_metadata(key, value) VALUES ('index_format_version', '1');")
    assert run and api_run and beta and dead
    return db


def _run(db: GraphDatabase, query: str, **kwargs: Any) -> dict[str, Any]:
    """Execute *query* and return the payload."""
    return execute_cypher(db, query, **kwargs)


def test_tokenize_comments_strings_and_backticks() -> None:
    """The lexer strips comments and decodes string escapes."""
    tokens = tokenize(
        "MATCH // comment\n (n:`Weird Name`) WHERE n.x = 'a\\n' /* block */ RETURN n.x"
    )
    values = [token.value for token in tokens]
    assert "Weird Name" in values
    assert "a\n" in values
    assert "comment" not in values
    assert values[-1] == ""


def test_compile_is_parameterized() -> None:
    """Literals become named parameters; caller text never reaches the SQL."""
    compiled = compile_cypher(
        "MATCH (f:Function) WHERE f.name = 'alpha' AND f.line_start > 1 RETURN f.name"
    )
    assert "'alpha'" not in compiled.sql
    assert ":p" in compiled.sql
    assert "alpha" in compiled.params.values()


def test_golden_sql_narrows_base_ctes() -> None:
    """The base CTEs are built only from the query's vocabulary."""
    node_only = compile_cypher("MATCH (f:Function) RETURN f.name")
    assert "edges(" not in node_only.sql
    assert "cypher_basename" not in node_only.sql
    assert "s.kind IN (:p" in node_only.sql

    one_hop = compile_cypher("MATCH (a:Function)-[:CALLS]->(b:Function) RETURN a.name")
    assert "edges(id, source, target" in one_hop.sql
    assert "'CONTAINS'" not in one_hop.sql
    assert "module_edges" not in one_hop.sql

    files = compile_cypher("MATCH (f:File)-[:IMPORTS]->(g:File) RETURN f.name")
    assert "cypher_basename" in files.sql
    assert "module_edges" in files.sql


def test_read_only_statements_are_rejected() -> None:
    """Write clauses never parse as read-only queries."""
    for query in ("CREATE (n:Function) RETURN n", "MATCH (n) SET n.name = 'x' RETURN n"):
        with pytest.raises(CypherError, match="unsupported read-only"):
            compile_cypher(query)


def test_unsupported_syntax_errors() -> None:
    """Unsupported constructs report a specific error instead of empty rows."""
    with pytest.raises(CypherError, match="unsupported label"):
        compile_cypher("MATCH (n:Widget) RETURN n.name")
    with pytest.raises(CypherError, match="unsupported relationship type"):
        compile_cypher("MATCH (a)-[:OWNS]->(b) RETURN a")
    with pytest.raises(CypherError, match="unsupported function"):
        compile_cypher("MATCH (n) RETURN mystery(n)")
    with pytest.raises(CypherError, match="variable-length upper bound"):
        compile_cypher("MATCH (a)-[:CALLS*1..9]->(b) RETURN a")
    with pytest.raises(CypherError, match="aggregate functions are not allowed"):
        compile_cypher("MATCH (n) WHERE count(n) > 1 RETURN n")
    with pytest.raises(CypherError, match="clauses after RETURN"):
        compile_cypher("MATCH (n) RETURN n MATCH (m) RETURN m")
    with pytest.raises(CypherError, match="must end with RETURN"):
        compile_cypher("MATCH (n)")


def test_syntax_errors_have_positions() -> None:
    """A malformed query reports where it broke."""
    with pytest.raises(CypherError) as info:
        compile_cypher("MATCH (n RETURN n")
    assert info.value.position is not None


def test_basic_match_and_where(cypher_db: GraphDatabase) -> None:
    """Labels, property filters, string predicates, and regex work."""
    payload = _run(
        cypher_db,
        "MATCH (f:Function) WHERE f.name STARTS WITH 'a' AND f.name =~ 'a.*' "
        "RETURN f.name AS name ORDER BY name",
    )
    assert payload["outcome"] == "resolved"
    assert payload["rows"] == [{"name": "alpha"}]

    payload = _run(
        cypher_db,
        "MATCH (f:Function) WHERE f.name ENDS WITH 'a' AND f.name CONTAINS 'et' "
        "RETURN f.name AS name ORDER BY name",
    )
    assert payload["rows"] == [{"name": "beta"}]


def test_inheritance_and_implementation_edges(cypher_db: GraphDatabase) -> None:
    """INHERITS and IMPLEMENTS are distinct relationship types."""
    inherited = _run(
        cypher_db,
        "MATCH (c:Class)-[:INHERITS]->(b:Class) RETURN c.name AS child, b.name AS base",
    )
    assert inherited["rows"] == [{"child": "Child", "base": "Base"}]

    implemented = _run(
        cypher_db,
        "MATCH (c:Class)-[:IMPLEMENTS]->(i:Interface) RETURN c.name AS type, i.name AS interface",
    )
    assert implemented["rows"] == [{"type": "Impl", "interface": "Api"}]


def test_direction_inbound_and_outbound(cypher_db: GraphDatabase) -> None:
    """Relationship direction is preserved and traversable both ways."""
    outbound = _run(
        cypher_db,
        "MATCH (a:Function)-[:CALLS]->(b:Function) RETURN a.name AS src, b.name AS tgt "
        "ORDER BY src, tgt",
    )
    assert outbound["rows"] == [
        {"src": "alpha", "tgt": "beta"},
        {"src": "test_alpha", "tgt": "alpha"},
    ]
    inbound = _run(
        cypher_db,
        "MATCH (a:Function)<-[:CALLS]-(b:Function) RETURN a.name AS src, b.name AS tgt "
        "ORDER BY src, tgt",
    )
    assert inbound["rows"] == [
        {"src": "alpha", "tgt": "test_alpha"},
        {"src": "beta", "tgt": "alpha"},
    ]


def test_undirected_and_edge_variables(cypher_db: GraphDatabase) -> None:
    """Undirected relationships and relationship variables are available."""
    payload = _run(
        cypher_db,
        "MATCH (a:Function)-[r:CALLS]-(b:Function) "
        "RETURN a.name AS a, b.name AS b, type(r) AS kind, r.line AS line "
        "ORDER BY a, b",
    )
    assert payload["outcome"] == "resolved"
    assert {row["kind"] for row in payload["rows"]} == {"CALLS"}
    alpha_beta = next(row for row in payload["rows"] if row["a"] == "alpha" and row["b"] == "beta")
    assert alpha_beta["line"] == 2


def test_aggregates_grouping_and_collect(cypher_db: GraphDatabase) -> None:
    """count/sum/avg/min/max/collect and grouping compile to SQL aggregates."""
    payload = _run(
        cypher_db,
        "MATCH (f:Function) RETURN labels(f) AS label, count(*) AS n, "
        "min(f.name) AS first, max(f.name) AS last, collect(f.name) AS names "
        "ORDER BY first",
    )
    assert payload["rows"] == [
        {
            "label": "Function",
            "n": 5,
            "first": "alpha",
            "last": "test_alpha",
            "names": ["alpha", "beta", "dead", "test_alpha", "gamma"],
        }
    ]
    distinct = _run(cypher_db, "MATCH (f:Function) RETURN count(DISTINCT f.kind) AS kinds")
    assert distinct["rows"] == [{"kinds": 1}]


def test_with_where_and_rebinding(cypher_db: GraphDatabase) -> None:
    """WITH scopes variables and supports post-projection filters."""
    payload = _run(
        cypher_db,
        "MATCH (f:Function) WITH f, f.name AS name WHERE name CONTAINS 'e' "
        "RETURN f.name AS name ORDER BY name",
    )
    assert payload["rows"] == [
        {"name": "beta"},
        {"name": "dead"},
        {"name": "test_alpha"},
    ]


def test_unwind_union_case_and_distinct(cypher_db: GraphDatabase) -> None:
    """UNWIND, UNION, CASE, and DISTINCT are supported."""
    payload = _run(cypher_db, "UNWIND [1, 2, 3] AS x RETURN x, x * x AS square ORDER BY x")
    assert payload["rows"] == [
        {"x": 1, "square": 1},
        {"x": 2, "square": 4},
        {"x": 3, "square": 9},
    ]

    union = _run(
        cypher_db,
        "MATCH (f:Function) RETURN f.name AS name UNION "
        "MATCH (c:Class) RETURN c.name AS name ORDER BY name",
    )
    assert union["columns"] == ["name"]
    assert [row["name"] for row in union["rows"]] == [
        "Alpha",
        "Base",
        "Child",
        "Impl",
        "alpha",
        "beta",
        "dead",
        "gamma",
        "test_alpha",
    ]

    case = _run(
        cypher_db,
        "MATCH (f:Function) RETURN "
        "CASE WHEN f.name = 'alpha' THEN 'A' ELSE 'B' END AS tag, count(*) AS n "
        "ORDER BY tag",
    )
    assert case["rows"] == [{"tag": "A", "n": 1}, {"tag": "B", "n": 4}]

    distinct = _run(cypher_db, "MATCH (f:Function) RETURN DISTINCT labels(f) AS label")
    assert distinct["rows"] == [{"label": "Function"}]


def test_optional_match_returns_null(cypher_db: GraphDatabase) -> None:
    """OPTIONAL MATCH keeps unmatched anchors."""
    payload = _run(
        cypher_db,
        "MATCH (f:Function) OPTIONAL MATCH (f)-[:IMPLEMENTS]->(i:Interface) "
        "RETURN f.name AS name, i.name AS interface ORDER BY name",
    )
    assert payload["rows"] == [
        {"name": "alpha", "interface": None},
        {"name": "beta", "interface": None},
        {"name": "dead", "interface": None},
        {"name": "gamma", "interface": None},
        {"name": "test_alpha", "interface": None},
    ]


def test_unwind_after_collect_and_exists_projection(cypher_db: GraphDatabase) -> None:
    """UNWIND consumes collected lists and EXISTS is usable as a projection."""
    payload = _run(
        cypher_db,
        "MATCH (f:Function) WITH collect(f.name) AS names "
        "UNWIND names AS name RETURN name ORDER BY name",
    )
    assert [row["name"] for row in payload["rows"]] == [
        "alpha",
        "beta",
        "dead",
        "gamma",
        "test_alpha",
    ]

    projected = _run(
        cypher_db,
        "MATCH (f:Function) RETURN f.name AS name, "
        "EXISTS { (f)-[:CALLS]->() } AS calls ORDER BY name",
    )
    assert projected["rows"] == [
        {"name": "alpha", "calls": 1},
        {"name": "beta", "calls": 0},
        {"name": "dead", "calls": 0},
        {"name": "gamma", "calls": 0},
        {"name": "test_alpha", "calls": 1},
    ]


def test_variable_length_paths(cypher_db: GraphDatabase) -> None:
    """[*n..m] walks a bounded number of hops."""
    payload = _run(
        cypher_db,
        "MATCH (a:Function)-[:CALLS*2..2]->(b:Function) "
        "RETURN a.name AS src, b.name AS tgt ORDER BY src, tgt",
    )
    assert payload["rows"] == [{"src": "test_alpha", "tgt": "beta"}]
    unbounded = _run(
        cypher_db,
        "MATCH (a:Function)-[:CALLS*]->(b:Function) "
        "RETURN a.name AS src, b.name AS tgt ORDER BY src, tgt",
    )
    assert {"src": "test_alpha", "tgt": "beta"} in unbounded["rows"]


def test_exists_including_inner_where(cypher_db: GraphDatabase) -> None:
    """EXISTS is correlated and supports an inner WHERE."""
    payload = _run(
        cypher_db,
        "MATCH (f:Function) WHERE NOT EXISTS { (f)<-[:CALLS]-(src) WHERE src.is_test = 0 } "
        "RETURN f.name AS name ORDER BY name",
    )
    assert payload["rows"] == [
        {"name": "alpha"},
        {"name": "dead"},
        {"name": "gamma"},
        {"name": "test_alpha"},
    ]

    bound_only = _run(
        cypher_db,
        "MATCH (f:Function) WHERE EXISTS { (f) } RETURN count(*) AS n",
    )
    assert bound_only["rows"] == [{"n": 5}]
    contradicted = _run(
        cypher_db,
        "MATCH (f:Function) WHERE EXISTS { (f:Interface) } RETURN count(*) AS n",
    )
    assert contradicted["rows"] == [{"n": 0}]


def test_synthetic_labels_and_edges(cypher_db: GraphDatabase) -> None:
    """File/Module/Unresolved nodes and CONTAINS/IMPORTS edges are exposed."""
    file_imports = _run(
        cypher_db,
        "MATCH (source:File)-[:IMPORTS]->(target:File) "
        "RETURN source.name AS source, target.name AS target",
    )
    assert file_imports["rows"] == [{"source": "a.py", "target": "b.py"}]

    contains = _run(
        cypher_db,
        "MATCH (t:Class)-[:CONTAINS]->(m:Method) RETURN m.name AS method ORDER BY method",
    )
    assert contains["rows"] == [{"method": "run"}]

    unresolved = _run(cypher_db, "MATCH (u:Unresolved) RETURN u.name AS raw")
    assert unresolved["rows"] == [{"raw": "loader.orphan"}]

    unresolved_edge = _run(
        cypher_db,
        "MATCH (src:Function)-[r:CALLS]->(u:Unresolved) "
        "RETURN src.name AS source, u.name AS target, r.resolved AS resolved",
    )
    assert unresolved_edge["rows"] == [{"source": "dead", "target": "loader.orphan", "resolved": 0}]

    modules = _run(cypher_db, "MATCH (m:Module) RETURN count(*) AS n")
    assert modules["rows"][0]["n"] >= 1


def test_scalar_functions(cypher_db: GraphDatabase) -> None:
    """The documented scalar function set compiles and runs."""
    payload = _run(
        cypher_db,
        "MATCH (f:Function) WHERE f.name = 'alpha' RETURN "
        "coalesce(f.visibility, 'none') AS visibility, "
        "toLower(f.name) AS lower, toUpper(f.name) AS upper, "
        "toString(f.line_start) AS line, size(f.name) AS size, "
        "substring(f.name, 0, 3) AS prefix, replace(f.name, 'a', 'A') AS replaced, "
        "trim('  x  ') AS trimmed, id(f) AS identifier",
    )
    assert payload["rows"] == [
        {
            "visibility": "public",
            "lower": "alpha",
            "upper": "ALPHA",
            "line": "1",
            "size": 5,
            "prefix": "alp",
            "replaced": "AlphA",
            "trimmed": "x",
            "identifier": 1,
        }
    ]


def test_skip_limit_and_cursor_paging(cypher_db: GraphDatabase) -> None:
    """Paging is deterministic and cursors are generation-bound."""
    first = _run(
        cypher_db,
        "MATCH (f:Function) RETURN f.name AS name ORDER BY name",
        limit=2,
    )
    assert [row["name"] for row in first["rows"]] == ["alpha", "beta"]
    assert first["truncated"] is True
    assert first["next_cursor"]

    second = _run(
        cypher_db,
        "MATCH (f:Function) RETURN f.name AS name ORDER BY name",
        limit=2,
        cursor=first["next_cursor"],
    )
    assert [row["name"] for row in second["rows"]] == ["dead", "gamma"]

    stale = _run(
        cypher_db,
        "MATCH (c:Class) RETURN c.name AS name ORDER BY name",
        cursor=first["next_cursor"],
    )
    assert stale["outcome"] == "invalid_argument"
    assert stale["error_kind"] == "stale_cursor"

    skipped = _run(
        cypher_db,
        "MATCH (f:Function) RETURN f.name AS name ORDER BY name SKIP 1 LIMIT 1",
    )
    assert skipped["rows"] == [{"name": "beta"}]


def test_skip_and_cursor_do_not_double_skip(cypher_db: GraphDatabase) -> None:
    """A cursor carries an absolute offset; SKIP is applied exactly once."""
    first = _run(
        cypher_db,
        "MATCH (f:Function) RETURN f.name AS name ORDER BY name SKIP 1",
        limit=2,
    )
    assert [row["name"] for row in first["rows"]] == ["beta", "dead"]
    second = _run(
        cypher_db,
        "MATCH (f:Function) RETURN f.name AS name ORDER BY name SKIP 1",
        limit=2,
        cursor=first["next_cursor"],
    )
    assert [row["name"] for row in second["rows"]] == ["gamma", "test_alpha"]
    assert second["next_cursor"] is None


def test_user_limit_survives_byte_capped_paging(
    cypher_db: GraphDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A query LIMIT bounds the total across byte-capped pages, not each page."""
    monkeypatch.setattr(cypher, "MAX_BYTES", 40)
    query = "MATCH (f:Function) RETURN f.name AS name ORDER BY name LIMIT 3"
    first = _run(cypher_db, query)
    assert first["truncated"] is True
    names = [row["name"] for row in first["rows"]]
    cursor = first["next_cursor"]
    assert cursor
    while cursor:
        page = _run(cypher_db, query, cursor=cursor)
        names.extend(row["name"] for row in page["rows"])
        cursor = page["next_cursor"]
    assert names == ["alpha", "beta", "dead"]


def test_query_limit_is_a_user_bound(cypher_db: GraphDatabase) -> None:
    """A query's own LIMIT does not report server truncation."""
    payload = _run(
        cypher_db,
        "MATCH (f:Function) RETURN f.name AS name ORDER BY name LIMIT 1",
        limit=5,
    )
    assert payload["rows"] == [{"name": "alpha"}]
    assert payload["truncated"] is False
    assert payload["capped_by"] == "user"


def test_byte_cap_truncates(cypher_db: GraphDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    """The byte cap trims a page and yields the next cursor."""
    monkeypatch.setattr(cypher, "MAX_BYTES", 40)
    payload = _run(cypher_db, "MATCH (f:Function) RETURN f.name AS name ORDER BY name")
    assert payload["truncated"] is True
    assert payload["capped_by"] == "bytes"
    assert payload["next_cursor"]
    assert 0 < payload["row_count"] < 5


def test_timeout_returns_a_structured_payload(tmp_path: Path) -> None:
    """A deadline aborts an expensive query without leaking SQL."""
    db = GraphDatabase(tmp_path / "big.db")
    db.initialize()
    with db.write_transaction() as conn:
        conn.executemany(
            "INSERT INTO symbols(fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) "
            "VALUES (?, ?, 'function', '/repo/x.py', ?, ?, 0, 0, 'python');",
            [(f"/repo/x.py::f{i}", f"f{i}", i, i + 1) for i in range(400)],
        )
        conn.execute("INSERT INTO index_metadata(key, value) VALUES ('index_generation', 'g');")
    payload = _run(db, "MATCH (a), (b), (c), (d), (e) RETURN count(*) AS n", timeout_ms=5)
    assert payload["outcome"] == "timeout"
    assert payload["error_kind"] == "timeout"
    assert "sqlite" not in payload["error"].lower()


def test_injection_literal_does_not_execute(cypher_db: GraphDatabase) -> None:
    """A SQL-looking string stays a string literal."""
    payload = _run(
        cypher_db,
        "MATCH (f:Function) WHERE f.name = 'x\\'; DROP TABLE symbols; --' RETURN f.name AS name",
    )
    assert payload["outcome"] == "no_match"
    with cypher_db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM symbols;").fetchone()[0] > 0


def test_random_fragments_never_crash_or_write(cypher_db: GraphDatabase) -> None:
    """Fuzz-ish fragments return structured errors and never mutate the graph."""
    import random

    rng = random.Random(20261026)
    alphabet = list("MATCHRETURNWHEREFunctionCALLS()[]{}:.,*-><|'\"0123456789_ ")
    with cypher_db.connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM symbols;").fetchone()[0]
    for _ in range(100):
        fragment = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 80)))
        payload = _run(cypher_db, fragment)
        assert payload["outcome"] in {"invalid_argument", "no_match", "resolved"}
        assert "sqlite" not in str(payload.get("error", "")).lower()
    with cypher_db.connect() as conn:
        after = conn.execute("SELECT COUNT(*) FROM symbols;").fetchone()[0]
    assert after == before


def test_json_values_and_text_rendering(cypher_db: GraphDatabase) -> None:
    """Whole node values are JSON objects and the text renderer is compact."""
    payload = _run(
        cypher_db,
        "MATCH (f:Function) WHERE f.name = 'alpha' RETURN f AS node LIMIT 1",
    )
    node = payload["rows"][0]["node"]
    assert isinstance(node, dict)
    assert node["name"] == "alpha"
    assert node["label"] == "Function"
    text = render_cypher_text(payload)
    assert "rows" in text
    assert "node" in text


def test_dead_code_cypher_agrees_with_the_dedicated_surface(cypher_db: GraphDatabase) -> None:
    """The documented EXISTS query selects the same candidates as the tool."""
    payload = _run(cypher_db, DEAD_CODE_CYPHER)
    cypher_fqns = {row["fqn"] for row in payload["rows"]}
    tool = find_dead_code(cypher_db, index_root=Path("/repo"))
    tool_fqns = {candidate["fqn"] for candidate in tool["candidates"]}
    assert cypher_fqns == tool_fqns
    assert DEAD_CODE_CYPHER in str(tool["canonical_query"])


def test_query_digest_is_whitespace_stable() -> None:
    """The cursor key ignores insignificant whitespace."""
    assert query_digest("MATCH (n)  RETURN n") == query_digest("MATCH (n)\nRETURN n")


def test_publication_payload_shape(cypher_db: GraphDatabase) -> None:
    """The payload carries generation, digest, note, and column metadata."""
    payload = _run(cypher_db, "MATCH (f:Function) RETURN f.name AS name ORDER BY name LIMIT 1")
    assert payload["index_generation"] == "gen-1"
    assert payload["columns"] == ["name"]
    assert payload["query_digest"]
    assert "absence is not proof of completeness" in payload["note"]
    assert json.dumps(payload, default=str)
