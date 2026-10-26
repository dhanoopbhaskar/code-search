"""Read-only, agent-facing graph surfaces over the SQLite index.

The traversal service in :mod:`code_search.engine.graph_query` answers
neighbourhood and path questions. This module answers the *discovery*
questions an agent must ask first: what labels and edge types exist, what a
file declares, which symbols match structural filters, and where the index has
gaps. Every function is read-only, deterministic, and bounded.

The functions return plain dictionaries so the CLI and the MCP server can share
the exact same payload shape. Transport concerns (freshness, audit entries) stay
in the calling surface.
"""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from code_search.engine.config import _is_test_file
from code_search.engine.graph import GRAPH_EDGE_TYPES, SCHEMA_VERSION, GraphDatabase
from code_search.engine.graph_metrics import collect_graph_metrics
from code_search.engine.paths import normalize_indexed_path

#: Stored symbol kinds accepted by the ``symbols.kind`` CHECK constraint.
SUPPORTED_NODE_KINDS: tuple[str, ...] = (
    "function",
    "class",
    "method",
    "variable",
    "import",
    "interface",
    "enum",
    "type_alias",
    "constructor",
    "field",
)

#: Edge types the schema accepts. Kept in sync with the ``graph_edges`` CHECK.
SUPPORTED_EDGE_TYPES: tuple[str, ...] = GRAPH_EDGE_TYPES

#: Edge types counted by default when ranking symbols by degree.
_DEGREE_EDGE_TYPES: tuple[str, ...] = (
    "CALLS",
    "INHERITS",
    "IMPLEMENTS",
    "REFERENCES",
    "USAGE",
    "CALL_REFERENCE",
)

#: Edge types that can contribute to a symbol's degree. ``IMPORTS`` is
#: file-level (``module_edges``), not a symbol edge.
_DEGREE_CAPABLE_EDGE_TYPES: frozenset[str] = frozenset(_DEGREE_EDGE_TYPES)

_MAX_OUTLINE_LIMIT = 500
_MAX_SEARCH_LIMIT = 200
_MAX_CONNECTED_NEIGHBORS = 10
_MAX_COVERAGE_ROWS = 500

#: Coverage row kind → agent-facing status.
_COVERAGE_STATUS_BY_KIND: dict[str, str] = {
    "parse_partial": "partial",
    "parse_unusable": "unusable",
    "skipped_read": "skipped",
    "skipped_oversized": "skipped",
    "skipped_extension": "skipped",
    "excluded_ignore": "excluded",
}

#: Worst-first ordering used to collapse several issues into one path status.
_COVERAGE_SEVERITY: dict[str, int] = {
    "coverage_unavailable": 5,
    "unusable": 4,
    "skipped": 3,
    "not_indexed": 3,
    "partial": 2,
    "excluded": 1,
    "no_recorded_issue": 0,
}

_COVERAGE_ACTIONS: dict[str, str] = {
    "no_recorded_issue": "Use graph results with the best-effort caveat.",
    "partial": "Read the reported line ranges and verify scope before trusting graph edges.",
    "unusable": "Read the source directly; the parse is not usable.",
    "skipped": "Read the source directly; the file was not indexed.",
    "excluded": "Read the source or adjust ignore rules, then reindex.",
    "not_indexed": "Reindex, or check the path spelling.",
    "coverage_unavailable": "Reindex to record coverage metadata.",
}


def changed_files_since(root: Path, ref: str) -> list[str]:
    """Return working-tree paths changed relative to git *ref*.

    Args:
        root: Repository root to run git in.
        ref: A commit, branch, or other ref accepted by ``git diff``.

    Returns:
        Index-relative paths in git's output order.

    Raises:
        RuntimeError: When git is unavailable or *ref* cannot be resolved.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", ref],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"git is unavailable: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"git diff failed for {ref!r}: {detail}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _metadata(conn: Any, key: str) -> str | None:
    """Return one ``index_metadata`` value, or ``None``."""
    row = conn.execute("SELECT value FROM index_metadata WHERE key = ?;", (key,)).fetchone()
    return str(row["value"]) if row is not None and row["value"] is not None else None


def _has_derived_data(conn: Any) -> bool:
    """Return whether this index carries the derived graph data.

    ``index_format_version`` is written by the indexer after the entry-point,
    importance, and degree passes. Its absence means the index predates them,
    so callers keep the conservative fallback rather than reading zeroes.
    """
    value = _metadata(conn, "index_format_version")
    if value is None:
        return False
    try:
        return int(value) >= 1
    except ValueError:
        return False


def _stored_symbol_path(conn: Any, candidate: str) -> str | None:
    """Return the stored ``symbols.file_path`` spelling for *candidate*.

    Exact match first; on a miss, compare resolved paths so a case- or
    symlink-variant spelling maps back to the indexed file.
    """
    row = conn.execute(
        "SELECT file_path FROM symbols WHERE file_path = ? LIMIT 1;", (candidate,)
    ).fetchone()
    if row is not None:
        return str(row["file_path"])
    try:
        resolved = Path(candidate).resolve()
    except OSError:
        return None
    for row in conn.execute("SELECT DISTINCT file_path FROM symbols;"):
        stored = str(row["file_path"])
        try:
            if Path(stored).resolve() == resolved:
                return stored
        except OSError:
            continue
    return None


def _relative_or_absolute(path: str, index_root: Path | None) -> str:
    """Return *path* relative to *index_root* when possible."""
    if index_root is None:
        return Path(path).as_posix()
    try:
        return Path(path).resolve().relative_to(index_root.resolve()).as_posix()
    except (ValueError, OSError):
        return Path(path).as_posix()


def _parent_names(conn: Any, parent_ids: set[int]) -> dict[int, str]:
    """Return ``{parent_id: parent_fqn}`` for the requested ids."""
    if not parent_ids:
        return {}
    placeholders = ",".join("?" for _ in parent_ids)
    rows = conn.execute(
        f"SELECT id, fqn FROM symbols WHERE id IN ({placeholders});", sorted(parent_ids)
    ).fetchall()
    return {int(row["id"]): str(row["fqn"]) for row in rows}


def get_graph_schema(
    db: GraphDatabase,
    *,
    diagnostics: bool = False,
    node_limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a bounded description of the graph an agent is about to query.

    Args:
        db: The graph database to inspect.
        diagnostics: When true, add per-edge property-key diagnostics sampled
            from stored edge properties (capped at 1,000 rows).
        node_limit: Maximum node labels to return (clipped to 500).
        offset: Zero-based offset into the sorted node-label list.

    Returns:
        A JSON-serialisable dict with generation, supported and stored labels,
        edge-type counts, resolution tiers, symbol totals, and coverage counts.
    """
    node_limit = max(1, min(node_limit, 500))
    offset = max(0, offset)
    metrics = collect_graph_metrics(db)
    with db.connect() as conn:
        generation = _metadata(conn, "index_generation") or metrics.get("index_generation")
        indexed_at = _metadata(conn, "last_indexed_at")
        index_root = _metadata(conn, "index_root")
        node_labels_all = dict(sorted(metrics.get("symbols", {}).get("by_kind", {}).items()))
        file_count = int(
            conn.execute("SELECT COUNT(DISTINCT file_path) AS n FROM symbols;").fetchone()["n"]
        )
        module_count = int(
            conn.execute("SELECT COUNT(DISTINCT source_path) AS n FROM module_edges;").fetchone()[
                "n"
            ]
        )

    labels = list(node_labels_all.items())
    page = labels[offset : offset + node_limit]
    payload: dict[str, Any] = {
        "index_generation": generation,
        "indexed_at": indexed_at,
        "index_root": index_root,
        "schema_version": SCHEMA_VERSION,
        "node_kinds_supported": list(SUPPORTED_NODE_KINDS),
        "node_labels": {kind: count for kind, count in page},
        "node_labels_total": len(labels),
        "node_labels_offset": offset,
        "synthetic_labels": {"file": file_count, "module": module_count},
        "edge_types_supported": list(SUPPORTED_EDGE_TYPES),
        "edge_types": metrics.get("edges", {}).get("by_type", {}),
        "resolution_tiers": metrics.get("edges", {}).get("by_tier", {}),
        "unresolved_top": metrics.get("unresolved_top", []),
        "symbols": metrics.get("symbols", {}),
        "entry_points": metrics.get("entry_points", {"total": 0, "by_reason": {}}),
        "importance": metrics.get("importance", {"available": False}),
        "index_format_version": metrics.get("index_format_version"),
        "coverage": metrics.get("coverage", {}),
        "stats": {
            "total_symbols": int(metrics.get("symbols", {}).get("total", 0)),
            "total_edges": int(metrics.get("edges", {}).get("total", 0)),
            "resolved_edges": int(metrics.get("edges", {}).get("resolved", 0)),
            "unresolved_edges": int(metrics.get("edges", {}).get("unresolved", 0)),
            "resolution_ratio": metrics.get("edges", {}).get("resolution_ratio", 0.0),
        },
        "note": (
            "absence is not proof of completeness: a clean schema means no gap was "
            "recorded, not that every reference resolved"
        ),
    }
    if diagnostics:
        payload["diagnostics"] = _edge_property_diagnostics(db)
    return payload


