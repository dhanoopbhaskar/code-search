"""Post-index graph enrichment passes.

Once symbols and edges are persisted, three derived facts are computed and
stored so an agent query does not have to guess them: entry-point
classification, importance, and degree counts. ``TESTS`` edges are derived from
the resolved production references made by test symbols, and every symbol gets
a project-relative ``canonical_fqn``.

Every pass is deterministic, runs inside one write transaction, and is safe to
re-run on a full or incremental index.
"""

from __future__ import annotations

import fnmatch
import math
import re
from pathlib import Path
from typing import Any

from code_search.engine.config import Settings

#: Edge types that contribute to stored degrees. ``TESTS`` is derived from the
#: others, so counting it would double-count the same relationship.
DEGREE_EDGE_TYPES: tuple[str, ...] = (
    "CALLS",
    "INHERITS",
    "IMPLEMENTS",
    "REFERENCES",
    "USAGE",
    "CALL_REFERENCE",
)

#: Edge types that represent a use of the target for importance purposes.
_IMPORTANCE_EDGE_TYPES: tuple[str, ...] = ("CALLS", "USAGE")

#: Annotation/decorator markers that declare a framework entry point.
_ENTRY_POINT_ANNOTATION_RE = re.compile(
    r"@(?:"
    r"app\.(?:route|get|post|put|patch|delete|websocket)|"
    r"router\.|blueprint\.|"
    r"(?:get|post|put|delete|patch|head|options|request)mapping|"
    r"path|route|handler|endpoint|"
    r"(?:rest)?controller|"
    r"pytest\.fixture|fixture|"
    r"bean|eventlistener|scheduled|commandlinerunner|applicationrunner|"
    r"(?:before|after)each|main"
    r")",
    re.IGNORECASE,
)

#: Types whose visibility makes a top-level declaration part of the public API.
_PUBLIC_VISIBILITIES: frozenset[str] = frozenset({"public"})


def rebuild_derived_graph_data(
    db: Any,
    root_path: Path,
    settings: Settings | None = None,
) -> dict[str, int]:
    """Recompute canonical FQNs, TESTS edges, entry points, importance, degrees.

    Args:
        db: The graph database to update.
        root_path: Indexed repository root, used for project-relative names.
        settings: Engine settings (configured entry-point patterns).

    Returns:
        A deterministic summary ``{symbols, tests_edges, entry_points,
        degrees_rows}``.
    """
    settings = settings or Settings.from_env()
    with db.write_transaction() as conn:
        backfill_canonical_fqns(conn, root_path)
        backfill_test_flags(conn)
        tests_edges = derive_tests_edges(conn)
        entry_points = classify_entry_points(conn, settings)
        compute_importance(conn)
        degrees_rows = rebuild_symbol_degrees(conn)
        symbol_count = int(conn.execute("SELECT COUNT(*) AS n FROM symbols;").fetchone()["n"])
    return {
        "symbols": symbol_count,
        "tests_edges": tests_edges,
        "entry_points": entry_points,
        "degrees_rows": degrees_rows,
    }


def backfill_canonical_fqns(conn: Any, root_path: Path) -> int:
    """Store ``<relative path>::<declaration>`` for every symbol.

    ``canonical_fqn`` is additive: ``fqn`` keeps its absolute-path spelling so
    every existing query keeps working, while the canonical form is stable
    across worktrees and usable for display and later snapshot comparison.
    """
    root = root_path.resolve()
    rows = conn.execute("SELECT id, fqn, file_path FROM symbols;").fetchall()
    updates: list[tuple[str, int]] = []
    for row in rows:
        file_path = str(row["file_path"] or "")
        fqn = str(row["fqn"] or "")
        try:
            relative = Path(file_path).resolve().relative_to(root).as_posix()
        except (ValueError, OSError):
            relative = Path(file_path).as_posix()
        canonical = f"{relative}{fqn[len(file_path) :]}" if fqn.startswith(file_path) else fqn
        updates.append((canonical, int(row["id"])))
    if updates:
        conn.executemany("UPDATE symbols SET canonical_fqn = ? WHERE id = ?;", updates)
    return len(updates)


