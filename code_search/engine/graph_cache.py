"""Generation-keyed in-memory adjacency cache for the symbol graph.

The graph lives in SQLite. Answering a multi-hop question with one query per
visited node makes latency a function of the node count instead of the edge
count. This module materialises the resolved symbol edges once per index
generation into compact arrays, so a walk reads neighbour slices from memory.

Design constraints:

* **Generation-keyed.** The cache key is ``(database path, index_generation)``.
  A reindex publishes a new generation, which makes the old snapshot
  unreachable; a committed write drops the entry eagerly.
* **Bounded.** The snapshot reports its estimated size. A snapshot above the
  configured budget is refused (and remembered as over-budget) instead of
  being silently kept. Idle entries expire.
* **Best effort.** Any build failure falls back to the SQL path; the cache is
  an optimisation, never a correctness requirement.
* **Resolved structure only.** Unresolved references are evidence, not graph
  structure, so only edges with a target participate. Containment is derived
  from ``symbols.parent_symbol_id`` and is always available.

The class is deliberately small: a CSR (compressed sparse row) layout per
direction plus a symbol-directory dict. No third-party graph library is used.
"""

from __future__ import annotations

import array
import contextlib
import logging
import os
import threading
import time
from bisect import bisect_left
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from code_search.engine.config import Settings
    from code_search.engine.graph import GraphDatabase

logger = logging.getLogger(__name__)

#: Per-symbol overhead of the directory dictionaries and dataclass instances,
#: used only for the cache-budget estimate.
_ESTIMATED_SYMBOL_OVERHEAD = 240


@dataclass(frozen=True, slots=True)
class CachedSymbol:
    """Symbol metadata needed to shape a node without another SQL query."""

    id: int
    fqn: str
    name: str
    kind: str
    file_path: str
    line_start: int
    line_end: int
    conventional_fqn: str | None
    docstring: str | None
    parent_id: int | None
    is_test: bool


@dataclass(frozen=True, slots=True)
class CachedNeighbor:
    """One adjacent symbol reached through a stored edge."""

    symbol_id: int
    edge_type: str
    resolution_tier: str | None