def _edge_property_diagnostics(db: GraphDatabase) -> dict[str, Any]:
    """Return bounded edge-property diagnostics for the current schema.

    The ``properties`` column is part of schema v18. A pre-migration database
    that was opened without ``initialize`` still lacks it, so the diagnostics
    report that fact instead of inventing keys.
    """
    with db.connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(graph_edges);")}
    if "properties" not in columns:
        return {
            "property_keys": {},
            "available": False,
            "detail": "edge properties are not stored in this schema version",
        }
    keys: Counter[str] = Counter()
    with db.connect() as conn:
        for row in conn.execute("SELECT properties FROM graph_edges LIMIT 1000;"):
            try:
                parsed = json.loads(row["properties"] or "{}")
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                keys.update(parsed.keys())
    return {"property_keys": dict(sorted(keys.items())), "available": True, "sampled": 1000}


def get_file_outline(
    db: GraphDatabase,
    file_path: str,
    *,
    index_root: Path | None = None,
    kinds: list[str] | None = None,
    limit: int = 200,
    offset: int = 0,
    include_docstring: bool = False,
) -> dict[str, Any]:
    """Return the declarations of one indexed file in source order.

    Args:
        db: The graph database to inspect.
        file_path: Absolute or index-relative path to the file.
        index_root: Indexed repository root used to resolve a relative path.
        kinds: Optional declaration-kind filter.
        limit: Maximum declarations to return (clipped to 500).
        offset: Zero-based offset into the source-ordered declaration list.
        include_docstring: Include the stored docstring (off by default to save
            response tokens).

    Returns:
        A JSON-serialisable outline with the resolved path, declarations,
        exact total, and truncation flag. ``outcome`` is ``not_indexed`` when
        no declaration for the file exists in the index.
    """
    limit = max(1, min(limit, _MAX_OUTLINE_LIMIT))
    offset = max(0, offset)
    root = index_root
    candidate: Path | None = None
    if root is not None:
        candidate = normalize_indexed_path(file_path, root)
    if candidate is None:
        raw = Path(file_path)
        candidate = raw.resolve() if raw.is_absolute() else raw

    with db.connect() as conn:
        stored = _stored_symbol_path(conn, str(candidate))
        if stored is None:
            return {
                "outcome": "not_indexed",
                "file_path": _relative_or_absolute(str(candidate), root),
                "stored_path": None,
                "symbols": [],
                "total": 0,
                "returned": 0,
                "offset": offset,
                "limit": limit,
                "truncated": False,
                "index_generation": _metadata(conn, "index_generation"),
            }
        params: list[Any] = [stored]
        kind_clause = ""
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            kind_clause = f" AND kind IN ({placeholders})"
            params.extend(kinds)
        total = int(
            conn.execute(
                f"SELECT COUNT(*) AS n FROM symbols WHERE file_path = ?{kind_clause};",
                params,
            ).fetchone()["n"]
        )
        rows = conn.execute(
            "SELECT id, name, kind, fqn, conventional_fqn, line_start, line_end, "
            "column_start, column_end, parent_symbol_id, docstring "
            f"FROM symbols WHERE file_path = ?{kind_clause} "
            "ORDER BY line_start, column_start, id LIMIT ? OFFSET ?;",
            [*params, limit, offset],
        ).fetchall()
        parents = _parent_names(
            conn, {int(row["parent_symbol_id"]) for row in rows if row["parent_symbol_id"]}
        )
        generation = _metadata(conn, "index_generation")

    declarations: list[dict[str, Any]] = []
    for row in rows:
        entry: dict[str, Any] = {
            "name": row["name"],
            "kind": row["kind"],
            "fqn": row["fqn"],
            "conventional_fqn": row["conventional_fqn"],
            "line_start": row["line_start"],
            "line_end": row["line_end"],
            "column_start": row["column_start"],
            "column_end": row["column_end"],
            "parent_fqn": parents.get(int(row["parent_symbol_id"]))
            if row["parent_symbol_id"]
            else None,
        }
        if include_docstring:
            entry["docstring"] = row["docstring"] or ""
        declarations.append(entry)

    return {
        "outcome": "resolved",
        "file_path": _relative_or_absolute(stored, root),
        "stored_path": stored,
        "symbols": declarations,
        "total": total,
        "returned": len(declarations),
        "offset": offset,
        "limit": limit,
        "truncated": offset + len(declarations) < total,
        "index_generation": generation,
    }