def backfill_test_flags(conn: Any) -> int:
    """Refresh ``symbols.is_test`` from the shared path classifier."""
    from code_search.engine.config import _is_test_file

    rows = conn.execute("SELECT DISTINCT file_path FROM symbols;").fetchall()
    updates = [
        (1 if _is_test_file(str(row["file_path"] or "")) else 0, row["file_path"]) for row in rows
    ]
    if updates:
        conn.executemany("UPDATE symbols SET is_test = ? WHERE file_path = ?;", updates)
    return len(updates)


def derive_tests_edges(conn: Any) -> int:
    """Rebuild ``TESTS`` edges from test-symbol references to production code.

    A ``TESTS`` edge is derived, not independently extracted: every resolved
    ``CALLS``/``USAGE``/``CALL_REFERENCE``/``REFERENCES``/``IMPLEMENTS``/
    ``INHERITS`` edge whose source symbol lives in a test file and whose target
    does not becomes a direct test-to-production edge. Existing derived rows
    are replaced so an incremental run cannot leave stale test relationships.
    """
    conn.execute("DELETE FROM graph_edges WHERE edge_type = 'TESTS';")
    cursor = conn.execute(
        "INSERT OR IGNORE INTO graph_edges "
        "(source_symbol_id, target_symbol_id, edge_type, source_range, "
        "resolution_tier, resolved, properties) "
        "SELECT e.source_symbol_id, e.target_symbol_id, 'TESTS', e.source_range, "
        "'derived', 1, '{\"via\": \"test_crossing\"}' "
        "FROM graph_edges e "
        "JOIN symbols src ON src.id = e.source_symbol_id "
        "JOIN symbols tgt ON tgt.id = e.target_symbol_id "
        "WHERE e.resolved = 1 AND e.target_symbol_id IS NOT NULL "
        "AND e.edge_type IN "
        "('CALLS','USAGE','CALL_REFERENCE','REFERENCES','IMPLEMENTS','INHERITS') "
        "AND src.is_test = 1 AND tgt.is_test = 0 "
        "AND e.source_symbol_id != e.target_symbol_id;"
    )
    return max(0, int(cursor.rowcount))


def classify_entry_points(conn: Any, settings: Settings) -> int:
    """Store ``is_entry_point`` and ``entry_point_reason`` on every symbol.

    Rules are evaluated in order and the first match wins: test symbol,
    ``main``, constructor, override/implementation, exported top-level symbol,
    annotated framework handler, then a configured name/glob. Only top-level
    public declarations count as exported API, so ordinary public methods are
    not all classified as entry points.
    """
    rows = conn.execute(
        "SELECT id, fqn, name, kind, file_path, parent_symbol_id, "
        "declared_rules, visibility, is_test "
        "FROM symbols ORDER BY id;"
    ).fetchall()
    symbols: dict[int, dict[str, Any]] = {int(row["id"]): dict(row) for row in rows}

    method_names: dict[int, set[str]] = {}
    for row in rows:
        parent_id = row["parent_symbol_id"]
        if parent_id is None:
            continue
        method_names.setdefault(int(parent_id), set()).add(str(row["name"]))

    bases_by_type: dict[int, set[int]] = {}
    for edge in conn.execute(
        "SELECT source_symbol_id, target_symbol_id FROM graph_edges "
        "WHERE resolved = 1 AND target_symbol_id IS NOT NULL "
        "AND edge_type IN ('INHERITS', 'IMPLEMENTS');"
    ):
        bases_by_type.setdefault(int(edge["source_symbol_id"]), set()).add(
            int(edge["target_symbol_id"])
        )

    configured = tuple(pattern.strip() for pattern in settings.entry_points if pattern.strip())
    updates: list[tuple[int, str | None, int]] = []
    for symbol_id, symbol in symbols.items():
        reason = _entry_point_reason(
            symbol,
            method_names,
            bases_by_type,
            configured,
        )
        updates.append((1 if reason else 0, reason, symbol_id))
    if updates:
        conn.executemany(
            "UPDATE symbols SET is_entry_point = ?, entry_point_reason = ? WHERE id = ?;",
            updates,
        )
    return sum(1 for is_entry, _reason, _id in updates if is_entry)