class GraphSnapshot:
    """Read-only, in-memory view of one index generation's adjacency.

    The CSR arrays are grouped in ascending symbol-id order. ``_ids`` is the
    sorted id array used to map a symbol id to its row without a second dict.
    """

    __slots__ = (
        "_child_ids",
        "_child_indptr",
        "_estimated_bytes",
        "_ids",
        "_in_indptr",
        "_in_other",
        "_in_tier",
        "_in_type",
        "_out_indptr",
        "_out_other",
        "_out_tier",
        "_out_type",
        "_symbols",
        "_tier_names",
        "_type_codes",
        "_type_names",
        "edge_count",
        "generation",
    )

    def __init__(
        self,
        *,
        generation: str,
        ids: array.array[int],
        symbols: dict[int, CachedSymbol],
        type_names: list[str],
        tier_names: list[str | None],
        out_indptr: array.array[int],
        out_other: array.array[int],
        out_type: array.array[int],
        out_tier: array.array[int],
        in_indptr: array.array[int],
        in_other: array.array[int],
        in_type: array.array[int],
        in_tier: array.array[int],
        child_indptr: array.array[int],
        child_ids: array.array[int],
        estimated_bytes: int,
        edge_count: int,
    ) -> None:
        self.generation = generation
        self.edge_count = edge_count
        self._ids = ids
        self._symbols = symbols
        self._type_names = type_names
        self._tier_names = tier_names
        self._type_codes = {name: code for code, name in enumerate(type_names)}
        self._out_indptr = out_indptr
        self._out_other = out_other
        self._out_type = out_type
        self._out_tier = out_tier
        self._in_indptr = in_indptr
        self._in_other = in_other
        self._in_type = in_type
        self._in_tier = in_tier
        self._child_indptr = child_indptr
        self._child_ids = child_ids
        self._estimated_bytes = estimated_bytes

    @property
    def symbol_count(self) -> int:
        """Return the number of symbols in the snapshot."""
        return len(self._ids)

    @property
    def estimated_bytes(self) -> int:
        """Return the snapshot's estimated resident size in bytes."""
        return self._estimated_bytes

    def symbol(self, symbol_id: int) -> CachedSymbol | None:
        """Return the cached directory entry for *symbol_id*, if any."""
        return self._symbols.get(symbol_id)

    def type_codes(self, edge_types: set[str] | frozenset[str]) -> frozenset[int]:
        """Translate edge-type names to the snapshot's compact type codes.

        Unknown names are ignored. An empty input yields an empty code set,
        which callers treat as "no edge types to traverse".
        """
        codes = {
            self._type_codes[edge_type] for edge_type in edge_types if edge_type in self._type_codes
        }
        return frozenset(codes)

    def iter_out(
        self, symbol_id: int, type_codes: frozenset[int] | None = None
    ) -> Iterator[CachedNeighbor]:
        """Yield outgoing neighbours of *symbol_id* in stored order.

        Args:
            symbol_id: The source symbol.
            type_codes: Type codes to include; ``None`` includes every type.
        """
        position = self._position(symbol_id)
        if position is None:
            return
        start = self._out_indptr[position]
        stop = self._out_indptr[position + 1]
        for index in range(start, stop):
            code = self._out_type[index]
            if type_codes is not None and code not in type_codes:
                continue
            yield CachedNeighbor(
                symbol_id=self._out_other[index],
                edge_type=self._type_names[code],
                resolution_tier=self._tier_names[self._out_tier[index]],
            )

    def iter_in(
        self, symbol_id: int, type_codes: frozenset[int] | None = None
    ) -> Iterator[CachedNeighbor]:
        """Yield incoming neighbours of *symbol_id* in stored order."""
        position = self._position(symbol_id)
        if position is None:
            return
        start = self._in_indptr[position]
        stop = self._in_indptr[position + 1]
        for index in range(start, stop):
            code = self._in_type[index]
            if type_codes is not None and code not in type_codes:
                continue
            yield CachedNeighbor(
                symbol_id=self._in_other[index],
                edge_type=self._type_names[code],
                resolution_tier=self._tier_names[self._in_tier[index]],
            )

    def children(self, symbol_id: int) -> Iterator[int]:
        """Yield declared child symbols (structural containment, parent first)."""
        position = self._position(symbol_id)
        if position is None:
            return
        start = self._child_indptr[position]
        stop = self._child_indptr[position + 1]
        for index in range(start, stop):
            yield self._child_ids[index]

    def parent(self, symbol_id: int) -> int | None:
        """Return the declaring parent symbol id, if any."""
        symbol = self._symbols.get(symbol_id)
        return symbol.parent_id if symbol is not None else None

    def _position(self, symbol_id: int) -> int | None:
        """Return the CSR row for *symbol_id* using binary search."""
        index = bisect_left(self._ids, symbol_id)
        if index < len(self._ids) and self._ids[index] == symbol_id:
            return index
        return None


def read_index_generation(db: GraphDatabase) -> str | None:
    """Return the current index generation, or ``None`` for an old index."""
    try:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT value FROM index_metadata WHERE key = 'index_generation';"
            ).fetchone()
    except Exception:
        return None
    if row is None or not row["value"]:
        return None
    return str(row["value"])


def _intern(value: str | None, names: list[Any], codes: dict[str | None, int]) -> int:
    """Return the compact code for *value*, appending it to *names* if new."""
    code = codes.get(value)
    if code is None:
        code = len(names)
        names.append(value)
        codes[value] = code
    return code