def _coerce_kinds(kind: str | list[str] | None) -> list[str]:
    """Return a de-duplicated kind list from a string or list input."""
    if kind is None:
        return []
    values = [kind] if isinstance(kind, str) else list(kind)
    result: list[str] = []
    for value in values:
        for part in str(value).split(","):
            part = part.strip()
            if part and part not in result:
                result.append(part)
    return result


def _entry_point_reason(file_path: str, name: str, kind: str, parent_fqn: str | None) -> str | None:
    """Classify an entry point for indexes without the stored classifier.

    The indexer now stores ``is_entry_point``/``entry_point_reason`` using the
    full rule set in :mod:`code_search.engine.graph_passes`. This conservative
    fallback remains only so an older index (before ``index_format_version``)
    still excludes tests, module-level ``main``, and constructors instead of
    silently disabling ``exclude_entry_points``.
    """
    if _is_test_file(file_path):
        return "test"
    if name in ("main", "__main__") and parent_fqn is None and kind == "function":
        return "main"
    if kind == "constructor":
        return "constructor"
    return None


def _compile_pattern(value: str | None, label: str) -> tuple[re.Pattern[str] | None, str | None]:
    """Compile an optional Python regex, returning ``(pattern, error)``."""
    if not value:
        return None, None
    try:
        return re.compile(value), None
    except re.error as exc:
        return None, f"invalid {label} regex: {exc}"


def _file_matcher(
    pattern: str | None,
) -> tuple[Any, str | None]:
    """Return a predicate matching a stored path against *pattern*.

    ``re:<regex>`` selects regular-expression matching; anything else is a
    shell-style glob matched against both the repository-relative path and the
    stored absolute path.
    """
    if not pattern:
        return (lambda _path, _relative: True), None
    if pattern.startswith("re:"):
        compiled, error = _compile_pattern(pattern[3:], "file_pattern")
        if error:
            return (lambda _path, _relative: False), error
        assert compiled is not None
        return (lambda _path, relative: bool(compiled.fullmatch(relative))), None
    lowered = pattern.lower()
    return (
        lambda path, relative: (
            fnmatch.fnmatch(relative.lower(), lowered) or fnmatch.fnmatch(path.lower(), lowered)
        ),
        None,
    )


def _degree_table_sql(edge_types: list[str], *, use_stored: bool = False) -> tuple[str, list[Any]]:
    """Return the CTE and parameters that aggregate resolved degrees.

    When *use_stored* is true the derived ``symbol_degrees`` table is used;
    otherwise the aggregation scans ``graph_edges``. Hand-built databases and
    pre-Phase-2 indexes lack degree rows, so the caller falls back to the live
    aggregation rather than reporting zero.
    """
    placeholders = ",".join("?" for _ in edge_types)
    if use_stored:
        cte = (
            "WITH in_deg AS ("
            "SELECT symbol_id, SUM(in_count) AS n FROM symbol_degrees "
            f"WHERE edge_type IN ({placeholders}) "
            "GROUP BY symbol_id), "
            "out_deg AS ("
            "SELECT symbol_id, SUM(out_count) AS n FROM symbol_degrees "
            f"WHERE edge_type IN ({placeholders}) "
            "GROUP BY symbol_id)"
        )
        return cte, [*edge_types, *edge_types]
    cte = (
        "WITH in_deg AS ("
        "SELECT target_symbol_id AS symbol_id, COUNT(*) AS n FROM graph_edges "
        f"WHERE resolved = 1 AND edge_type IN ({placeholders}) "
        "GROUP BY target_symbol_id), "
        "out_deg AS ("
        "SELECT source_symbol_id AS symbol_id, COUNT(*) AS n FROM graph_edges "
        f"WHERE resolved = 1 AND edge_type IN ({placeholders}) "
        "GROUP BY source_symbol_id)"
    )
    return cte, [*edge_types, *edge_types]