def _entry_point_reason(
    symbol: dict[str, Any],
    method_names: dict[int, set[str]],
    bases_by_type: dict[int, set[int]],
    configured: tuple[str, ...],
) -> str | None:
    """Return the first matching entry-point reason for *symbol*."""
    name = str(symbol["name"])
    kind = str(symbol["kind"])
    parent_id = symbol["parent_symbol_id"]
    if symbol["is_test"]:
        return "test"
    if name in ("main", "__main__") and kind in ("function", "method"):
        return "main"
    if kind == "constructor" or (name in ("__init__", "__new__") and parent_id is not None):
        return "constructor"
    if kind == "method" and parent_id is not None:
        for base_id in bases_by_type.get(int(parent_id), set()):
            if name in method_names.get(base_id, set()):
                return "override"
    if parent_id is None and symbol["visibility"] in _PUBLIC_VISIBILITIES:
        return "exported"
    rules = str(symbol["declared_rules"] or "")
    if rules and _ENTRY_POINT_ANNOTATION_RE.search(rules):
        return "annotation"
    fqn = str(symbol["fqn"])
    for pattern in configured:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(fqn, pattern):
            return "configured"
    return None


def compute_importance(conn: Any) -> int:
    """Store the adapted weighted-degree importance score on every symbol.

    The formula is documented and deterministic::

        importance = sqrt(incoming CALLS + USAGE)
                   * 0.1 for private symbols
                   * 0.1 when the name is defined in >= 5 distinct files
                   * 10  for a descriptive name of at least 8 characters
                   * 0.1 for test scaffolding

    Scores are rounded to six decimals so the same index always produces the
    same values.
    """
    placeholders = ",".join("?" for _ in _IMPORTANCE_EDGE_TYPES)
    incoming: dict[int, int] = {
        int(row["target_symbol_id"]): int(row["n"])
        for row in conn.execute(
            "SELECT target_symbol_id, COUNT(*) AS n FROM graph_edges "
            "WHERE resolved = 1 AND target_symbol_id IS NOT NULL "
            f"AND edge_type IN ({placeholders}) "
            "GROUP BY target_symbol_id;",
            _IMPORTANCE_EDGE_TYPES,
        )
    }
    file_spread: dict[str, int] = {
        str(row["name"]): int(row["n"])
        for row in conn.execute(
            "SELECT name, COUNT(DISTINCT file_path) AS n FROM symbols GROUP BY name;"
        )
    }
    updates: list[tuple[float, int]] = []
    for row in conn.execute("SELECT id, name, visibility, is_test FROM symbols ORDER BY id;"):
        score = math.sqrt(incoming.get(int(row["id"]), 0))
        if row["visibility"] in ("private", "package", "internal"):
            score *= 0.1
        if file_spread.get(str(row["name"]), 0) >= 5:
            score *= 0.1
        name = str(row["name"])
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) and len(name) >= 8:
            score *= 10.0
        if row["is_test"]:
            score *= 0.1
        updates.append((round(score, 6), int(row["id"])))
    if updates:
        conn.executemany("UPDATE symbols SET importance = ? WHERE id = ?;", updates)
    return len(updates)


def rebuild_symbol_degrees(conn: Any) -> int:
    """Replace ``symbol_degrees`` with counts over resolved symbol edges."""
    placeholders = ",".join("?" for _ in DEGREE_EDGE_TYPES)
    conn.execute("DELETE FROM symbol_degrees;")
    cursor = conn.execute(
        "INSERT OR REPLACE INTO symbol_degrees (symbol_id, edge_type, in_count, out_count) "
        "SELECT symbol_id, edge_type, SUM(in_count), SUM(out_count) FROM ( "
        "SELECT target_symbol_id AS symbol_id, edge_type, 1 AS in_count, 0 AS out_count "
        "FROM graph_edges WHERE resolved = 1 AND target_symbol_id IS NOT NULL "
        f"AND edge_type IN ({placeholders}) "
        "UNION ALL "
        "SELECT source_symbol_id AS symbol_id, edge_type, 0 AS in_count, 1 AS out_count "
        f"FROM graph_edges WHERE resolved = 1 AND edge_type IN ({placeholders}) "
        ") GROUP BY symbol_id, edge_type;",
        (*DEGREE_EDGE_TYPES, *DEGREE_EDGE_TYPES),
    )
    return max(0, int(cursor.rowcount))