def build_snapshot(db: GraphDatabase, generation: str) -> GraphSnapshot:
    """Read one index generation into a compact adjacency snapshot.

    Args:
        db: The graph database to read.
        generation: The generation token the snapshot describes.

    Returns:
        A :class:`GraphSnapshot`. The database must already have the v18
        symbol columns; :meth:`GraphDatabase.initialize` migrates them.
    """
    with db.connect() as conn:
        # Read symbols and edges from one WAL snapshot. Without an explicit
        # transaction each statement could observe a different commit while an
        # index is publishing, producing a snapshot that never existed.
        conn.execute("BEGIN;")
        try:
            ids = array.array("q")
            symbols: dict[int, CachedSymbol] = {}
            for row in conn.execute(
                "SELECT id, fqn, name, kind, file_path, line_start, line_end, "
                "conventional_fqn, docstring, parent_symbol_id, is_test "
                "FROM symbols ORDER BY id;"
            ):
                symbol_id = int(row["id"])
                ids.append(symbol_id)
                symbols[symbol_id] = CachedSymbol(
                    id=symbol_id,
                    fqn=str(row["fqn"]),
                    name=str(row["name"]),
                    kind=str(row["kind"]),
                    file_path=str(row["file_path"]),
                    line_start=int(row["line_start"]),
                    line_end=int(row["line_end"]),
                    conventional_fqn=row["conventional_fqn"],
                    docstring=row["docstring"],
                    parent_id=(
                        int(row["parent_symbol_id"])
                        if row["parent_symbol_id"] is not None
                        else None
                    ),
                    is_test=bool(row["is_test"]),
                )
            position = {symbol_id: index for index, symbol_id in enumerate(ids)}

            type_names: list[str] = []
            type_codes: dict[str | None, int] = {}
            tier_names: list[str | None] = [None]
            tier_codes: dict[str | None, int] = {None: 0}
            edge_source = array.array("q")
            edge_target = array.array("q")
            edge_type = array.array("h")
            edge_tier = array.array("h")
            for row in conn.execute(
                "SELECT source_symbol_id, target_symbol_id, edge_type, resolution_tier "
                "FROM graph_edges "
                "WHERE resolved = 1 AND target_symbol_id IS NOT NULL "
                "AND source_symbol_id != target_symbol_id "
                "ORDER BY source_symbol_id, id;"
            ):
                source = int(row["source_symbol_id"])
                target = int(row["target_symbol_id"])
                if source not in position or target not in position:
                    continue
                edge_source.append(source)
                edge_target.append(target)
                edge_type.append(_intern(str(row["edge_type"]), type_names, type_codes))
                edge_tier.append(_intern(row["resolution_tier"], tier_names, tier_codes))
        finally:
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK;")

    out_indptr, out_other, out_type, out_tier = _build_csr(
        edge_source, edge_target, edge_type, edge_tier, position, len(ids)
    )
    in_indptr, in_other, in_type, in_tier = _build_csr(
        edge_target, edge_source, edge_type, edge_tier, position, len(ids)
    )
    child_indptr, child_ids = _build_children(ids, symbols, position)
    estimated = _estimate_bytes(
        ids=ids,
        symbols=symbols,
        arrays=(
            out_indptr,
            out_other,
            out_type,
            out_tier,
            in_indptr,
            in_other,
            in_type,
            in_tier,
            child_indptr,
            child_ids,
        ),
    )
    return GraphSnapshot(
        generation=generation,
        ids=ids,
        symbols=symbols,
        type_names=type_names,
        tier_names=tier_names,
        out_indptr=out_indptr,
        out_other=out_other,
        out_type=out_type,
        out_tier=out_tier,
        in_indptr=in_indptr,
        in_other=in_other,
        in_type=in_type,
        in_tier=in_tier,
        child_indptr=child_indptr,
        child_ids=child_ids,
        estimated_bytes=estimated,
        edge_count=len(edge_source),
    )