def search_symbols(
    db: GraphDatabase,
    *,
    query: str | None = None,
    name_pattern: str | None = None,
    qn_pattern: str | None = None,
    kind: str | list[str] | None = None,
    file_pattern: str | None = None,
    min_degree: int | None = None,
    max_degree: int | None = None,
    edge_types: list[str] | None = None,
    exclude_entry_points: bool = True,
    include_connected: bool = False,
    limit: int = 50,
    offset: int = 0,
    index_root: Path | None = None,
) -> dict[str, Any]:
    """Search symbols by structure rather than text similarity.

    Args:
        db: The graph database to inspect.
        query: Optional case-insensitive substring over name, FQN, and
            docstring.
        name_pattern: Optional Python regex, matched against the full name.
        qn_pattern: Optional Python regex, matched against the full FQN.
        kind: Optional declaration kind or kinds (``"method"``,
            ``"class,interface"``, ``["function"]``).
        file_pattern: Optional glob (or ``re:<regex>``) over the file path.
        min_degree: Minimum resolved total degree (incoming + outgoing).
        max_degree: Maximum resolved total degree.
        edge_types: Edge types counted for degree filters; defaults to the
            stored degree-capable set and ignores unresolved edges.
        exclude_entry_points: Exclude the stored entry-point classification
            (tests, ``main``, constructors, overrides, annotated handlers, and
            exported top-level declarations).
        include_connected: Attach up to ten resolved neighbours per returned
            symbol using one batched query.
        limit: Maximum symbols returned (clipped to 200).
        offset: Zero-based offset into the deterministically ordered matches.
        index_root: Indexed repository root, used for relative paths.

    Returns:
        A JSON-serialisable payload with ``symbols``, exact ``total``, paging,
        echoed filters, and coverage/generation context. An invalid regex
        returns ``outcome: invalid_argument`` rather than raising.
    """
    limit = max(1, min(limit, _MAX_SEARCH_LIMIT))
    offset = max(0, offset)
    kinds = _coerce_kinds(kind)
    requested_edge_types = sorted(
        {edge_type.upper() for edge_type in (edge_types or _DEGREE_EDGE_TYPES) if edge_type.strip()}
    )
    active_edge_types = [
        edge_type for edge_type in requested_edge_types if edge_type in _DEGREE_CAPABLE_EDGE_TYPES
    ]
    if not active_edge_types:
        return {
            "outcome": "invalid_argument",
            "error": (
                "degree filters support CALLS, INHERITS, and REFERENCES; "
                "IMPORTS is a file-level edge"
            ),
            "symbols": [],
            "total": 0,
            "returned": 0,
            "offset": offset,
            "limit": limit,
            "truncated": False,
        }
    name_re, name_error = _compile_pattern(name_pattern, "name_pattern")
    qn_re, qn_error = _compile_pattern(qn_pattern, "qn_pattern")
    file_match, file_error = _file_matcher(file_pattern)
    error = name_error or qn_error or file_error
    if error is not None:
        return {
            "outcome": "invalid_argument",
            "error": error,
            "symbols": [],
            "total": 0,
            "returned": 0,
            "offset": offset,
            "limit": limit,
            "truncated": False,
        }

    cte, degree_params = _degree_table_sql(active_edge_types)
    where: list[str] = []
    params: list[Any] = [*degree_params]
    if kinds:
        where.append(f"s.kind IN ({','.join('?' for _ in kinds)})")
        params.extend(kinds)
    if query:
        where.append(
            "(LOWER(s.name) LIKE ? OR LOWER(s.fqn) LIKE ? "
            "OR LOWER(COALESCE(s.docstring, '')) LIKE ?)"
        )
        like = f"%{query.lower()}%"
        params.extend([like, like, like])
    where_sql = f" WHERE {' AND '.join(where)}" if where else ""
    with db.connect() as conn:
        use_stored = _has_derived_data(conn)
        if use_stored:
            cte, _ = _degree_table_sql(active_edge_types, use_stored=True)
        order_sql = "s.importance DESC, s.fqn" if use_stored else "s.fqn"
        sql = (
            f"{cte} SELECT s.id, s.fqn, s.name, s.kind, s.file_path, s.line_start, s.line_end, "
            "s.docstring, s.conventional_fqn, s.canonical_fqn, s.importance, "
            "s.is_entry_point, s.entry_point_reason, p.fqn AS parent_fqn, "
            "COALESCE(in_deg.n, 0) AS in_degree, COALESCE(out_deg.n, 0) AS out_degree "
            "FROM symbols s LEFT JOIN symbols p ON p.id = s.parent_symbol_id "
            "LEFT JOIN in_deg ON in_deg.symbol_id = s.id "
            "LEFT JOIN out_deg ON out_deg.symbol_id = s.id"
            f"{where_sql} ORDER BY {order_sql};"
        )
        rows = conn.execute(sql, params).fetchall()
        generation = _metadata(conn, "index_generation")

    matches: list[dict[str, Any]] = []
    for row in rows:
        stored_path = str(row["file_path"])
        relative = _relative_or_absolute(stored_path, index_root)
        if name_re is not None and not name_re.fullmatch(str(row["name"])):
            continue
        if qn_re is not None and not qn_re.fullmatch(str(row["fqn"])):
            continue
        if not file_match(stored_path, relative):
            continue
        degree_total = int(row["in_degree"]) + int(row["out_degree"])
        if min_degree is not None and degree_total < min_degree:
            continue
        if max_degree is not None and degree_total > max_degree:
            continue
        if use_stored:
            reason = row["entry_point_reason"] if row["is_entry_point"] else None
        else:
            reason = _entry_point_reason(
                stored_path, str(row["name"]), str(row["kind"]), row["parent_fqn"]
            )
        if exclude_entry_points and reason is not None:
            continue
        matches.append(
            {
                "name": row["name"],
                "kind": row["kind"],
                "fqn": row["fqn"],
                "canonical_fqn": row["canonical_fqn"],
                "conventional_fqn": row["conventional_fqn"],
                "file_path": relative,
                "stored_path": stored_path,
                "line_start": row["line_start"],
                "line_end": row["line_end"],
                "parent_fqn": row["parent_fqn"],
                "degree": {
                    "in": int(row["in_degree"]),
                    "out": int(row["out_degree"]),
                    "total": degree_total,
                },
                "is_entry_point": reason is not None,
                "entry_point_reason": reason,
                "importance": float(row["importance"]) if use_stored else None,
                "_id": int(row["id"]),
            }
        )

    total = len(matches)
    page = matches[offset : offset + limit]
    if include_connected and page:
        neighbors = _connected_neighbors(db, [entry["_id"] for entry in page], active_edge_types)
        for entry in page:
            entry["connected"] = neighbors.get(entry["_id"], [])
    for entry in page:
        entry.pop("_id", None)

    return {
        "outcome": "resolved" if total else "no_match",
        "symbols": page,
        "total": total,
        "returned": len(page),
        "offset": offset,
        "limit": limit,
        "truncated": offset + len(page) < total,
        "filters": {
            "query": query,
            "name_pattern": name_pattern,
            "qn_pattern": qn_pattern,
            "kind": kinds or None,
            "file_pattern": file_pattern,
            "min_degree": min_degree,
            "max_degree": max_degree,
            "edge_types": active_edge_types,
            "exclude_entry_points": exclude_entry_points,
        },
        "index_generation": generation,
        "coverage_note": (
            "results describe indexed declarations only; an absent symbol may be "
            "unindexed or unresolved"
        ),
    }


_DEAD_CODE_EDGE_TYPES: tuple[str, ...] = (
    "CALLS",
    "USAGE",
    "CALL_REFERENCE",
    "REFERENCES",
    "IMPLEMENTS",
    "INHERITS",
)
_DEAD_CODE_KINDS: tuple[str, ...] = ("function", "method", "constructor")
_LOW_CONFIDENCE_TIERS: frozenset[str] = frozenset({"fallback", "ambiguous"})
_MAX_DEAD_CODE_ROWS = 200
_MAX_UNRESOLVED_TARGETS = 5000


def find_dead_code(
    db: GraphDatabase,
    *,
    kinds: str | list[str] | None = None,
    include_entry_points: bool = False,
    include_tests: bool = False,
    limit: int = 50,
    offset: int = 0,
    index_root: Path | None = None,
) -> dict[str, Any]:
    """Report callables with no proven incoming reference from production code.

    Candidates are functions, methods, and constructors with no resolved
    incoming ``CALLS``/``USAGE``/``CALL_REFERENCE``/``REFERENCES``/
    ``IMPLEMENTS``/``INHERITS`` edge from a non-test symbol. Entry points and
    test symbols are excluded by default. The result is evidence, never a
    deletion recommendation: unresolved same-name references and test-only
    usage are reported per row because they are exactly the cases where a
    dynamic or external caller could keep the symbol alive.

    Args:
        db: The graph database to inspect.
        kinds: Optional candidate kinds (defaults to function/method/constructor).
        include_entry_points: Include symbols classified as entry points.
        include_tests: Include test symbols as candidates.
        limit: Maximum candidates returned (clipped to 200).
        offset: Zero-based offset into the ordered candidates.
        index_root: Indexed repository root, used for relative paths.

    Returns:
        A JSON-serialisable payload with ``candidates``, exact ``total``,
        paging, the edge types checked, and a coverage caveat.
    """
    limit = max(1, min(limit, _MAX_DEAD_CODE_ROWS))
    offset = max(0, offset)
    requested_kinds = _coerce_kinds(kinds) or list(_DEAD_CODE_KINDS)
    unknown_kinds = sorted(set(requested_kinds) - set(SUPPORTED_NODE_KINDS))
    if unknown_kinds:
        return {
            "outcome": "invalid_argument",
            "error": f"unsupported kind(s): {', '.join(unknown_kinds)}",
            "supported_kinds": list(_DEAD_CODE_KINDS),
            "candidates": [],
            "total": 0,
            "returned": 0,
            "offset": offset,
            "limit": limit,
            "truncated": False,
        }

    type_placeholders = ",".join("?" for _ in _DEAD_CODE_EDGE_TYPES)
    kind_placeholders = ",".join("?" for _ in requested_kinds)
    low_tiers = ",".join(f"'{tier}'" for tier in sorted(_LOW_CONFIDENCE_TIERS))
    rows: list[Any] = []
    unresolved: list[Any] = []
    generation: str | None = None
    with db.connect() as conn:
        use_stored = _has_derived_data(conn)
        generation = _metadata(conn, "index_generation")
        rows = conn.execute(
            "WITH incoming AS ("
            "SELECT e.target_symbol_id AS id, "
            "SUM(CASE WHEN src.is_test = 0 AND "
            f"COALESCE(e.resolution_tier, '') NOT IN ({low_tiers}) "
            "THEN 1 ELSE 0 END) AS proven, "
            "SUM(CASE WHEN src.is_test = 0 AND "
            f"COALESCE(e.resolution_tier, '') IN ({low_tiers}) "
            "THEN 1 ELSE 0 END) AS low_confidence, "
            "SUM(CASE WHEN src.is_test = 1 THEN 1 ELSE 0 END) AS test_usage "
            "FROM graph_edges e JOIN symbols src ON src.id = e.source_symbol_id "
            "WHERE e.resolved = 1 AND e.target_symbol_id IS NOT NULL "
            f"AND e.edge_type IN ({type_placeholders}) "
            "GROUP BY e.target_symbol_id) "
            "SELECT s.id, s.fqn, s.canonical_fqn, s.name, s.kind, s.file_path, "
            "s.line_start, s.line_end, s.visibility, s.is_test, s.is_entry_point, "
            "s.entry_point_reason, s.importance, p.fqn AS parent_fqn, "
            "COALESCE(inc.proven, 0) AS proven, "
            "COALESCE(inc.low_confidence, 0) AS low_confidence, "
            "COALESCE(inc.test_usage, 0) AS test_usage "
            "FROM symbols s LEFT JOIN symbols p ON p.id = s.parent_symbol_id "
            "LEFT JOIN incoming inc ON inc.id = s.id "
            f"WHERE s.kind IN ({kind_placeholders}) "
            "AND COALESCE(p.kind, '') != 'interface' "
            "ORDER BY s.fqn;",
            [*_DEAD_CODE_EDGE_TYPES, *requested_kinds],
        ).fetchall()
        unresolved = conn.execute(
            "SELECT target_raw, COUNT(*) AS n FROM graph_edges "
            "WHERE resolved = 0 AND target_raw IS NOT NULL AND target_raw != '' "
            f"AND edge_type IN ({type_placeholders}) "
            "GROUP BY target_raw ORDER BY target_raw LIMIT ?;",
            [*_DEAD_CODE_EDGE_TYPES, _MAX_UNRESOLVED_TARGETS],
        ).fetchall()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        stored_path = str(row["file_path"] or "")
        is_test = bool(row["is_test"]) or _is_test_file(stored_path)
        if is_test and not include_tests:
            continue
        if use_stored:
            reason = row["entry_point_reason"] if row["is_entry_point"] else None
        else:
            reason = _entry_point_reason(
                stored_path, str(row["name"]), str(row["kind"]), row["parent_fqn"]
            )
        if reason is not None and not include_entry_points:
            continue
        if int(row["proven"]) > 0:
            continue
        unresolved_count = sum(
            int(item["n"]) for item in unresolved if str(row["name"]) in str(item["target_raw"])
        )
        confidence = _dead_code_confidence(
            int(row["low_confidence"]), int(row["test_usage"]), unresolved_count
        )
        candidates.append(
            {
                "name": row["name"],
                "kind": row["kind"],
                "fqn": row["fqn"],
                "canonical_fqn": row["canonical_fqn"],
                "file_path": _relative_or_absolute(stored_path, index_root),
                "stored_path": stored_path,
                "line_start": row["line_start"],
                "line_end": row["line_end"],
                "visibility": row["visibility"],
                "is_test": is_test,
                "is_entry_point": reason is not None,
                "entry_point_reason": reason,
                "importance": float(row["importance"] or 0.0),
                "incoming": {
                    "proven": int(row["proven"]),
                    "low_confidence": int(row["low_confidence"]),
                    "test": int(row["test_usage"]),
                    "unresolved_same_name": unresolved_count,
                },
                "confidence": confidence,
                "used_only_by_tests": (
                    int(row["test_usage"]) > 0 and int(row["low_confidence"]) == 0
                ),
            }
        )

    order = {"high": 0, "medium": 1, "low": 2}
    candidates.sort(
        key=lambda item: (
            order.get(item["confidence"], 3),
            str(item["is_test"]),
            -float(item["importance"]),
            item["fqn"],
        )
    )
    total = len(candidates)
    page = candidates[offset : offset + limit]
    return {
        "outcome": "resolved",
        "candidates": page,
        "total": total,
        "returned": len(page),
        "offset": offset,
        "limit": limit,
        "truncated": offset + len(page) < total,
        "edge_types_checked": list(_DEAD_CODE_EDGE_TYPES),
        "kinds": requested_kinds,
        "include_entry_points": include_entry_points,
        "include_tests": include_tests,
        "index_generation": generation,
        "note": (
            "candidates have no proven production reference in this index; "
            "absence is not proof of completeness, so verify unresolved and "
            "dynamic call sites before changing code"
        ),
    }


def _dead_code_confidence(low_confidence: int, test_usage: int, unresolved: int) -> str:
    """Return the documented dead-code confidence label."""
    if low_confidence > 0:
        return "low"
    if test_usage > 0 or unresolved > 0:
        return "medium"
    return "high"