def _build_csr(
    group_keys: array.array[int],
    other_keys: array.array[int],
    types: array.array[int],
    tiers: array.array[int],
    position: dict[int, int],
    symbol_count: int,
) -> tuple[array.array[int], array.array[int], array.array[int], array.array[int]]:
    """Group edges by *group_keys* into CSR arrays.

    Args:
        group_keys: The endpoint the list is keyed by (source or target id).
        other_keys: The opposite endpoint for each edge.
        types: Compact edge-type code per edge.
        tiers: Compact resolution-tier code per edge.
        position: Symbol id to CSR row map.
        symbol_count: Number of symbols (CSR row count).
    """
    indptr = array.array("q", [0]) * (symbol_count + 1)
    for symbol_id in group_keys:
        row = position[symbol_id]
        indptr[row + 1] += 1
    for index in range(symbol_count):
        indptr[index + 1] += indptr[index]
    others = array.array("q", [0]) * len(group_keys)
    edge_types = array.array("h", [0]) * len(group_keys)
    edge_tiers = array.array("h", [0]) * len(group_keys)
    cursor = array.array("q", indptr)
    for index in range(len(group_keys)):
        row = position[group_keys[index]]
        slot = cursor[row]
        cursor[row] += 1
        others[slot] = other_keys[index]
        edge_types[slot] = types[index]
        edge_tiers[slot] = tiers[index]
    return indptr, others, edge_types, edge_tiers


def _build_children(
    ids: array.array[int],
    symbols: dict[int, CachedSymbol],
    position: dict[int, int],
) -> tuple[array.array[int], array.array[int]]:
    """Build the containment CSR from ``symbols.parent_symbol_id``."""
    indptr = array.array("q", [0]) * (len(ids) + 1)
    for symbol in symbols.values():
        if symbol.parent_id is None or symbol.parent_id not in position:
            continue
        indptr[position[symbol.parent_id] + 1] += 1
    for index in range(len(ids)):
        indptr[index + 1] += indptr[index]
    children = array.array("q", [0]) * int(indptr[-1])
    cursor = array.array("q", indptr)
    for symbol_id in ids:
        symbol = symbols[symbol_id]
        if symbol.parent_id is None or symbol.parent_id not in position:
            continue
        row = position[symbol.parent_id]
        slot = cursor[row]
        cursor[row] += 1
        children[slot] = symbol_id
    return indptr, children


def _estimate_bytes(
    *,
    ids: array.array[int],
    symbols: dict[int, CachedSymbol],
    arrays: tuple[array.array[int], ...],
) -> int:
    """Estimate the snapshot's resident size for the cache budget."""
    total = ids.itemsize * len(ids)
    for values in arrays:
        total += values.itemsize * len(values)
    for symbol in symbols.values():
        total += _ESTIMATED_SYMBOL_OVERHEAD
        total += len(symbol.fqn) + len(symbol.name) + len(symbol.file_path)
        total += len(symbol.conventional_fqn or "")
        total += len(symbol.docstring or "")
    return total


@dataclass(slots=True)
class _Entry:
    """A cached snapshot plus its LRU timestamp."""

    snapshot: GraphSnapshot
    last_used: float