def _connected_neighbors(
    db: GraphDatabase, symbol_ids: list[int], edge_types: list[str]
) -> dict[int, list[dict[str, Any]]]:
    """Return up to ten resolved neighbours per symbol in one batched query."""
    placeholders = ",".join("?" for _ in symbol_ids)
    type_placeholders = ",".join("?" for _ in edge_types)
    params: list[Any] = [
        *symbol_ids,
        *edge_types,
        *symbol_ids,
        *edge_types,
        max(1, len(symbol_ids)) * 10,
    ]
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT e.source_symbol_id, e.target_symbol_id, e.edge_type AS relation, "
            "s.fqn, s.name, s.kind "
            "FROM graph_edges e JOIN symbols s ON s.id = e.target_symbol_id "
            "WHERE e.resolved = 1 "
            f"AND e.source_symbol_id IN ({placeholders}) "
            f"AND e.edge_type IN ({type_placeholders}) "
            "UNION ALL "
            "SELECT e.source_symbol_id, e.target_symbol_id, e.edge_type AS relation, "
            "s.fqn, s.name, s.kind "
            "FROM graph_edges e JOIN symbols s ON s.id = e.source_symbol_id "
            "WHERE e.resolved = 1 "
            f"AND e.target_symbol_id IN ({placeholders}) "
            f"AND e.edge_type IN ({type_placeholders}) "
            "ORDER BY relation, fqn LIMIT ?;",
            params,
        ).fetchall()

    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        source_id = int(row["source_symbol_id"])
        target_id = int(row["target_symbol_id"])
        for subject, direction in ((source_id, "outbound"), (target_id, "inbound")):
            if subject not in symbol_ids:
                continue
            bucket = grouped.setdefault(subject, [])
            if len(bucket) >= _MAX_CONNECTED_NEIGHBORS:
                continue
            if any(
                item["fqn"] == row["fqn"] and item["relation"] == row["relation"] for item in bucket
            ):
                continue
            bucket.append(
                {
                    "fqn": row["fqn"],
                    "name": row["name"],
                    "kind": row["kind"],
                    "relation": row["relation"],
                    "direction": direction,
                }
            )
    return grouped


def render_symbol_search_text(payload: dict[str, Any]) -> str:
    """Render a structural symbol-search payload as compact text."""
    if payload.get("outcome") == "invalid_argument":
        return f"Invalid search: {payload.get('error')}"
    if not payload.get("symbols"):
        return (
            "No matching symbols (an absent symbol may be unindexed; "
            "run 'code-search coverage' to check)"
        )
    lines = [
        f"{payload.get('total', 0)} matching symbols "
        f"(showing {payload.get('returned', 0)} from {payload.get('offset', 0)})"
    ]
    for symbol in payload.get("symbols", []):
        degree = symbol.get("degree", {})
        entry = " [entry point]" if symbol.get("is_entry_point") else ""
        importance = symbol.get("importance")
        score = f" imp={importance:.3f}" if importance is not None else ""
        lines.append(
            f"  {symbol['kind']:<12} {symbol['name']}  "
            f"({symbol['file_path']}:{symbol['line_start']})  "
            f"in={degree.get('in', 0)} out={degree.get('out', 0)}{score}{entry}"
        )
    if payload.get("truncated"):
        lines.append("  (truncated; use --limit/--offset for the next page)")
    return "\n".join(lines)


def render_dead_code_text(payload: dict[str, Any]) -> str:
    """Render a dead-code payload as compact text with its caveats."""
    if payload.get("outcome") == "invalid_argument":
        return f"Invalid request: {payload.get('error')}"
    candidates = payload.get("candidates") or []
    if not candidates:
        return (
            "No dead-code candidates "
            "(absence is not proof of completeness; run 'code-search coverage')"
        )
    lines = [
        f"{payload.get('total', 0)} dead-code candidates "
        f"(showing {payload.get('returned', 0)} from {payload.get('offset', 0)})"
    ]
    for item in candidates:
        incoming = item.get("incoming", {})
        lines.append(
            f"  {item['confidence']:<6} {item['kind']:<12} {item['name']}  "
            f"({item['file_path']}:{item['line_start']})  "
            f"test={incoming.get('test', 0)} unresolved={incoming.get('unresolved_same_name', 0)}"
        )
    if payload.get("truncated"):
        lines.append("  (truncated; use --limit/--offset for the next page)")
    note = payload.get("note")
    if note:
        lines.append(f"Note: {note}")
    return "\n".join(lines)


def _stored_checksum_path(conn: Any, candidate: str) -> str | None:
    """Return the stored ``file_checksums.file_path`` spelling for *candidate*."""
    row = conn.execute(
        "SELECT file_path FROM file_checksums WHERE file_path = ? LIMIT 1;", (candidate,)
    ).fetchone()
    if row is not None:
        return str(row["file_path"])
    try:
        resolved = Path(candidate).resolve()
    except OSError:
        return None
    for row in conn.execute("SELECT file_path FROM file_checksums;"):
        stored = str(row["file_path"])
        try:
            if Path(stored).resolve() == resolved:
                return stored
        except OSError:
            continue
    return None


def _coverage_status_for_kind(kind: str) -> str:
    """Map a stored coverage kind to the agent-facing status."""
    return _COVERAGE_STATUS_BY_KIND.get(kind, "partial")


def _worst_status(statuses: list[str]) -> str:
    """Return the most severe status, or ``no_recorded_issue`` when empty."""
    if not statuses:
        return "no_recorded_issue"
    return max(statuses, key=lambda status: _COVERAGE_SEVERITY.get(status, 0))


def _file_freshness(stored_path: str, checksum: dict[str, Any] | None) -> str:
    """Compare the recorded checksum row with the file on disk.

    Returns ``current``, ``modified``, ``missing``, or ``unknown``.
    """
    if checksum is None:
        return "unknown"
    try:
        stat = Path(stored_path).stat()
    except OSError:
        return "missing"
    recorded_size = checksum.get("size")
    recorded_mtime = checksum.get("file_mtime_ns")
    if recorded_size is None and recorded_mtime is None:
        return "unknown"
    if (recorded_size is not None and int(recorded_size) != stat.st_size) or (
        recorded_mtime is not None and int(recorded_mtime) != stat.st_mtime_ns
    ):
        return "modified"
    return "current"


def check_index_coverage(
    db: GraphDatabase,
    *,
    paths: list[str] | None = None,
    scopes: list[str] | None = None,
    index_root: Path | None = None,
    parser: Any | None = None,
    max_rows: int = _MAX_COVERAGE_ROWS,
) -> dict[str, Any]:
    """Report where the index has gaps, per requested path or scope.

    The report distinguishes a clean file from a file that was never indexed:
    ``no_recorded_issue`` means "indexed and no gap was recorded", while
    ``not_indexed``/``skipped``/``excluded`` mean the graph cannot answer for
    that path. A clean result is not proof of completeness.

    Args:
        db: The graph database to inspect.
        paths: Specific absolute or index-relative file paths.
        scopes: Index-relative directory prefixes to aggregate.
        index_root: Indexed repository root used to resolve relative inputs.
        parser: Optional :class:`~code_search.engine.parser.ASTParser`, used to
            classify an unindexed path as excluded or unsupported.
        max_rows: Maximum gap rows or scope entries returned (clipped to 1000).

    Returns:
        A JSON-serialisable coverage payload with per-path entries, per-scope
        aggregates, a summary, and a recommended action.
    """
    max_rows = max(1, min(max_rows, 1000))
    root = index_root
    with db.connect() as conn:
        generation = _metadata(conn, "index_generation")
        indexed_at = _metadata(conn, "last_indexed_at")
        checksum_rows = {
            str(row["file_path"]): {
                "size": row["size"],
                "file_mtime_ns": row["file_mtime_ns"],
                "parse_failed": int(row["parse_failed"] or 0),
            }
            for row in conn.execute(
                "SELECT file_path, size, file_mtime_ns, parse_failed FROM file_checksums;"
            )
        }
        coverage_sql = "SELECT file_path, kind, detail, line_ranges FROM index_coverage"
        coverage_params: tuple[Any, ...] = ()
        if generation is not None:
            coverage_sql += " WHERE generation = ?"
            coverage_params = (generation,)
        coverage_rows: dict[str, list[dict[str, Any]]] = {}
        for row in conn.execute(coverage_sql + " ORDER BY file_path, kind;", coverage_params):
            coverage_rows.setdefault(str(row["file_path"]), []).append(
                {
                    "kind": str(row["kind"]),
                    "detail": str(row["detail"] or ""),
                    "line_ranges": _parse_line_ranges(row["line_ranges"]),
                }
            )

    entries: list[dict[str, Any]] = []
    scope_entries: list[dict[str, Any]] = []
    by_status: Counter[str] = Counter()
    truncated = False

    resolved_paths: list[tuple[str, str]] = []
    with db.connect() as conn:
        for requested in paths or []:
            if root is not None:
                normalized = normalize_indexed_path(requested, root)
                candidate = str(normalized) if normalized is not None else requested
            else:
                raw = Path(requested)
                candidate = str(raw.resolve()) if raw.is_absolute() else requested
            resolved_paths.append((candidate, _stored_checksum_path(conn, candidate) or ""))

    for candidate, stored in resolved_paths:
        indexed = bool(stored)
        path = stored or candidate
        entry = _coverage_entry(
            path,
            indexed=indexed,
            coverage_rows=coverage_rows.get(path, []),
            checksum=checksum_rows.get(path),
            generation=generation,
            root=root,
            parser=parser,
        )
        entries.append(entry)
        by_status[entry["status"]] += 1
        if len(entries) >= max_rows:
            truncated = True
            break

    scope_limit = max_rows - len(entries)
    for scope in scopes or []:
        if len(scope_entries) >= max(0, scope_limit):
            truncated = True
            break
        scope_entries.append(
            _coverage_scope_entry(
                scope,
                checksum_rows=checksum_rows,
                coverage_rows=coverage_rows,
                generation=generation,
                root=root,
            )
        )

    gaps: list[dict[str, Any]] = []
    if not paths and not scopes:
        for stored_path, issues in sorted(coverage_rows.items()):
            for issue in issues:
                if len(gaps) >= max_rows:
                    truncated = True
                    break
                status = _coverage_status_for_kind(issue["kind"])
                by_status[status] += 1
                gaps.append(
                    {
                        "file_path": _relative_or_absolute(stored_path, root),
                        "stored_path": stored_path,
                        "status": status,
                        "kind": issue["kind"],
                        "detail": issue["detail"],
                        "line_ranges": issue["line_ranges"],
                        "freshness": _file_freshness(stored_path, checksum_rows.get(stored_path)),
                    }
                )
            if truncated:
                break

    statuses = [entry["status"] for entry in entries]
    statuses.extend(entry["status"] for entry in scope_entries)
    statuses.extend(gap["status"] for gap in gaps)
    if not statuses:
        status = "coverage_unavailable" if generation is None else "no_recorded_issue"
    else:
        status = _worst_status(statuses)
    if generation is None:
        status = "coverage_unavailable"

    return {
        "outcome": "coverage_unavailable" if generation is None else "resolved",
        "status": status,
        "index_generation": generation,
        "indexed_at": indexed_at,
        "coverage_complete": not coverage_rows,
        "entries": entries,
        "scopes": scope_entries,
        "gaps": gaps,
        "summary": {
            "requested": len(paths or []) + len(scopes or []),
            "returned": len(entries) + len(scope_entries) + len(gaps),
            "by_status": dict(sorted(by_status.items())),
            "truncated": truncated,
        },
        "recommended_action": _COVERAGE_ACTIONS.get(status, _COVERAGE_ACTIONS["not_indexed"]),
        "note": (
            "absence is not proof of completeness: no_recorded_issue means no gap "
            "was recorded for this generation, not that every reference resolved"
        ),
    }