class AdjacencyCache:
    """Thread-safe LRU registry of generation-keyed graph snapshots."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: OrderedDict[tuple[str, str], _Entry] = OrderedDict()
        self._over_budget: dict[tuple[str, str], int] = {}
        self._hits = 0
        self._misses = 0
        self._builds = 0

    def get(self, db: GraphDatabase, settings: Settings) -> GraphSnapshot | None:
        """Return a snapshot for the database's current generation.

        Returns ``None`` when the cache is disabled, the database has no
        generation token, the generation is already known to exceed the
        budget, or the build fails. Callers then use their SQL path.
        """
        if not settings.graph_cache_enabled:
            return None
        max_bytes = max(0, int(settings.graph_cache_max_bytes))
        if max_bytes == 0:
            return None
        generation = read_index_generation(db)
        if generation is None:
            return None
        db_path = os.fspath(db.db_path)
        key = (db_path, generation)
        now = time.monotonic()
        with self._lock:
            self._expire_idle(settings.graph_cache_idle_seconds, now)
            self._drop_other_generations(db_path, generation)
            entry = self._entries.get(key)
            if entry is not None:
                entry.last_used = now
                self._entries.move_to_end(key)
                self._hits += 1
                return entry.snapshot
            if key in self._over_budget:
                self._misses += 1
                return None
            self._builds += 1
            try:
                snapshot = build_snapshot(db, generation)
            except Exception:
                logger.warning("Adjacency cache build failed; using SQL", exc_info=True)
                self._misses += 1
                return None
            if snapshot.estimated_bytes > max_bytes:
                self._over_budget[key] = snapshot.estimated_bytes
                self._misses += 1
                logger.info(
                    "Adjacency cache refused: %d bytes exceeds the %d-byte budget",
                    snapshot.estimated_bytes,
                    max_bytes,
                )
                return None
            self._entries[key] = _Entry(snapshot=snapshot, last_used=now)
            self._evict(max_bytes)
            return snapshot

    def invalidate(self, db_path: str | Path) -> None:
        """Drop every snapshot for *db_path* (call after a committed write)."""
        target = os.fspath(db_path)
        with self._lock:
            for key in [key for key in self._entries if key[0] == target]:
                del self._entries[key]
            for key in [key for key in self._over_budget if key[0] == target]:
                del self._over_budget[key]

    def clear(self) -> None:
        """Drop every snapshot and reset the hit/miss counters."""
        with self._lock:
            self._entries.clear()
            self._over_budget.clear()
            self._hits = 0
            self._misses = 0
            self._builds = 0

    def stats(self) -> dict[str, Any]:
        """Return cache diagnostics for benchmarks and schema output."""
        with self._lock:
            entries = [
                {
                    "db_path": key[0],
                    "generation": key[1],
                    "symbols": entry.snapshot.symbol_count,
                    "edges": entry.snapshot.edge_count,
                    "bytes": entry.snapshot.estimated_bytes,
                    "last_used_seconds_ago": round(time.monotonic() - entry.last_used, 1),
                }
                for key, entry in self._entries.items()
            ]
            return {
                "entries": entries,
                "bytes": sum(entry["bytes"] for entry in entries),
                "hits": self._hits,
                "misses": self._misses,
                "builds": self._builds,
                "over_budget": len(self._over_budget),
            }

    def _drop_other_generations(self, db_path: str, generation: str) -> None:
        """Remove superseded generations for the same database."""
        for key in [key for key in self._entries if key[0] == db_path and key[1] != generation]:
            del self._entries[key]
        for key in [key for key in self._over_budget if key[0] == db_path and key[1] != generation]:
            del self._over_budget[key]

    def _expire_idle(self, idle_seconds: float, now: float) -> None:
        """Drop entries unused for longer than *idle_seconds* (0 disables)."""
        if idle_seconds <= 0:
            return
        for key in [
            key for key, entry in self._entries.items() if now - entry.last_used > idle_seconds
        ]:
            del self._entries[key]

    def _evict(self, max_bytes: int) -> None:
        """Evict least-recently-used entries until the budget is respected."""
        while self._entries:
            total = sum(entry.snapshot.estimated_bytes for entry in self._entries.values())
            if total <= max_bytes:
                return
            self._entries.popitem(last=False)


_CACHE = AdjacencyCache()


def adjacency_snapshot(db: GraphDatabase, settings: Settings) -> GraphSnapshot | None:
    """Return the current snapshot from the process-wide cache, if usable."""
    return _CACHE.get(db, settings)


def invalidate_adjacency_cache(db_path: str | Path) -> None:
    """Drop cached snapshots for *db_path* after a committed graph write."""
    _CACHE.invalidate(db_path)


def adjacency_cache_stats() -> dict[str, Any]:
    """Return process-wide adjacency-cache diagnostics."""
    return _CACHE.stats()


def clear_adjacency_cache() -> None:
    """Drop and reset the process-wide cache (tests and maintenance)."""
    _CACHE.clear()