def _parse_line_ranges(raw: Any) -> list[list[int]]:
    """Parse the stored JSON line ranges, tolerating malformed rows."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    result: list[list[int]] = []
    for item in parsed[:50]:
        if isinstance(item, list) and len(item) == 2:
            try:
                result.append([int(item[0]), int(item[1])])
            except (TypeError, ValueError):
                continue
    return result


def _coverage_entry(
    path: str,
    *,
    indexed: bool,
    coverage_rows: list[dict[str, Any]],
    checksum: dict[str, Any] | None,
    generation: str | None,
    root: Path | None,
    parser: Any | None,
) -> dict[str, Any]:
    """Build one per-path coverage entry.

    Args:
        path: Stored spelling when indexed, otherwise the caller's candidate.
        indexed: Whether the file appears in ``file_checksums``.
        coverage_rows: Recorded gaps for this file in the current generation.
        checksum: Recorded size/mtime row, when indexed.
        generation: Current index generation, or ``None`` on an old index.
        root: Indexed repository root for relative display.
        parser: Optional parser used to classify an unindexed path.

    Returns:
        A per-path entry with status, kind, ranges, freshness, and an action.
    """
    if generation is None:
        status = "coverage_unavailable"
        kind = None
    elif coverage_rows:
        statuses = [_coverage_status_for_kind(issue["kind"]) for issue in coverage_rows]
        status = _worst_status(statuses)
        kind = coverage_rows[0]["kind"]
    elif indexed:
        status = "no_recorded_issue"
        kind = None
    else:
        status, kind = _classify_unindexed_path(path, root, parser)

    line_ranges: list[list[int]] = []
    for issue in coverage_rows:
        line_ranges.extend(issue["line_ranges"])
    detail = "; ".join(issue["detail"] for issue in coverage_rows if issue.get("detail"))
    return {
        "file_path": _relative_or_absolute(path, root),
        "stored_path": path if indexed else None,
        "status": status,
        "kind": kind,
        "detail": detail,
        "line_ranges": line_ranges[:50],
        "freshness": _file_freshness(path, checksum),
        "recommended_action": _COVERAGE_ACTIONS.get(status, _COVERAGE_ACTIONS["not_indexed"]),
    }


def _classify_unindexed_path(
    candidate: str, root: Path | None, parser: Any | None
) -> tuple[str, str | None]:
    """Classify a path absent from both coverage and file checksums."""
    path = Path(candidate)
    if parser is not None:
        try:
            if root is not None and parser.is_excluded_file(path, root):
                return "excluded", "excluded_ignore"
            if not parser.is_supported_file(path):
                return "skipped", "skipped_extension"
        except Exception:
            pass
    return "not_indexed", None


def _coverage_scope_entry(
    scope: str,
    *,
    checksum_rows: dict[str, Any],
    coverage_rows: dict[str, list[dict[str, Any]]],
    generation: str | None,
    root: Path | None,
) -> dict[str, Any]:
    """Aggregate coverage for one index-relative directory scope."""
    normalized = scope.strip().strip("/")
    if root is not None:
        absolute = normalize_indexed_path(scope, root)
        if absolute is not None:
            normalized = _relative_or_absolute(str(absolute), root).strip("/")
    prefix = f"{normalized}/" if normalized else ""
    files = [
        stored
        for stored in checksum_rows
        if _relative_or_absolute(stored, root) == normalized
        or _relative_or_absolute(stored, root).startswith(prefix)
    ]
    gap_files = [stored for stored in files if stored in coverage_rows]
    issues = [
        {
            "file_path": _relative_or_absolute(stored, root),
            "kind": issue["kind"],
            "detail": issue["detail"],
            "line_ranges": issue["line_ranges"],
            "status": _coverage_status_for_kind(issue["kind"]),
        }
        for stored in gap_files[:100]
        for issue in coverage_rows[stored]
    ]
    if generation is None:
        status = "coverage_unavailable"
    elif not files:
        status = "not_indexed"
    elif issues:
        status = _worst_status([issue["status"] for issue in issues])
    else:
        status = "no_recorded_issue"
    return {
        "scope": normalized,
        "status": status,
        "indexed_files": len(files),
        "files_with_gaps": len(gap_files),
        "gaps": issues,
        "recommended_action": _COVERAGE_ACTIONS.get(status, _COVERAGE_ACTIONS["not_indexed"]),
    }


def render_coverage_text(payload: dict[str, Any]) -> str:
    """Render a coverage payload as compact text."""
    summary = payload.get("summary", {})
    lines = [
        f"Coverage ({payload.get('status')}, generation "
        f"{payload.get('index_generation') or 'unknown'})"
    ]
    for entry in payload.get("entries", []):
        detail = f" — {entry['detail']}" if entry.get("detail") else ""
        ranges = f" lines={entry['line_ranges']}" if entry.get("line_ranges") else ""
        lines.append(
            f"  {entry['file_path']}: {entry['status']} [{entry.get('freshness')}]{detail}{ranges}"
        )
    for scope in payload.get("scopes", []):
        lines.append(
            f"  {scope['scope']}: {scope['status']} "
            f"({scope['indexed_files']} files, {scope['files_with_gaps']} with gaps)"
        )
    for gap in payload.get("gaps", []):
        detail = f" — {gap['detail']}" if gap.get("detail") else ""
        lines.append(f"  {gap['file_path']}: {gap['status']} ({gap['kind']}){detail}")
    if not payload.get("entries") and not payload.get("scopes") and not payload.get("gaps"):
        lines.append("  No gaps recorded for this generation.")
    by_status = summary.get("by_status") or {}
    if by_status:
        lines.append(
            "Summary: " + ", ".join(f"{status}={count}" for status, count in by_status.items())
        )
    if summary.get("truncated"):
        lines.append("  (truncated; narrow the paths/scopes or raise the row cap)")
    lines.append(f"Action: {payload.get('recommended_action')}")
    return "\n".join(lines)


def render_graph_schema_text(payload: dict[str, Any]) -> str:
    """Render a graph-schema payload as compact text."""
    lines = [
        f"Graph schema (generation {payload.get('index_generation') or 'unknown'})",
        f"Index: {payload.get('index_root') or 'unknown'}"
        f" (schema v{payload.get('schema_version')})",
    ]
    symbols = payload.get("symbols", {})
    total_symbols = int(symbols.get("total", 0))
    lines.append(f"Symbols: {total_symbols:,} ({payload.get('node_labels_total', 0)} kinds)")
    for kind, count in payload.get("node_labels", {}).items():
        lines.append(f"  {kind:<14} {int(count):>8,}")
    synthetic = payload.get("synthetic_labels", {})
    if synthetic:
        rendered = ", ".join(f"{key}={int(value):,}" for key, value in synthetic.items())
        lines.append(f"Synthetic labels: {rendered}")

    stats = payload.get("stats", {})
    lines.append(
        "Edges: "
        f"{int(stats.get('total_edges', 0)):,} "
        f"(resolved {int(stats.get('resolved_edges', 0)):,}, "
        f"unresolved {int(stats.get('unresolved_edges', 0)):,})"
    )
    for edge_type in payload.get("edge_types_supported", []):
        stat = payload.get("edge_types", {}).get(edge_type)
        if stat:
            lines.append(
                f"  {edge_type:<12} {int(stat['total']):>8,} ({int(stat['resolved']):,} resolved)"
            )
        else:
            lines.append(f"  {edge_type:<12} {0:>8,} (not emitted)")
    tiers = payload.get("resolution_tiers", {})
    if tiers:
        rendered = ", ".join(f"{tier}={int(count):,}" for tier, count in tiers.items())
        lines.append(f"Resolution tiers: {rendered}")

    entry_points = payload.get("entry_points", {})
    if int(entry_points.get("total", 0)):
        reasons = ", ".join(
            f"{reason}={int(count):,}"
            for reason, count in entry_points.get("by_reason", {}).items()
        )
        lines.append(f"Entry points: {int(entry_points['total']):,} ({reasons})")
    importance = payload.get("importance", {})
    if importance.get("available"):
        lines.append(
            f"Importance: {int(importance.get('nonzero', 0)):,} scored "
            f"(max {float(importance.get('max', 0.0)):.3f})"
        )

    coverage = payload.get("coverage", {})
    lines.append(
        f"Coverage gaps: {int(coverage.get('total', 0)):,}"
        f" (complete: {str(bool(coverage.get('complete'))).lower()})"
    )
    note = payload.get("note")
    if note:
        lines.append(f"Note: {note}")
    return "\n".join(lines)


def render_file_outline_text(payload: dict[str, Any]) -> str:
    """Render a file-outline payload as compact text."""
    if payload.get("outcome") != "resolved":
        return f"{payload.get('file_path')}: not indexed (run 'code-search coverage' to check why)"
    lines = [
        f"{payload.get('file_path')} ({payload.get('total', 0)} declarations, "
        f"showing {payload.get('returned', 0)})"
    ]
    for symbol in payload.get("symbols", []):
        parent = ""
        if symbol.get("parent_fqn"):
            parent = f" in {symbol['parent_fqn'].rsplit('::', 1)[-1]}"
        lines.append(
            f"  {int(symbol['line_start']):>5}  {symbol['kind']:<12} {symbol['name']}{parent}"
        )
    if payload.get("truncated"):
        lines.append("  (truncated; increase --limit or use --offset)")
    return "\n".join(lines)
