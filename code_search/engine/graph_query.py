"""Graph traversal and explanation over the symbol and module graph.

The service seeds a traversal from the existing hybrid search ranker, walks the
resolved ``graph_edges`` (and optional ``module_edges``) with bounded BFS, and
returns a compact, provenance-labelled answer. It deliberately returns
neighbourhoods rather than source bodies so multi-hop questions fit an agent's
context budget.

Design constraints:

* No network access and no LLM calls.
* No ``networkx`` dependency; traversal is plain Python over SQLite.
* Deterministic ordering for the same index and query.
* Every rendered edge carries a confidence label derived from the persisted
  resolution tier (``EXTRACTED`` / ``INFERRED`` / ``AMBIGUOUS`` /
  ``UNRESOLVED``).
"""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from code_search.engine.config import Settings, _is_test_file
from code_search.engine.graph import (
    DocLinkStore,
    EdgeStore,
    GraphDatabase,
    ModuleEdgeStore,
    RationaleStore,
    read_source_slice,
)
from code_search.engine.graph_cache import (
    CachedSymbol,
    GraphSnapshot,
    adjacency_snapshot,
)
from code_search.engine.query_terms import morphological_variants
from code_search.engine.symbols import SymbolStore

#: Resolution tier → graphify-style confidence label.
CONFIDENCE_BY_TIER: dict[str, str] = {
    "exact": "EXTRACTED",
    "conventional": "EXTRACTED",
    "import": "EXTRACTED",
    "same_file": "INFERRED",
    "range": "INFERRED",
    "type_infer": "INFERRED",
    "derived": "INFERRED",
    "fallback": "AMBIGUOUS",
    "ambiguous": "AMBIGUOUS",
}

#: Confidence ordering, most trustworthy first.
CONFIDENCE_ORDER: dict[str, int] = {
    "EXTRACTED": 0,
    "INFERRED": 1,
    "AMBIGUOUS": 2,
    "UNRESOLVED": 3,
}

VALID_EDGE_TYPES = {
    "CALLS",
    "IMPORTS",
    "INHERITS",
    "IMPLEMENTS",
    "REFERENCES",
    "USAGE",
    "CALL_REFERENCE",
    "TESTS",
}
DEFAULT_EDGE_TYPES = frozenset({"CALLS", "INHERITS"})
_TYPE_KINDS = frozenset({"class", "interface", "enum"})

#: Bounded aspects accepted by :meth:`GraphQueryService.architecture`.
ARCHITECTURE_ASPECTS = frozenset(
    {
        "overview",
        "structure",
        "dependencies",
        "hotspots",
        "entry_points",
        "clusters",
        "cycles",
    }
)

_MAX_DEPTH = 4
_MAX_NODES = 200
_MAX_FANOUT = 50
_DEFAULT_TOKEN_BUDGET = 1500
_MAX_PATH_HOPS = 6
_MAX_PATH_NODES = 1000


def display_symbol(fqn: str) -> str:
    """Return *fqn* with its filesystem path prefix removed for human display.

    Stored FQNs are ``<absolute file path>::<declaration>``. The path prefix is
    noise in text output, so it is dropped while logical module prefixes (for
    example ``pkg.module::Thing``) are preserved.
    """
    if fqn.startswith("file:"):
        return fqn[5:]
    if "::" in fqn:
        prefix, declaration = fqn.rsplit("::", 1)
        if "/" in prefix or "\\" in prefix:
            return declaration
    return fqn


def relative_display(file_path: str | None, root: str | Path | None) -> str:
    """Return *file_path* relative to *root* in POSIX form for display."""
    if not file_path:
        return "?"
    if root:
        try:
            return Path(file_path).resolve().relative_to(Path(root).resolve()).as_posix()
        except (ValueError, OSError):
            pass
    return Path(file_path).as_posix()


def _render_edge(edge: GraphEdge) -> str:
    """Render *edge* with human-friendly endpoints."""
    source = display_symbol(edge.source)
    target = display_symbol(edge.target)
    if edge.direction == "reverse":
        if edge.relation == "CONTAINS":
            return f"{target} --member of--> {source}"
        return f"{target} <--{edge.relation}/{edge.confidence}-- {source}"
    return f"{source} --{edge.relation}/{edge.confidence}--> {target}"


def resolve_confidence(resolution_tier: str | None, resolved: bool = True) -> str:
    """Return the graphify-style confidence label for an edge.

    Args:
        resolution_tier: Persisted tier (``exact``, ``conventional``,
            ``import``, ``same_file``, ``range``, ``type_infer``, ``derived``,
            ``fallback``, ``ambiguous``) or ``None``.
        resolved: Whether the edge target resolved to a symbol.

    Returns:
        ``EXTRACTED`` for exact/conventional/import, ``INFERRED`` for
        same-file/range/type-inferred/derived, ``AMBIGUOUS`` for
        fallback/ambiguous, and ``UNRESOLVED`` when *resolved* is false.
    """
    if not resolved:
        return "UNRESOLVED"
    return CONFIDENCE_BY_TIER.get(resolution_tier or "", "INFERRED")


def edge_resolution_stats(db: GraphDatabase) -> dict[str, dict[str, int]]:
    """Return per-edge-type ``{total, resolved, unresolved, ratio}`` counts.

    This is the graph-quality metric: a healthy index keeps a non-zero resolved
    ratio for every produced edge type, and imports should not silently reach
    zero rows.
    """
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT edge_type, COUNT(*) AS total, COALESCE(SUM(resolved), 0) AS resolved "
            "FROM graph_edges GROUP BY edge_type ORDER BY edge_type;"
        ).fetchall()
    stats: dict[str, dict[str, int]] = {}
    for row in rows:
        total = int(row["total"])
        resolved = int(row["resolved"])
        stats[str(row["edge_type"])] = {
            "total": total,
            "resolved": resolved,
            "unresolved": total - resolved,
            "ratio": round(1000 * resolved / total) if total else 0,
        }
    return stats


def _candidate_identifiers(text: str) -> list[str]:
    """Return likely symbol references from *text*, longest and most specific first."""
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", text)
    ordered: list[str] = []
    for token in sorted(set(tokens), key=lambda value: (-len(value), value)):
        if len(token) < 4:
            continue
        if not (any(ch.isupper() for ch in token) or "." in token or "_" in token):
            continue
        ordered.append(token)
    return ordered


# Question words and glue that must not drive per-term seed coverage: a
# parameter type named ``NewCommentParam`` is not evidence that a comment
# method answers a question about a "new article".
_QUERY_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "and",
        "are",
        "before",
        "been",
        "being",
        "between",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "into",
        "its",
        "over",
        "that",
        "the",
        "this",
        "through",
        "under",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)


def _terms(text: str) -> set[str]:
    """Return lowercased identifier/word terms from *text*."""
    parts = re.split(r"[^A-Za-z0-9_]+|(?<=[a-z0-9])(?=[A-Z])|_", text)
    return {p.lower() for p in parts if len(p) >= 3}


def _query_terms(text: str) -> set[str]:
    """Return significant query terms and their morphological variants.

    A question says ``saving`` where the indexed declaration says ``save``, so
    the variants are what make per-term seed coverage work on natural-language
    questions instead of only on identifier-shaped ones.
    """
    terms = _terms(text) - _QUERY_STOPWORDS
    expanded: set[str] = set(terms)
    for term in terms:
        expanded.update(morphological_variants(term))
    return expanded - _QUERY_STOPWORDS


def _symbol_terms(fqn: str, name: str) -> set[str]:
    """Return the declaration terms of a symbol, excluding parameter types."""
    declaration = fqn.split("(", 1)[0]
    return _terms(declaration + " " + name)


@dataclass(frozen=True)
class GraphNode:
    """A node in a graph answer (symbol, file, or unresolved external leaf).

    ``reason`` is populated on seed nodes to explain why the seed was chosen;
    it is ``None`` for nodes reached by traversal.
    """

    key: str
    fqn: str
    name: str
    kind: str
    file_path: str | None
    line_start: int | None
    line_end: int | None
    source: str = "symbol"
    distance: int = 0
    signature: str | None = None
    docstring: str | None = None
    reason: str | None = None
    symbol_id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable node payload."""
        return {
            "key": self.key,
            "fqn": self.fqn,
            "name": self.name,
            "kind": self.kind,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "source": self.source,
            "distance": self.distance,
            "signature": self.signature,
            "docstring": self.docstring,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GraphEdge:
    """A directed relation between two graph-answer nodes."""

    source: str
    target: str
    relation: str
    confidence: str
    direction: str = "forward"
    resolution_tier: str | None = None
    target_raw: str | None = None
    source_range: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable edge payload."""
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "confidence": self.confidence,
            "direction": self.direction,
            "resolution_tier": self.resolution_tier,
            "target_raw": self.target_raw,
            "source_range": self.source_range,
        }

    def render(self) -> str:
        """Render the edge in its actual direction, flagging reverse traversal."""
        rendered = f"{self.source} --{self.relation}/{self.confidence}--> {self.target}"
        if self.direction == "reverse":
            rendered += " (backwards)"
        return rendered


@dataclass
class GraphAnswer:
    """The result of a graph query."""

    question: str
    seeds: list[GraphNode] = field(default_factory=list)
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    truncated: bool = False
    outcome: str = "resolved"
    stats: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return the structured (JSON) graph answer."""
        return {
            "outcome": self.outcome,
            "seeds": [n.as_dict() for n in self.seeds],
            "nodes": [n.as_dict() for n in self.nodes],
            "edges": [e.as_dict() for e in self.edges],
            "truncated": self.truncated,
            "stats": self.stats,
        }


@dataclass
class PathAnswer:
    """The result of a shortest-path request."""

    source: GraphNode | None = None
    target: GraphNode | None = None
    hops: list[GraphEdge] = field(default_factory=list)
    undirected: bool = False
    outcome: str = "resolved"
    candidates: list[dict[str, Any]] = field(default_factory=list)
    explanation: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def found(self) -> bool:
        """Return whether a path was found."""
        return bool(self.hops) and self.outcome == "resolved"

    def as_dict(self) -> dict[str, Any]:
        """Return the structured (JSON) path answer."""
        return {
            "outcome": self.outcome,
            "found": self.found,
            "source": self.source.as_dict() if self.source else None,
            "target": self.target.as_dict() if self.target else None,
            "hops": [h.as_dict() for h in self.hops],
            "undirected": self.undirected,
            "candidates": self.candidates,
            "explanation": self.explanation,
            "stats": self.stats,
        }


@dataclass
class ExplainAnswer:
    """The result of an ``explain`` request (a symbol ego graph)."""

    symbol: GraphNode | None = None
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    rationale: list[dict[str, Any]] = field(default_factory=list)
    doc_links: list[dict[str, Any]] = field(default_factory=list)
    outcome: str = "resolved"
    candidates: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    stats: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return the structured (JSON) explain answer."""
        return {
            "outcome": self.outcome,
            "symbol": self.symbol.as_dict() if self.symbol else None,
            "nodes": [n.as_dict() for n in self.nodes],
            "edges": [e.as_dict() for e in self.edges],
            "rationale": self.rationale,
            "doc_links": self.doc_links,
            "candidates": self.candidates,
            "truncated": self.truncated,
            "stats": self.stats,
        }


@dataclass
class ImpactAnswer:
    """Symbols and files impacted by a set of changed files."""

    changed_paths: list[str] = field(default_factory=list)
    symbols: list[GraphNode] = field(default_factory=list)
    impacted: list[GraphNode] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    production_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    test_symbols: list[GraphNode] = field(default_factory=list)
    production_symbols: list[GraphNode] = field(default_factory=list)
    risks: dict[str, str] = field(default_factory=dict)
    risk_summary: dict[str, int] = field(default_factory=dict)
    parents: dict[str, dict[str, str]] = field(default_factory=dict)
    direction: str = "inbound"
    via: list[str] = field(default_factory=list)
    fixpoint: bool = False
    truncated: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return the structured impact payload."""
        return {
            "changed_paths": self.changed_paths,
            "symbols": [n.as_dict() for n in self.symbols],
            "impacted": [n.as_dict() for n in self.impacted],
            "files": self.files,
            "production_files": self.production_files,
            "test_files": self.test_files,
            "test_symbols": [n.as_dict() for n in self.test_symbols],
            "production_symbols": [n.as_dict() for n in self.production_symbols],
            "risks": self.risks,
            "risk_summary": self.risk_summary,
            "parents": self.parents,
            "direction": self.direction,
            "via": self.via,
            "fixpoint": self.fixpoint,
            "truncated": self.truncated,
            "summary": self.summary,
        }


@dataclass
class ArchitectureReport:
    """Deterministic architecture overview of the indexed graph."""

    god_nodes: list[dict[str, Any]] = field(default_factory=list)
    communities: list[dict[str, Any]] = field(default_factory=list)
    import_cycles: list[list[str]] = field(default_factory=list)
    isolated: list[dict[str, Any]] = field(default_factory=list)
    edge_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    suggested_questions: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return the structured report payload."""
        return {
            "god_nodes": self.god_nodes,
            "communities": self.communities,
            "import_cycles": self.import_cycles,
            "isolated": self.isolated,
            "edge_stats": self.edge_stats,
            "suggested_questions": self.suggested_questions,
            "stats": self.stats,
        }


class GraphQueryService:
    """Query, path, and explain over the indexed symbol/module graph."""

    def __init__(
        self,
        db: GraphDatabase,
        symbol_store: SymbolStore,
        edge_store: EdgeStore,
        search: Any,
        settings: Settings | None = None,
        module_store: ModuleEdgeStore | None = None,
        rationale_store: RationaleStore | None = None,
        doc_link_store: DocLinkStore | None = None,
        reranker: Any | None = None,
    ) -> None:
        """Wire the service to the existing engine components.

        Args:
            db: Graph database handle.
            symbol_store: Symbol resolution and lookup.
            edge_store: Symbol-level edge traversal.
            search: The hybrid ``HybridSearch`` instance used for seed
                selection.
            settings: Engine settings (defaults to ``Settings.from_env()``).
            module_store: Optional module-edge store.
            rationale_store: Optional rationale store.
            doc_link_store: Optional documentation-link store.
            reranker: Optional result reranker. When supplied, seeds are chosen
                from the same reranked hits the search surface returns instead
                of the raw fusion order.
        """
        self._db = db
        self._symbols = symbol_store
        self._edges = edge_store
        self._search = search
        self._reranker = reranker
        self._settings = settings or Settings.from_env()
        self._modules = module_store or ModuleEdgeStore(db)
        self._rationale = rationale_store or RationaleStore(db)
        self._doc_links = doc_link_store or DocLinkStore(db)
        self._index_root = self._read_index_root()

    def _read_index_root(self) -> Path:
        """Return the indexed repository root recorded in metadata."""
        try:
            with self._db.connect() as conn:
                row = conn.execute(
                    "SELECT value FROM index_metadata WHERE key = 'index_root';"
                ).fetchone()
            if row is not None and row["value"]:
                return Path(str(row["value"]))
        except Exception:
            pass
        return self._settings.context_dir.parent

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    def query(
        self,
        question: str,
        *,
        depth: int = 2,
        max_nodes: int = 120,
        edge_types: set[str] | None = None,
        token_budget: int = _DEFAULT_TOKEN_BUDGET,
        seeds: list[str] | None = None,
        include_external: bool = False,
        direction: str = "both",
    ) -> GraphAnswer:
        """Traverse the graph from hybrid-search seeds and answer *question*.

        Args:
            question: Natural-language or identifier query used to seed.
            depth: Maximum BFS depth (clipped to 4).
            max_nodes: Maximum returned nodes (clipped to 200).
            edge_types: Edge types to traverse (default ``CALLS``/``INHERITS``).
            token_budget: Soft output budget used when trimming the answer.
            seeds: Optional explicit seed symbol references; when omitted seeds
                are derived from hybrid search.
            include_external: When false (the default), unresolved/external
                callee leaves are collapsed out of the neighbourhood so the
                answer is a clean in-corpus graph. The collapsed count is
                reported in ``stats["collapsed_externals"]``.
            direction: ``both`` (default neighbourhood), ``inbound``
                (callers/importers/subtypes), or ``outbound``
                (callees/imports/base types). Unknown values fall back to
                ``both`` for compatibility.

        Returns:
            A :class:`GraphAnswer`; ``outcome`` is ``no_seed`` when nothing
            could be mapped to a symbol.
        """
        start = time.monotonic()
        if direction not in {"inbound", "outbound", "both"}:
            direction = "both"
        depth = max(0, min(depth, _MAX_DEPTH))
        max_nodes = max(1, min(max_nodes, _MAX_NODES))
        active_types = (edge_types or set(DEFAULT_EDGE_TYPES)) & VALID_EDGE_TYPES
        seed_nodes = self._select_seeds(question, seeds)
        if not seed_nodes:
            return GraphAnswer(
                question=question,
                outcome="no_seed",
                stats={
                    "direction": direction,
                    "elapsed_ms": round((time.monotonic() - start) * 1000, 1),
                },
            )
        nodes: dict[str, GraphNode] = {n.key: n for n in seed_nodes}
        edges: list[GraphEdge] = []
        seen_edges: set[tuple[str, str, str, str]] = set()
        queue: deque[tuple[GraphNode, int]] = deque((n, 0) for n in seed_nodes)
        truncated = False
        collapsed_externals = 0

        while queue:
            node, node_depth = queue.popleft()
            if node_depth >= depth:
                continue
            if len(nodes) >= max_nodes:
                truncated = True
                break
            outgoing, fanout_truncated = self._fetch_outgoing(
                node, active_types, direction=direction
            )
            if fanout_truncated:
                truncated = True
            for edge, target in outgoing:
                if target.source == "external" and not include_external:
                    collapsed_externals += 1
                    continue
                if len(nodes) >= max_nodes:
                    truncated = True
                    break
                edge_key = (edge.source, edge.target, edge.relation, edge.confidence)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edges.append(edge)
                existing = nodes.get(target.key)
                if existing is None:
                    target = GraphNode(
                        key=target.key,
                        fqn=target.fqn,
                        name=target.name,
                        kind=target.kind,
                        file_path=target.file_path,
                        line_start=target.line_start,
                        line_end=target.line_end,
                        source=target.source,
                        distance=node_depth + 1,
                        signature=target.signature,
                        docstring=target.docstring,
                    )
                    nodes[target.key] = target
                    if target.source != "external":
                        queue.append((target, node_depth + 1))
                elif target.source != "external" and existing.distance > node_depth + 1:
                    # Re-queue at the shorter distance so expansion stays BFS.
                    nodes[target.key] = GraphNode(
                        key=existing.key,
                        fqn=existing.fqn,
                        name=existing.name,
                        kind=existing.kind,
                        file_path=existing.file_path,
                        line_start=existing.line_start,
                        line_end=existing.line_end,
                        source=existing.source,
                        distance=node_depth + 1,
                        signature=existing.signature,
                        docstring=existing.docstring,
                    )

        ordered_nodes = self._order_nodes(nodes.values(), seed_keys={n.key for n in seed_nodes})
        ordered_edges = self._order_edges(edges, nodes)
        answer = GraphAnswer(
            question=question,
            seeds=seed_nodes,
            nodes=ordered_nodes,
            edges=ordered_edges,
            truncated=truncated,
            stats={
                "depth": depth,
                "max_nodes": max_nodes,
                "direction": direction,
                "edge_types": sorted(active_types),
                "visited": len(nodes),
                "returned": len(ordered_nodes),
                "collapsed_externals": collapsed_externals,
                "elapsed_ms": 0.0,
            },
        )
        self._trim_to_budget(answer, token_budget)
        answer.stats["elapsed_ms"] = round((time.monotonic() - start) * 1000, 1)
        return answer

    def _select_seeds(self, question: str, explicit: list[str] | None) -> list[GraphNode]:
        """Resolve *explicit* seeds or derive up to three from hybrid search.

        Seeds always come from the search hits first: the top hit seeds the
        traversal, per-term coverage adds a hit for each uncovered query term,
        and the remaining top hits fill the seed set. When a reranker is wired
        in, the hits are reranked first so the seeds match the ranking the
        search surface shows. Every seed carries a ``reason`` describing why it
        was chosen.
        """
        if explicit:
            resolved: list[GraphNode] = []
            for reference in explicit:
                node = self._resolve_seed_node(reference)
                if node is not None:
                    resolved.append(
                        replace(
                            node,
                            reason=(f"explicit seed {reference!r} resolved from the symbol index"),
                        )
                    )
            return resolved[:3]

        self._ensure_search_is_warm()
        try:
            envelope = self._search.search(
                question,
                limit=8,
                content="code_focused",
                include_tests=False,
            )
        except Exception:
            return []
        results = envelope.get("results") or []
        if self._reranker is not None and results:
            with contextlib.suppress(Exception):
                results = self._reranker.rerank(results, query=question)
        mapped: list[tuple[int, dict[str, Any], GraphNode]] = []
        for rank, result in enumerate(results, start=1):
            node = self._map_chunk_to_symbol(result)
            if node is not None:
                mapped.append((rank, result, node))
        if not mapped:
            # Lexical fallback: when the ranker finds nothing (a short
            # imperative question on a tiny index), resolve the identifiers
            # named in the question itself.
            fallback_seeds: list[GraphNode] = []
            for identifier in _candidate_identifiers(question):
                envelope = self._symbols.resolve_name(identifier)
                symbol = envelope.get("symbol")
                if symbol is None:
                    continue
                node = replace(
                    self._node_from_symbol(symbol),
                    reason=(
                        f"identifier {identifier!r} named in the query "
                        "resolved from the symbol index"
                    ),
                )
                if all(node.key != existing.key for existing in fallback_seeds):
                    fallback_seeds.append(node)
                if len(fallback_seeds) >= 3:
                    break
            return fallback_seeds

        first_rank, first_result, first_node = mapped[0]
        min_score = float(first_result.get("score") or 0.0) * 0.25
        chosen: list[GraphNode] = [
            replace(first_node, reason=self._seed_reason(first_rank, first_result))
        ]
        chosen_ids = {chosen[0].key}

        # Per-term guarantee: make sure one common identifier cannot starve
        # the other query terms by adding a seed covering each uncovered term.
        query_terms = _query_terms(question)
        covered = _symbol_terms(first_node.fqn, first_node.name)
        for term in sorted(query_terms - covered):
            for rank, result, node in mapped:
                if node.key in chosen_ids:
                    continue
                if float(result.get("score") or 0.0) < min_score:
                    continue
                node_terms = _symbol_terms(node.fqn, node.name)
                if term in node_terms:
                    reason = f"hybrid search hit #{rank} covers query term {term!r}"
                    chosen.append(replace(node, reason=reason))
                    chosen_ids.add(node.key)
                    covered |= node_terms
                    break
            if len(chosen) >= 3:
                break

        for rank, result, node in mapped:
            if len(chosen) >= 3:
                break
            if node.key in chosen_ids:
                continue
            if float(result.get("score") or 0.0) < min_score:
                continue
            chosen.append(replace(node, reason=self._seed_reason(rank, result)))
            chosen_ids.add(node.key)
        return chosen

    @staticmethod
    def _seed_reason(rank: int, result: dict[str, Any]) -> str:
        """Return the human-readable provenance for a hybrid-search seed."""
        score = float(result.get("score") or 0.0)
        return f"hybrid search hit #{rank} (score {score:.3f})"

    def _ensure_search_is_warm(self) -> None:
        """Wait a bounded interval for the embedding model before seeding.

        A cold model silently drops the vector arm, so the same question would
        seed from a lexical-only ranking and could bury the symbol it names.
        The daemon and MCP apply the same bounded wait before ranking; doing it
        here keeps every surface seeding from the same fused order. A warm
        model returns immediately.
        """
        generator = getattr(self._search, "_embedding_generator", None)
        wait_warm = getattr(generator, "wait_warm", None)
        begin_warmup = getattr(generator, "begin_warmup", None)
        if not callable(wait_warm) or not callable(begin_warmup):
            return
        timeout = float(getattr(self._settings, "warmup_wait_s", 0.0) or 0.0)
        if timeout <= 0:
            return
        with contextlib.suppress(Exception):
            begin_warmup()
            wait_warm(timeout)

    def _resolve_seed_node(self, reference: str) -> GraphNode | None:
        """Resolve an explicit seed reference to a graph node."""
        envelope = self._symbols.resolve_name(reference)
        symbol = envelope.get("symbol")
        if symbol is None:
            return None
        return self._node_from_symbol(symbol)

    def _map_chunk_to_symbol(self, result: dict[str, Any]) -> GraphNode | None:
        """Map a search-result chunk to its most specific enclosing symbol."""
        fqn = result.get("fqn") or ""
        file_path = result.get("file_path") or ""
        line_start = result.get("line_start")
        with self._db.connect() as conn:
            if fqn:
                row = conn.execute(
                    "SELECT * FROM symbols WHERE fqn = ? LIMIT 1;", (fqn,)
                ).fetchone()
                if row is not None:
                    return self._node_from_symbol(dict(row))
            if file_path and line_start is not None:
                row = conn.execute(
                    "SELECT * FROM symbols WHERE file_path = ? "
                    "AND line_start <= ? AND line_end >= ? "
                    "ORDER BY (line_end - line_start) ASC, line_start ASC LIMIT 1;",
                    (file_path, line_start, line_start),
                ).fetchone()
                if row is not None:
                    return self._node_from_symbol(dict(row))
        if fqn:
            envelope = self._symbols.resolve_name(fqn)
            symbol = envelope.get("symbol")
            if symbol is not None:
                return self._node_from_symbol(symbol)
        if file_path:
            # Resource chunks (XML mapper, SQL, config) often have no symbol
            # FQN. Their filename stem is the conventional companion type, so
            # an ``ArticleFavoriteMapper.xml`` hit can still seed the graph.
            stem = Path(file_path).stem
            if stem:
                envelope = self._symbols.resolve_name(stem)
                symbol = envelope.get("symbol")
                if symbol is not None:
                    return self._node_from_symbol(symbol)
        return None

    @staticmethod
    def _node_from_symbol(symbol: dict[str, Any]) -> GraphNode:
        """Shape a symbol row into a graph node."""
        symbol_id = symbol.get("id")
        return GraphNode(
            key=str(symbol.get("fqn")),
            fqn=str(symbol.get("fqn")),
            name=str(symbol.get("name") or ""),
            kind=str(symbol.get("kind") or "symbol"),
            file_path=symbol.get("file_path"),
            line_start=symbol.get("line_start"),
            line_end=symbol.get("line_end"),
            source="symbol",
            signature=symbol.get("signature"),
            docstring=symbol.get("docstring"),
            symbol_id=int(symbol_id) if symbol_id is not None else None,
        )

    @staticmethod
    def _node_from_cached(symbol: CachedSymbol, distance: int = 0) -> GraphNode:
        """Shape a cached directory entry into a graph node."""
        return GraphNode(
            key=symbol.fqn,
            fqn=symbol.fqn,
            name=symbol.name,
            kind=symbol.kind,
            file_path=symbol.file_path,
            line_start=symbol.line_start,
            line_end=symbol.line_end,
            source="symbol",
            distance=distance,
            signature=symbol.conventional_fqn,
            docstring=symbol.docstring,
            symbol_id=symbol.id,
        )

    def _snapshot(self) -> GraphSnapshot | None:
        """Return the current generation's adjacency snapshot, if usable."""
        return adjacency_snapshot(self._db, self._settings)

    def _fetch_outgoing(
        self, node: GraphNode, edge_types: set[str], *, direction: str = "both"
    ) -> tuple[list[tuple[GraphEdge, GraphNode]], bool]:
        """Return one hop of neighbours and whether the fan-out was capped.

        Args:
            node: The node being expanded.
            edge_types: Edge types to traverse.
            direction: ``both``, ``inbound``, or ``outbound``. Containment is
                structural and only expands in the outbound/both direction.

        Returns:
            ``(neighbours, truncated)`` where ``truncated`` is ``True`` when
            more edges were available than the fan-out cap (including an
            over-cap containment list).
        """
        outgoing: list[tuple[GraphEdge, GraphNode]] = []
        truncated = False
        if node.source == "symbol" and node.line_start is not None:
            with self._db.connect() as conn:
                symbol_row = conn.execute(
                    "SELECT id FROM symbols WHERE fqn = ? LIMIT 1;", (node.fqn,)
                ).fetchone()
            if symbol_row is not None:
                if direction in {"outbound", "both"}:
                    outgoing.extend(
                        self._fetch_symbol_edges(
                            node.key, int(symbol_row["id"]), edge_types, direction="out"
                        )
                    )
                # A neighbourhood is more useful than a one-way slice for
                # "how does X flow" questions: callers/importers are as
                # relevant as callees. An explicit direction narrows the walk
                # to the requested side only.
                if direction in {"inbound", "both"}:
                    outgoing.extend(
                        self._fetch_symbol_edges(
                            node.key, int(symbol_row["id"]), edge_types, direction="in"
                        )
                    )

        # Containment is structural (not a graph_edges CHECK kind): it connects
        # a type/file node to the declarations it owns so a class seed can
        # reach its methods and a module seed can reach its top-level symbols.
        if direction in {"outbound", "both"}:
            contained, containment_truncated = self._fetch_contained(node)
            outgoing.extend(contained)
            truncated = truncated or containment_truncated

        if "IMPORTS" in edge_types and node.file_path:
            relative = self._relative_path(node.file_path)
            related: list[tuple[dict[str, Any], str]] = []
            if direction in {"outbound", "both"}:
                related.extend(
                    (item, "forward") for item in self._modules.get_imports(relative, max_depth=1)
                )
            if direction in {"inbound", "both"}:
                related.extend(
                    (item, "reverse") for item in self._modules.get_importers(relative, max_depth=1)
                )
            seen_paths: set[str] = set()
            for related_file, traversal in related:
                target_path = related_file["path"]
                if target_path in seen_paths:
                    continue
                seen_paths.add(target_path)
                target_node = GraphNode(
                    key=f"file:{target_path}",
                    fqn=target_path,
                    name=target_path.rsplit("/", 1)[-1],
                    kind="file",
                    file_path=target_path,
                    line_start=None,
                    line_end=None,
                    source="file",
                )
                outgoing.append(
                    (
                        GraphEdge(
                            source=node.key,
                            target=target_node.key,
                            relation="IMPORTS",
                            confidence="EXTRACTED",
                            direction=traversal,
                            target_raw=target_path,
                        ),
                        target_node,
                    )
                )
        if len(outgoing) > _MAX_FANOUT:
            truncated = True
            outgoing = outgoing[:_MAX_FANOUT]
        return outgoing, truncated

    def _fetch_contained(self, node: GraphNode) -> tuple[list[tuple[GraphEdge, GraphNode]], bool]:
        """Return synthetic ``CONTAINS`` edges for a type or file node.

        The boolean result reports whether the declaration list exceeded the
        containment cap. ``LIMIT cap + 1`` distinguishes "exactly cap" from
        "more than cap" without an extra count query.
        """
        limit = _MAX_FANOUT + 1
        with self._db.connect() as conn:
            if node.source == "symbol":
                rows = conn.execute(
                    "SELECT child.* FROM symbols child "
                    "JOIN symbols parent ON child.parent_symbol_id = parent.id "
                    "WHERE parent.fqn = ? ORDER BY child.line_start, child.id LIMIT ?;",
                    (node.fqn, limit),
                ).fetchall()
            elif node.source == "file" and node.file_path:
                rows = conn.execute(
                    "SELECT * FROM symbols WHERE file_path = ? "
                    "AND parent_symbol_id IS NULL ORDER BY line_start, id LIMIT ?;",
                    (node.file_path, limit),
                ).fetchall()
            else:
                rows = []
        truncated = len(rows) > _MAX_FANOUT
        result: list[tuple[GraphEdge, GraphNode]] = []
        for row in rows[:_MAX_FANOUT]:
            child = self._node_from_symbol(dict(row))
            result.append(
                (
                    GraphEdge(
                        source=node.key,
                        target=child.key,
                        relation="CONTAINS",
                        confidence="EXTRACTED",
                    ),
                    child,
                )
            )
        return result, truncated

    def _fetch_symbol_edges(
        self,
        subject_key: str,
        symbol_id: int,
        edge_types: set[str],
        direction: str,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[GraphEdge, GraphNode]]:
        """Return one hop of symbol edges in the requested direction.

        ``GraphEdge.source``/``target`` always describe the real stored
        direction (source symbol → target symbol); ``direction`` records
        whether the edge was traversed away from (``forward``) or towards
        (``reverse``) the queried subject.

        Args:
            subject_key: Graph-answer key of the queried subject.
            symbol_id: Stored symbol id of the queried subject.
            edge_types: Edge types to include.
            direction: ``out`` for outgoing, ``in`` for incoming.
            conn: Optional reader connection to reuse. Batch callers (impact)
                pass one connection instead of opening one per visited node.
        """
        if not edge_types:
            return []
        placeholders = ",".join("?" for _ in edge_types)
        if direction == "out":
            sql = (
                "SELECT e.edge_type, e.resolution_tier, e.resolved, e.target_raw, "
                "e.source_range, s.id AS other_id, s.fqn, s.name, s.kind, "
                "s.file_path, s.line_start, s.line_end, s.conventional_fqn, s.docstring "
                "FROM graph_edges e LEFT JOIN symbols s ON s.id = e.target_symbol_id "
                f"WHERE e.source_symbol_id = ? AND e.edge_type IN ({placeholders}) "
                "ORDER BY e.edge_type, s.fqn, e.target_raw;"
            )
            params: list[Any] = [symbol_id, *sorted(edge_types)]
        else:
            sql = (
                "SELECT e.edge_type, e.resolution_tier, e.resolved, e.target_raw, "
                "e.source_range, s.id AS other_id, s.fqn, s.name, s.kind, "
                "s.file_path, s.line_start, s.line_end, s.conventional_fqn, s.docstring "
                "FROM graph_edges e JOIN symbols s ON s.id = e.source_symbol_id "
                f"WHERE e.target_symbol_id = ? AND e.edge_type IN ({placeholders}) "
                "ORDER BY e.edge_type, s.fqn;"
            )
            params = [symbol_id, *sorted(edge_types)]
        if conn is not None:
            rows = conn.execute(sql, params).fetchall()
        else:
            with self._db.connect() as owned:
                rows = owned.execute(sql, params).fetchall()
        result: list[tuple[GraphEdge, GraphNode]] = []
        for row in rows:
            resolved = bool(row["resolved"])
            confidence = resolve_confidence(row["resolution_tier"], resolved)
            if resolved and row["fqn"]:
                target = GraphNode(
                    key=str(row["fqn"]),
                    fqn=str(row["fqn"]),
                    name=str(row["name"] or ""),
                    kind=str(row["kind"] or "symbol"),
                    file_path=row["file_path"],
                    line_start=row["line_start"],
                    line_end=row["line_end"],
                    source="symbol",
                    signature=row["conventional_fqn"],
                    docstring=row["docstring"],
                    symbol_id=int(row["other_id"]),
                )
                target_key = target.key
            else:
                raw = str(row["target_raw"] or "<unresolved>")
                target_key = f"external:{raw}"
                target = GraphNode(
                    key=target_key,
                    fqn=raw,
                    name=raw,
                    kind="external",
                    file_path=None,
                    line_start=None,
                    line_end=None,
                    source="external",
                )
            if direction == "out":
                edge_source, edge_target = subject_key, target_key
            else:
                edge_source, edge_target = target_key, subject_key
            result.append(
                (
                    GraphEdge(
                        source=edge_source,
                        target=edge_target,
                        relation=str(row["edge_type"]),
                        confidence=confidence,
                        direction="forward" if direction == "out" else "reverse",
                        resolution_tier=row["resolution_tier"],
                        target_raw=row["target_raw"],
                        source_range=row["source_range"],
                    ),
                    target,
                )
            )
        return result

    # ------------------------------------------------------------------
    # Shortest path
    # ------------------------------------------------------------------
    def _resolve_path_endpoint(self, reference: str) -> dict[str, Any]:
        """Resolve a path endpoint, preferring a unique type declaration.

        A bare class name can collide with its constructor (both are stored
        under the class name). Callers asking for a path between classes mean
        the type, so when the only ambiguity is constructor-vs-type pick the
        type rather than refusing the traversal.
        """
        envelope = self._symbols.resolve_name(reference)
        if envelope.get("kind") != "ambiguous":
            return envelope
        type_candidates = [
            candidate
            for candidate in envelope.get("candidates") or []
            if candidate.get("kind") in _TYPE_KINDS
        ]
        if len(type_candidates) != 1:
            return envelope
        resolved = self._symbols.resolve_name(str(type_candidates[0]["fqn"]))
        return resolved if resolved.get("symbol") is not None else envelope

    def shortest_path(
        self,
        source: str,
        target: str,
        *,
        undirected: bool = False,
        max_hops: int = _MAX_PATH_HOPS,
        edge_types: set[str] | None = None,
    ) -> PathAnswer:
        """Return a shortest path between two symbols.

        The endpoints are resolved through the shared ambiguity policy: an
        ambiguous reference is refused with its ranked candidates instead of
        being guessed. The traversal is a deterministic BFS bounded by
        *max_hops* and a global node cap.
        """
        start = time.monotonic()
        source_env = self._resolve_path_endpoint(source)
        target_env = self._resolve_path_endpoint(target)
        for env, label in ((source_env, "source"), (target_env, "target")):
            if env.get("kind") == "ambiguous":
                return PathAnswer(
                    outcome="ambiguous",
                    candidates=env.get("candidates") or [],
                    undirected=undirected,
                    explanation=f"ambiguous {label}: retry with a qualified FQN",
                    stats={"elapsed_ms": round((time.monotonic() - start) * 1000, 1)},
                )
            if env.get("symbol") is None:
                return PathAnswer(
                    outcome="not_found",
                    candidates=env.get("candidates") or [],
                    undirected=undirected,
                    explanation=f"{label} not found: {source if label == 'source' else target}",
                    stats={"elapsed_ms": round((time.monotonic() - start) * 1000, 1)},
                )
        source_sym = source_env["symbol"]
        target_sym = target_env["symbol"]
        source_node = self._node_from_symbol(source_sym)
        target_node = self._node_from_symbol(target_sym)
        if source_sym["id"] == target_sym["id"]:
            return PathAnswer(
                source=source_node,
                target=target_node,
                undirected=undirected,
                outcome="trivial",
                explanation="source and target are the same symbol",
                stats={"elapsed_ms": round((time.monotonic() - start) * 1000, 1)},
            )

        max_hops = max(1, min(max_hops, _MAX_PATH_HOPS))
        active_types = (edge_types or set(DEFAULT_EDGE_TYPES)) & VALID_EDGE_TYPES
        target_id = int(target_sym["id"])
        snapshot = self._snapshot()
        if snapshot is not None:
            parent = self._cached_path_parents(
                snapshot,
                int(source_sym["id"]),
                target_id,
                active_types,
                undirected=undirected,
                max_hops=max_hops,
            )
        else:
            parent = self._sql_path_parents(
                int(source_sym["id"]),
                target_id,
                active_types,
                undirected=undirected,
                max_hops=max_hops,
            )
        found = target_id in parent
        if not found:
            explanation = f"no path within {max_hops} hops; " + (
                "retry with --undirected to traverse callers as well"
                if not undirected
                else "no connecting edges in either direction (unresolved references may hide it)"
            )
            return PathAnswer(
                source=source_node,
                target=target_node,
                undirected=undirected,
                outcome="no_path",
                explanation=explanation,
                stats={
                    "visited": len(parent),
                    "max_hops": max_hops,
                    "adjacency": "cache" if snapshot is not None else "sql",
                    "elapsed_ms": round((time.monotonic() - start) * 1000, 1),
                },
            )

        hops: list[GraphEdge] = []
        cursor = target_id
        while cursor != int(source_sym["id"]):
            previous, hop_edge = parent[cursor]
            if hop_edge is None or previous is None:
                break
            hops.append(hop_edge)
            cursor = previous
        hops.reverse()
        return PathAnswer(
            source=source_node,
            target=target_node,
            hops=hops,
            undirected=undirected,
            outcome="resolved",
            stats={
                "visited": len(parent),
                "hop_count": len(hops),
                "max_hops": max_hops,
                "adjacency": "cache" if snapshot is not None else "sql",
                "elapsed_ms": round((time.monotonic() - start) * 1000, 1),
            },
        )

    def _cached_path_parents(
        self,
        snapshot: GraphSnapshot,
        source_id: int,
        target_id: int,
        edge_types: set[str],
        *,
        undirected: bool,
        max_hops: int,
    ) -> dict[int, tuple[int | None, GraphEdge | None]]:
        """BFS over the in-memory adjacency up to *max_hops*.

        The parent map is the public path reconstruction contract: each
        visited symbol points at the node and edge it was first reached
        through. Neighbours are sorted with the same confidence/type/id key as
        the SQL fallback, so both paths return the same shortest path.
        """
        type_codes = snapshot.type_codes(edge_types)
        parent: dict[int, tuple[int | None, GraphEdge | None]] = {source_id: (None, None)}
        depth: dict[int, int] = {source_id: 0}
        queue: deque[int] = deque([source_id])
        while queue and len(parent) < _MAX_PATH_NODES:
            current = queue.popleft()
            if current == target_id:
                break
            current_depth = depth[current]
            if current_depth >= max_hops:
                continue
            for neighbor, edge in self._cached_neighbors(
                snapshot, current, type_codes, undirected=undirected
            ):
                if neighbor in parent:
                    continue
                parent[neighbor] = (current, edge)
                depth[neighbor] = current_depth + 1
                queue.append(neighbor)
        return parent

    def _cached_neighbors(
        self,
        snapshot: GraphSnapshot,
        current: int,
        type_codes: frozenset[int],
        *,
        undirected: bool,
    ) -> list[tuple[int, GraphEdge]]:
        """Return one deterministic hop of neighbours from the snapshot.

        Outgoing edges are always traversed. With *undirected*, incoming edges
        are traversed as well. Structural containment is always available in
        both directions because a class owns its members rather than calling
        them.
        """
        current_symbol = snapshot.symbol(current)
        if current_symbol is None:
            return []
        current_fqn = current_symbol.fqn
        neighbors: list[tuple[int, GraphEdge]] = []
        for neighbor in snapshot.iter_out(current, type_codes):
            other = snapshot.symbol(neighbor.symbol_id)
            if other is None:
                continue
            neighbors.append(
                (
                    neighbor.symbol_id,
                    GraphEdge(
                        source=current_fqn,
                        target=other.fqn,
                        relation=neighbor.edge_type,
                        confidence=resolve_confidence(neighbor.resolution_tier, True),
                        direction="forward",
                        resolution_tier=neighbor.resolution_tier,
                    ),
                )
            )
        if undirected:
            for neighbor in snapshot.iter_in(current, type_codes):
                other = snapshot.symbol(neighbor.symbol_id)
                if other is None:
                    continue
                neighbors.append(
                    (
                        neighbor.symbol_id,
                        GraphEdge(
                            source=other.fqn,
                            target=current_fqn,
                            relation=neighbor.edge_type,
                            confidence=resolve_confidence(neighbor.resolution_tier, True),
                            direction="reverse",
                            resolution_tier=neighbor.resolution_tier,
                        ),
                    )
                )
        for child_id in snapshot.children(current):
            child = snapshot.symbol(child_id)
            if child is None:
                continue
            neighbors.append(
                (
                    child_id,
                    GraphEdge(
                        source=current_fqn,
                        target=child.fqn,
                        relation="CONTAINS",
                        confidence="EXTRACTED",
                        direction="forward",
                    ),
                )
            )
        parent_id = snapshot.parent(current)
        if parent_id is not None:
            parent_symbol = snapshot.symbol(parent_id)
            if parent_symbol is not None:
                neighbors.append(
                    (
                        parent_id,
                        GraphEdge(
                            source=parent_symbol.fqn,
                            target=current_fqn,
                            relation="CONTAINS",
                            confidence="EXTRACTED",
                            direction="reverse",
                        ),
                    )
                )
        neighbors.sort(
            key=lambda pair: (
                CONFIDENCE_ORDER[pair[1].confidence],
                pair[1].relation,
                pair[0],
            )
        )
        return neighbors

    def _sql_path_parents(
        self,
        source_id: int,
        target_id: int,
        edge_types: set[str],
        *,
        undirected: bool,
        max_hops: int,
    ) -> dict[int, tuple[int | None, GraphEdge | None]]:
        """BFS over the SQL adjacency fallback used when no cache is available."""
        adjacency = self._build_adjacency(edge_types, source_id, undirected)
        parent: dict[int, tuple[int | None, GraphEdge | None]] = {source_id: (None, None)}
        depth: dict[int, int] = {source_id: 0}
        queue: deque[int] = deque([source_id])
        while queue and len(parent) < _MAX_PATH_NODES:
            current = queue.popleft()
            if current == target_id:
                break
            current_depth = depth[current]
            if current_depth >= max_hops:
                continue
            for neighbor, edge in adjacency.get(current, []):
                if neighbor in parent:
                    continue
                parent[neighbor] = (current, edge)
                depth[neighbor] = current_depth + 1
                queue.append(neighbor)
        return parent

    def _build_adjacency(
        self, edge_types: set[str], source_id: int, undirected: bool
    ) -> dict[int, list[tuple[int, GraphEdge]]]:
        """Build a bounded adjacency map reachable from *source_id*.

        Only the source's connected component is materialised (bounded by the
        traversal's node cap), keeping the path query cheap on large indexes.
        """
        adjacency: dict[int, list[tuple[int, GraphEdge]]] = {}
        frontier: deque[int] = deque([source_id])
        visited: set[int] = {source_id}
        placeholders = ",".join("?" for _ in edge_types)
        with self._db.connect() as conn:
            while frontier and len(visited) < _MAX_PATH_NODES:
                current = frontier.popleft()
                current_row = conn.execute(
                    "SELECT fqn FROM symbols WHERE id = ?;", (current,)
                ).fetchone()
                if current_row is not None:
                    self._append_containment(
                        adjacency, frontier, visited, conn, current, str(current_row["fqn"])
                    )
                out_rows = conn.execute(
                    "SELECT e.source_symbol_id, e.target_symbol_id, e.edge_type, "
                    "e.resolution_tier, e.resolved, e.target_raw, "
                    "s1.fqn AS source_fqn, s2.fqn AS target_fqn "
                    "FROM graph_edges e INDEXED BY idx_edges_source_type "
                    "JOIN symbols s1 ON s1.id = e.source_symbol_id "
                    "JOIN symbols s2 ON s2.id = e.target_symbol_id "
                    f"WHERE e.edge_type IN ({placeholders}) "
                    "AND e.resolved = 1 AND e.source_symbol_id = ?;",
                    [*sorted(edge_types), current],
                ).fetchall()
                for row in out_rows:
                    tgt = row["target_symbol_id"]
                    if tgt is None or not bool(row["resolved"]):
                        continue
                    tgt = int(tgt)
                    confidence = resolve_confidence(row["resolution_tier"], True)
                    adjacency.setdefault(current, []).append(
                        (
                            tgt,
                            GraphEdge(
                                source=str(row["source_fqn"]),
                                target=str(row["target_fqn"]),
                                relation=str(row["edge_type"]),
                                confidence=confidence,
                                direction="forward",
                                resolution_tier=row["resolution_tier"],
                            ),
                        )
                    )
                    if tgt not in visited:
                        visited.add(tgt)
                        frontier.append(tgt)
                if undirected:
                    in_rows = conn.execute(
                        "SELECT e.source_symbol_id, e.target_symbol_id, e.edge_type, "
                        "e.resolution_tier, e.resolved, e.target_raw, "
                        "s1.fqn AS source_fqn, s2.fqn AS target_fqn "
                        "FROM graph_edges e INDEXED BY idx_edges_target_type "
                        "JOIN symbols s1 ON s1.id = e.source_symbol_id "
                        "JOIN symbols s2 ON s2.id = e.target_symbol_id "
                        f"WHERE e.edge_type IN ({placeholders}) "
                        "AND e.resolved = 1 "
                        "AND e.target_symbol_id = ? AND e.source_symbol_id != ?;",
                        [*sorted(edge_types), current, current],
                    ).fetchall()
                    for row in in_rows:
                        src = int(row["source_symbol_id"])
                        confidence = resolve_confidence(row["resolution_tier"], True)
                        adjacency.setdefault(current, []).append(
                            (
                                src,
                                GraphEdge(
                                    source=str(row["source_fqn"]),
                                    target=str(row["target_fqn"]),
                                    relation=str(row["edge_type"]),
                                    confidence=confidence,
                                    direction="reverse",
                                    resolution_tier=row["resolution_tier"],
                                ),
                            )
                        )
                        if src not in visited:
                            visited.add(src)
                            frontier.append(src)
        # Sort each neighbour list for deterministic path selection.
        for neighbors in adjacency.values():
            neighbors.sort(
                key=lambda pair: (
                    CONFIDENCE_ORDER[pair[1].confidence],
                    pair[1].relation,
                    pair[0],
                )
            )
        return adjacency

    def _append_containment(
        self,
        adjacency: dict[int, list[tuple[int, GraphEdge]]],
        frontier: deque[int],
        visited: set[int],
        conn: Any,
        symbol_id: int,
        symbol_fqn: str,
    ) -> None:
        """Add structural declaration containment to the path adjacency.

        Class nodes own their methods and fields through containment rather
        than call edges, so a class-to-class path has to descend into members
        and ascend back out. Both directions are structural and therefore
        available regardless of the requested edge types.
        """
        children = conn.execute(
            "SELECT id, fqn FROM symbols WHERE parent_symbol_id = ? "
            "ORDER BY line_start, id LIMIT ?;",
            (symbol_id, _MAX_FANOUT),
        ).fetchall()
        for child in children:
            child_id = int(child["id"])
            adjacency.setdefault(symbol_id, []).append(
                (
                    child_id,
                    GraphEdge(
                        source=symbol_fqn,
                        target=str(child["fqn"]),
                        relation="CONTAINS",
                        confidence="EXTRACTED",
                        direction="forward",
                    ),
                )
            )
            if child_id not in visited:
                visited.add(child_id)
                frontier.append(child_id)
        parent = conn.execute(
            "SELECT p.id, p.fqn FROM symbols p JOIN symbols s ON s.parent_symbol_id = p.id "
            "WHERE s.id = ?;",
            (symbol_id,),
        ).fetchone()
        if parent is not None:
            parent_id = int(parent["id"])
            adjacency.setdefault(symbol_id, []).append(
                (
                    parent_id,
                    GraphEdge(
                        source=str(parent["fqn"]),
                        target=symbol_fqn,
                        relation="CONTAINS",
                        confidence="EXTRACTED",
                        direction="reverse",
                    ),
                )
            )
            if parent_id not in visited:
                visited.add(parent_id)
                frontier.append(parent_id)

    # ------------------------------------------------------------------
    # Explain
    # ------------------------------------------------------------------
    def explain(
        self,
        symbol: str,
        *,
        depth: int = 1,
        relations: set[str] | None = None,
    ) -> ExplainAnswer:
        """Return an ego graph and metadata for *symbol*."""
        start = time.monotonic()
        envelope = self._symbols.resolve_name(symbol)
        if envelope.get("kind") == "ambiguous":
            return ExplainAnswer(
                outcome="ambiguous",
                candidates=envelope.get("candidates") or [],
                stats={"elapsed_ms": round((time.monotonic() - start) * 1000, 1)},
            )
        row = envelope.get("symbol")
        if row is None:
            return ExplainAnswer(
                outcome="not_found",
                candidates=envelope.get("candidates") or [],
                stats={"elapsed_ms": round((time.monotonic() - start) * 1000, 1)},
            )
        node = self._node_from_symbol(row)
        active = (relations or set(DEFAULT_EDGE_TYPES)) & VALID_EDGE_TYPES
        nodes: dict[str, GraphNode] = {node.key: node}
        edges: list[GraphEdge] = []
        seen: set[tuple[str, str, str, str]] = set()
        truncated = False

        for node_depth in range(max(0, min(depth, _MAX_DEPTH))):
            layer = [
                n for n in nodes.values() if n.distance == node_depth and n.source != "external"
            ]
            for current in layer:
                if current.source == "symbol" and current.line_start is not None:
                    with self._db.connect() as conn:
                        current_row = conn.execute(
                            "SELECT id FROM symbols WHERE fqn = ? LIMIT 1;", (current.fqn,)
                        ).fetchone()
                    if current_row is not None:
                        current_id = int(current_row["id"])
                        outgoing_edges = self._fetch_symbol_edges(
                            current.key, current_id, active, "out"
                        )
                        truncated = truncated or len(outgoing_edges) > _MAX_FANOUT
                        self._append_edges(
                            nodes,
                            edges,
                            seen,
                            outgoing_edges[:_MAX_FANOUT],
                            node_depth,
                        )
                        incoming_edges = self._fetch_symbol_edges(
                            current.key, current_id, active, "in"
                        )
                        truncated = truncated or len(incoming_edges) > _MAX_FANOUT
                        self._append_edges(
                            nodes,
                            edges,
                            seen,
                            incoming_edges[:_MAX_FANOUT],
                            node_depth,
                        )
                contained, containment_truncated = self._fetch_contained(current)
                truncated = truncated or containment_truncated
                self._append_edges(
                    nodes,
                    edges,
                    seen,
                    contained,
                    node_depth,
                )
                if "IMPORTS" in active and current.file_path:
                    relative = self._relative_path(current.file_path)
                    for edge, target in self._module_edges_for(relative, current.key):
                        edge_key = (edge.source, edge.target, edge.relation, edge.confidence)
                        if edge_key in seen:
                            continue
                        seen.add(edge_key)
                        edges.append(edge)
                        nodes.setdefault(target.key, target)

        rationale = self._rationale.for_symbol(int(row["id"]))
        doc_links: list[dict[str, Any]] = []
        if row.get("file_path"):
            doc_links = self._doc_links.for_file(str(row["file_path"]), limit=5)
        return ExplainAnswer(
            symbol=node,
            nodes=self._order_nodes(nodes.values(), seed_keys={node.key}),
            edges=self._order_edges(edges, nodes),
            rationale=rationale,
            doc_links=doc_links,
            outcome="resolved",
            truncated=truncated,
            stats={
                "depth": depth,
                "incoming": sum(1 for e in edges if e.direction == "reverse"),
                "outgoing": sum(1 for e in edges if e.direction == "forward"),
                "elapsed_ms": round((time.monotonic() - start) * 1000, 1),
            },
        )

    def _append_edges(
        self,
        nodes: dict[str, GraphNode],
        edges: list[GraphEdge],
        seen: set[tuple[str, str, str, str]],
        fetched: list[tuple[GraphEdge, GraphNode]],
        depth: int,
    ) -> None:
        """Merge fetched edges/nodes into the ego graph at *depth*."""
        for edge, target in fetched:
            edge_key = (edge.source, edge.target, edge.relation, edge.confidence)
            if edge_key in seen:
                continue
            seen.add(edge_key)
            edges.append(edge)
            if target.key not in nodes:
                nodes[target.key] = GraphNode(
                    key=target.key,
                    fqn=target.fqn,
                    name=target.name,
                    kind=target.kind,
                    file_path=target.file_path,
                    line_start=target.line_start,
                    line_end=target.line_end,
                    source=target.source,
                    distance=depth + 1,
                    signature=target.signature,
                    docstring=target.docstring,
                )

    def _module_edges_for(
        self, relative_path: str, subject_key: str
    ) -> list[tuple[GraphEdge, GraphNode]]:
        """Return module imports and importers for *relative_path* as file nodes.

        *subject_key* is the queried symbol/file node; import edges originate at
        it and importer edges point back to it so no edge references an
        undeclared node.
        """
        result: list[tuple[GraphEdge, GraphNode]] = []
        for info in self._modules.get_imports(relative_path, max_depth=1):
            target_path = info["path"]
            node = GraphNode(
                key=f"file:{target_path}",
                fqn=target_path,
                name=target_path.rsplit("/", 1)[-1],
                kind="file",
                file_path=target_path,
                line_start=None,
                line_end=None,
                source="file",
            )
            result.append(
                (
                    GraphEdge(
                        source=subject_key,
                        target=node.key,
                        relation="IMPORTS",
                        confidence="EXTRACTED",
                        target_raw=target_path,
                    ),
                    node,
                )
            )
        for info in self._modules.get_importers(relative_path, max_depth=1):
            source_path = info["path"]
            node = GraphNode(
                key=f"file:{source_path}",
                fqn=source_path,
                name=source_path.rsplit("/", 1)[-1],
                kind="file",
                file_path=source_path,
                line_start=None,
                line_end=None,
                source="file",
            )
            result.append(
                (
                    GraphEdge(
                        source=node.key,
                        target=subject_key,
                        relation="IMPORTS",
                        confidence="EXTRACTED",
                        direction="reverse",
                        target_raw=relative_path,
                    ),
                    node,
                )
            )
        return result

    def _relative_path(self, file_path: str) -> str:
        """Return *file_path* relative to the indexed root, in POSIX form."""
        try:
            return Path(file_path).resolve().relative_to(self._index_root.resolve()).as_posix()
        except (ValueError, OSError):
            return Path(file_path).as_posix()

    # ------------------------------------------------------------------
    # Impact analysis
    # ------------------------------------------------------------------
    def impact(
        self,
        changed_paths: list[str],
        *,
        depth: int = 3,
        max_nodes: int = 200,
        direction: str = "inbound",
        edge_types: set[str] | None = None,
        include_imports: bool = True,
        fixpoint: bool = False,
        seed_filter: str = "all",
    ) -> ImpactAnswer:
        """Return symbols reached from *changed_paths* through the graph.

        The default is a reverse walk (callers and subtypes) capped at *depth*.
        ``direction=outbound`` answers "what does this change depend on";
        ``both`` widens the neighbourhood. ``fixpoint`` walks to closure
        instead of stopping at *depth*, still bounded by *max_nodes*.

        Args:
            changed_paths: Absolute or index-relative changed paths.
            depth: Maximum traversal depth (clipped to 4) unless *fixpoint*.
            max_nodes: Maximum returned nodes (clipped to 200).
            direction: ``inbound``, ``outbound``, or ``both``.
            edge_types: Symbol edge types to traverse (default ``CALLS`` and
                ``INHERITS``).
            include_imports: Also traverse file-level import edges.
            fixpoint: Walk to closure instead of stopping at *depth*.
            seed_filter: ``all`` seeds every symbol in the changed files;
                ``product`` drops symbols in test files.

        Returns:
            An :class:`ImpactAnswer` with the impacted symbols, files split
            into production/test, per-symbol risk labels, and traversal
            provenance.
        """
        depth = max(1, min(depth, _MAX_DEPTH))
        max_nodes = max(1, min(max_nodes, _MAX_NODES))
        if direction not in {"inbound", "outbound", "both"}:
            direction = "inbound"
        active_types = (edge_types or set(DEFAULT_EDGE_TYPES)) & VALID_EDGE_TYPES
        changed_stored: list[str] = []
        for path in changed_paths:
            resolved = self._resolve_changed_path(path)
            if resolved is not None:
                changed_stored.append(resolved)

        seed_nodes: dict[str, GraphNode] = {}
        for stored in changed_stored:
            for symbol in self._symbols.lookup_by_file(stored):
                if seed_filter == "product" and _is_test_file(str(symbol.get("file_path") or "")):
                    continue
                node = self._node_from_symbol(symbol)
                seed_nodes[node.key] = node
            if not include_imports:
                continue
            import_depth = 1 if fixpoint else depth
            for rel in self._relative_changed_paths(stored):
                related: list[dict[str, Any]] = []
                if direction in ("inbound", "both"):
                    related.extend(self._modules.get_importers(rel, max_depth=import_depth))
                if direction in ("outbound", "both"):
                    related.extend(self._modules.get_imports(rel, max_depth=import_depth))
                for related_file in related:
                    related_path = related_file["path"]
                    target = GraphNode(
                        key=f"file:{related_path}",
                        fqn=related_path,
                        name=related_path.rsplit("/", 1)[-1],
                        kind="file",
                        file_path=related_path,
                        line_start=None,
                        line_end=None,
                        source="file",
                        distance=int(related_file["depth"]),
                    )
                    seed_nodes.setdefault(target.key, target)

        impacted: dict[str, GraphNode] = dict(seed_nodes)
        parents: dict[str, dict[str, str]] = {}
        frontier: deque[GraphNode] = deque(seed_nodes.values())
        truncated = False
        snapshot = self._snapshot()
        type_codes = snapshot.type_codes(active_types) if snapshot is not None else frozenset()
        # One reader connection for the whole walk: opening a fresh connection
        # per visited node would turn a deep walk into a connection storm. A
        # warm snapshot answers the hop from memory instead of issuing even
        # that one query.
        with self._db.connect() as conn:
            while frontier:
                if len(impacted) >= max_nodes:
                    truncated = True
                    break
                node = frontier.popleft()
                if node.source != "symbol":
                    continue
                if not fixpoint and node.distance >= depth:
                    continue
                neighbor_edges: list[tuple[GraphEdge, GraphNode]] = []
                if snapshot is not None and node.symbol_id is not None:
                    neighbor_edges = self._cached_impact_neighbors(
                        snapshot, node, type_codes, direction
                    )
                else:
                    row = conn.execute(
                        "SELECT id FROM symbols WHERE fqn = ? LIMIT 1;", (node.fqn,)
                    ).fetchone()
                    if row is None:
                        continue
                    if direction in ("inbound", "both"):
                        neighbor_edges.extend(
                            self._fetch_symbol_edges(
                                node.key, int(row["id"]), active_types, "in", conn=conn
                            )
                        )
                    if direction in ("outbound", "both"):
                        neighbor_edges.extend(
                            self._fetch_symbol_edges(
                                node.key, int(row["id"]), active_types, "out", conn=conn
                            )
                        )
                seen_neighbors: set[str] = set()
                for edge, source_node in neighbor_edges:
                    if source_node.source == "external" or source_node.key in impacted:
                        continue
                    if source_node.key in seen_neighbors:
                        continue
                    seen_neighbors.add(source_node.key)
                    source_node = GraphNode(
                        key=source_node.key,
                        fqn=source_node.fqn,
                        name=source_node.name,
                        kind=source_node.kind,
                        file_path=source_node.file_path,
                        line_start=source_node.line_start,
                        line_end=source_node.line_end,
                        source=source_node.source,
                        distance=node.distance + 1,
                        signature=source_node.signature,
                        docstring=source_node.docstring,
                        symbol_id=source_node.symbol_id,
                    )
                    impacted[source_node.key] = source_node
                    parents[source_node.key] = {
                        "parent": node.key,
                        "relation": edge.relation,
                    }
                    if source_node.source == "symbol":
                        frontier.append(source_node)

            ordered = self._order_nodes(impacted.values(), seed_keys=set(seed_nodes))
            symbol_nodes = [n for n in ordered if n.source == "symbol"]
            fan_in = self._fan_in_counts(conn, symbol_nodes, active_types)
        file_nodes = {n.fqn for n in ordered if n.source == "file"}
        # Symbol paths are stored absolute while module-edge paths are
        # relative; normalise both spellings so each file appears once.
        distance_by_file: dict[str, int] = {}
        for node in ordered:
            if node.source == "file":
                path = node.fqn
            elif node.file_path:
                path = self._relative_path(node.file_path)
            else:
                continue
            distance_by_file[path] = min(distance_by_file.get(path, node.distance), node.distance)
        files = sorted(
            {self._relative_path(n.file_path) for n in symbol_nodes if n.file_path} | file_nodes,
            key=lambda path: (distance_by_file.get(path, _MAX_DEPTH), path),
        )
        test_files = [path for path in files if _is_test_file(path)]
        production_files = [path for path in files if not _is_test_file(path)]
        test_symbols = [n for n in symbol_nodes if n.file_path and _is_test_file(n.file_path)]
        test_keys = {node.key for node in test_symbols}
        production_symbols = [n for n in symbol_nodes if n.key not in test_keys]
        risks: dict[str, str] = {}
        for node in symbol_nodes:
            risks[node.fqn] = self._impact_risk(node, fan_in.get(node.fqn, 0))
        risk_summary = {
            level: sum(1 for value in risks.values() if value == level)
            for level in ("high", "medium", "low")
        }
        return ImpactAnswer(
            changed_paths=changed_stored,
            symbols=list(seed_nodes.values()),
            impacted=symbol_nodes,
            files=files,
            production_files=production_files,
            test_files=test_files,
            test_symbols=test_symbols,
            production_symbols=production_symbols,
            risks=risks,
            risk_summary=risk_summary,
            parents=parents,
            direction=direction,
            via=sorted(active_types),
            fixpoint=fixpoint,
            truncated=truncated,
            summary={
                "symbols": len(symbol_nodes),
                "files": len(files),
                "production_files": len(production_files),
                "test_files": len(test_files),
                "production_symbols": len(production_symbols),
                "test_symbols": len(test_symbols),
                "tests": len(test_symbols),
                "changed_files": len(changed_stored),
                "high_risk": risk_summary["high"],
                "medium_risk": risk_summary["medium"],
                "low_risk": risk_summary["low"],
                "adjacency": "cache" if snapshot is not None else "sql",
            },
        )

    def _cached_impact_neighbors(
        self,
        snapshot: GraphSnapshot,
        node: GraphNode,
        type_codes: frozenset[int],
        direction: str,
    ) -> list[tuple[GraphEdge, GraphNode]]:
        """Return one deterministic hop of impact neighbours from the cache.

        Neighbours are sorted by confidence, edge type, and FQN before the
        caller sees them, so the first parent recorded for a node is stable
        across runs even though the CSR stores edges in insertion order.
        """
        if node.symbol_id is None:
            return []
        neighbors: list[tuple[GraphEdge, GraphNode]] = []
        if direction in ("inbound", "both"):
            for neighbor in snapshot.iter_in(node.symbol_id, type_codes):
                other = snapshot.symbol(neighbor.symbol_id)
                if other is None:
                    continue
                neighbors.append(
                    (
                        GraphEdge(
                            source=other.fqn,
                            target=node.fqn,
                            relation=neighbor.edge_type,
                            confidence=resolve_confidence(neighbor.resolution_tier, True),
                            direction="reverse",
                            resolution_tier=neighbor.resolution_tier,
                        ),
                        self._node_from_cached(other, distance=node.distance + 1),
                    )
                )
        if direction in ("outbound", "both"):
            for neighbor in snapshot.iter_out(node.symbol_id, type_codes):
                other = snapshot.symbol(neighbor.symbol_id)
                if other is None:
                    continue
                neighbors.append(
                    (
                        GraphEdge(
                            source=node.fqn,
                            target=other.fqn,
                            relation=neighbor.edge_type,
                            confidence=resolve_confidence(neighbor.resolution_tier, True),
                            direction="forward",
                            resolution_tier=neighbor.resolution_tier,
                        ),
                        self._node_from_cached(other, distance=node.distance + 1),
                    )
                )
        neighbors.sort(
            key=lambda pair: (
                CONFIDENCE_ORDER[pair[0].confidence],
                pair[0].relation,
                pair[1].key,
            )
        )
        return neighbors

    @staticmethod
    def _fan_in_counts(
        conn: sqlite3.Connection,
        nodes: list[GraphNode],
        edge_types: set[str],
    ) -> dict[str, int]:
        """Return resolved incoming-edge counts for *nodes* in one query."""
        if not nodes or not edge_types:
            return {}
        placeholders = ",".join("?" for _ in nodes)
        type_placeholders = ",".join("?" for _ in edge_types)
        rows = conn.execute(
            "SELECT s.fqn, COUNT(*) AS n FROM graph_edges e "
            "JOIN symbols s ON s.id = e.target_symbol_id "
            f"WHERE e.resolved = 1 AND e.edge_type IN ({type_placeholders}) "
            f"AND s.fqn IN ({placeholders}) GROUP BY s.fqn;",
            [*sorted(edge_types), *(node.fqn for node in nodes)],
        ).fetchall()
        return {str(row["fqn"]): int(row["n"]) for row in rows}

    @staticmethod
    def _impact_risk(node: GraphNode, fan_in: int) -> str:
        """Classify an impacted symbol's risk from fan-in and its kind.

        This is a conservative heuristic, not a contract: a high fan-in symbol,
        a type boundary, or a non-test entry point is treated as high risk.
        """
        if node.file_path and _is_test_file(node.file_path):
            return "low"
        if node.kind in _TYPE_KINDS or fan_in >= 5:
            return "high"
        if fan_in >= 1:
            return "medium"
        return "low"

    def detect_changes(
        self,
        changed_paths: list[str] | None = None,
        *,
        since: str | None = None,
        base_branch: str | None = None,
        scope: str = "impact",
        direction: str = "inbound",
        depth: int = 3,
        fixpoint: bool = False,
        edge_types: set[str] | None = None,
        include_imports: bool = True,
        seed_filter: str = "all",
        max_nodes: int = 200,
    ) -> dict[str, Any]:
        """Resolve changed files (optionally from git) and report their blast radius.

        Args:
            changed_paths: Explicit changed paths.
            since: Git ref to diff against when no ``base_branch`` is given.
            base_branch: Git ref to diff against (takes precedence over *since*).
            scope: ``files`` returns the changed paths only; ``impact`` returns
                the full graph result; ``tests`` narrows it to test files and
                test symbols.
            direction: ``inbound``, ``outbound``, or ``both``.
            depth: Traversal depth (clipped to 4).
            fixpoint: Walk to closure instead of stopping at *depth*.
            edge_types: Symbol edge types to traverse.
            include_imports: Also traverse file-level import edges.
            seed_filter: ``all`` or ``product`` (drop test-file seeds).
            max_nodes: Maximum returned nodes (clipped to 200).

        Returns:
            A JSON-serialisable payload. Invalid scope/ref combinations return
            ``outcome: invalid_argument``; an empty change set returns
            ``outcome: no_changes``.
        """
        if scope not in {"files", "impact", "tests"}:
            return {
                "outcome": "invalid_argument",
                "error": f"unsupported scope: {scope}; use files, impact, or tests",
            }
        ref = base_branch or since
        changes = list(changed_paths or [])
        changed_source = "explicit"
        if ref:
            from code_search.engine.graph_surface import changed_files_since

            try:
                changes.extend(changed_files_since(self._index_root, ref))
            except RuntimeError as exc:
                return {"outcome": "invalid_argument", "error": str(exc)}
            changed_source = "git"
        deduped: list[str] = []
        for path in changes:
            if path not in deduped:
                deduped.append(path)

        with self._db.connect() as conn:
            generation_row = conn.execute(
                "SELECT value FROM index_metadata WHERE key = 'index_generation';"
            ).fetchone()
            generation = str(generation_row["value"]) if generation_row is not None else None
        if not deduped:
            return {
                "outcome": "no_changes",
                "scope": scope,
                "changed_source": changed_source,
                "since": since,
                "base_branch": base_branch,
                "changed_files": [],
                "summary": {"changed_files": 0},
                "index_generation": generation,
            }

        if scope == "files":
            relative_changes: list[str] = []
            for path in deduped:
                resolved = self._resolve_changed_path(path)
                relative_changes.append(
                    self._relative_path(resolved) if resolved is not None else path
                )
            return {
                "outcome": "resolved",
                "scope": scope,
                "changed_source": changed_source,
                "since": since,
                "base_branch": base_branch,
                "changed_files": relative_changes,
                "summary": {"changed_files": len(deduped)},
                "index_generation": generation,
            }

        answer = self.impact(
            deduped,
            depth=depth,
            max_nodes=max_nodes,
            direction=direction,
            edge_types=edge_types,
            include_imports=include_imports,
            fixpoint=fixpoint,
            seed_filter=seed_filter,
        )
        payload = answer.as_dict()
        payload.update(
            {
                "outcome": "resolved",
                "scope": scope,
                "changed_source": changed_source,
                "since": since,
                "base_branch": base_branch,
                "changed_files": [self._relative_path(path) for path in answer.changed_paths],
                "index_generation": generation,
            }
        )
        if scope == "tests":
            payload["impacted"] = [node.as_dict() for node in answer.test_symbols]
            payload["files"] = answer.test_files
            payload["summary"] = {
                "files": len(answer.test_files),
                "symbols": len(answer.test_symbols),
                "changed_files": len(answer.changed_paths),
                "high_risk": sum(
                    1 for node in answer.test_symbols if answer.risks.get(node.fqn) == "high"
                ),
            }
        return payload

    def _resolve_changed_path(self, path: str) -> str | None:
        """Resolve a caller-supplied changed path to its stored spelling."""
        from code_search.engine.paths import normalize_indexed_path, resolve_stored_path

        candidate = normalize_indexed_path(path, self._index_root)
        with self._db.connect() as conn:
            if candidate is not None:
                stored = resolve_stored_path(candidate, conn)
                if stored is not None:
                    return stored
            # Explicit CLI paths may be relative to the caller's working
            # directory rather than the index root; try that spelling too.
            cwd_candidate = Path(path)
            if not cwd_candidate.is_absolute():
                cwd_candidate = Path.cwd() / cwd_candidate
            if cwd_candidate.exists():
                return resolve_stored_path(cwd_candidate.resolve(), conn)
            return None

    def _relative_changed_paths(self, stored_path: str) -> list[str]:
        """Return the relative spelling(s) a stored path may use in module edges."""
        values = {self._relative_path(stored_path)}
        values.add(Path(stored_path).as_posix())
        return sorted(values)

    # ------------------------------------------------------------------
    # Architecture report
    # ------------------------------------------------------------------
    def architecture_report(
        self,
        *,
        top_n: int = 15,
        max_communities: int = 10,
        max_edges: int = 20000,
    ) -> ArchitectureReport:
        """Build a deterministic, offline architecture report.

        God nodes are ranked by stored importance (falling back to raw degree
        on an index without the importance pass); test files and non-entity
        kinds are excluded. Communities come from deterministic label
        propagation over the resolved symbol graph. Import cycles are detected
        by DFS over resolved ``module_edges``.
        """
        start = time.monotonic()
        top_n = max(1, min(top_n, 100))
        max_communities = max(1, min(max_communities, 50))
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT s.id, s.fqn, s.name, s.kind, s.file_path, s.line_start, "
                "s.importance, "
                "(SELECT COUNT(*) FROM graph_edges e "
                " WHERE e.resolved = 1 AND e.source_symbol_id = s.id) + "
                "(SELECT COUNT(*) FROM graph_edges e2 "
                " WHERE e2.resolved = 1 AND e2.target_symbol_id = s.id) AS degree "
                "FROM symbols s WHERE s.kind IN "
                "('function','method','class','interface','enum','constructor') "
                "ORDER BY s.importance DESC, degree DESC, s.fqn, s.id;"
            ).fetchall()
            edge_rows = conn.execute(
                "SELECT source_symbol_id, target_symbol_id FROM graph_edges "
                "WHERE resolved = 1 AND target_symbol_id IS NOT NULL "
                "AND edge_type != 'TESTS' "
                "ORDER BY source_symbol_id, target_symbol_id LIMIT ?;",
                (max_edges,),
            ).fetchall()
            total_symbols = int(conn.execute("SELECT COUNT(*) AS n FROM symbols;").fetchone()["n"])

        entity_ids: set[int] = set()
        god_nodes: list[dict[str, Any]] = []
        for row in rows:
            if _is_test_file(str(row["file_path"] or "")):
                continue
            node_degree = int(row["degree"])
            if node_degree <= 0:
                continue
            entity_ids.add(int(row["id"]))
            if len(god_nodes) < top_n:
                god_nodes.append(
                    {
                        "fqn": row["fqn"],
                        "kind": row["kind"],
                        "file_path": self._relative_path(str(row["file_path"] or "")),
                        "degree": node_degree,
                        "importance": round(float(row["importance"] or 0.0), 6),
                    }
                )

        adjacency: dict[int, set[int]] = {node_id: set() for node_id in entity_ids}
        degree_map: dict[int, int] = dict.fromkeys(entity_ids, 0)
        for edge in edge_rows:
            src = int(edge["source_symbol_id"])
            tgt = int(edge["target_symbol_id"])
            if src in entity_ids and tgt in entity_ids and src != tgt:
                adjacency[src].add(tgt)
                adjacency[tgt].add(src)
                degree_map[src] += 1
                degree_map[tgt] += 1

        communities = self._label_propagation(adjacency, max_communities)
        god_by_id = {
            int(row["id"]): str(row["fqn"]) for row in rows if int(row["id"]) in entity_ids
        }
        for community in communities:
            members = community["members"]
            community["label"] = (
                max(members, key=lambda member: (degree_map.get(member, 0), god_by_id[member]))
                if members
                else ""
            )
            community["label_fqn"] = god_by_id.get(community["label"], "")
            community["members"] = [{"id": member, "fqn": god_by_id[member]} for member in members]

        cycles = self._import_cycles()
        edge_stats = edge_resolution_stats(self._db)
        total_edges = sum(int(stat["total"]) for stat in edge_stats.values())
        resolved_edges = sum(int(stat["resolved"]) for stat in edge_stats.values())
        resolved_symbols = len(entity_ids)
        isolated = [
            {
                "fqn": row["fqn"],
                "kind": row["kind"],
                "file_path": self._relative_path(str(row["file_path"] or "")),
            }
            for row in rows
            if int(row["id"]) in entity_ids and degree_map.get(int(row["id"]), 0) == 0
        ][:top_n]
        return ArchitectureReport(
            god_nodes=god_nodes,
            communities=communities,
            import_cycles=cycles,
            isolated=isolated,
            edge_stats=edge_stats,
            suggested_questions=self._suggest_questions(god_nodes, cycles, isolated),
            stats={
                "symbols": resolved_symbols,
                "symbols_extracted": total_symbols,
                "symbol_coverage": (
                    round(resolved_symbols / total_symbols, 3) if total_symbols else 0.0
                ),
                "edges": len(edge_rows),
                "edges_total": total_edges,
                "edges_resolved": resolved_edges,
                "edge_coverage": round(resolved_edges / total_edges, 3) if total_edges else 0.0,
                "elapsed_ms": round((time.monotonic() - start) * 1000, 1),
            },
        )

    def architecture(
        self,
        *,
        aspects: set[str] | None = None,
        top_n: int = 15,
        max_communities: int = 10,
    ) -> dict[str, Any]:
        """Return a bounded architecture answer for the requested aspects.

        ``overview`` is the safe default: languages, directory packages, and
        entry-point counts. The expensive sections (hotspots, clusters, cycles)
        are only computed when requested, so an agent cannot accidentally pull a
        whole report into its context.

        Args:
            aspects: Requested sections. ``all`` expands to every supported
                aspect. ``None`` means ``overview``.
            top_n: Maximum hotspots and examples per section (clipped to 50).
            max_communities: Maximum clusters returned (clipped to 20).

        Returns:
            A JSON-serialisable payload. An unsupported aspect returns
            ``outcome: invalid_argument`` with the supported set rather than
            silently ignoring it.
        """
        requested = {aspect.strip().lower() for aspect in (aspects or {"overview"}) if aspect}
        if "all" in requested:
            requested = set(ARCHITECTURE_ASPECTS)
        unsupported = sorted(requested - ARCHITECTURE_ASPECTS)
        if unsupported:
            return {
                "outcome": "invalid_argument",
                "error": f"unsupported aspect(s): {', '.join(unsupported)}",
                "supported_aspects": sorted(ARCHITECTURE_ASPECTS),
            }

        top_n = max(1, min(top_n, 50))
        max_communities = max(1, min(max_communities, 20))
        start = time.monotonic()
        # Hotspots and clusters need the full degree/community pass. Overview,
        # structure, dependencies, entry points, and cycles do not, so the
        # default discovery call stays cheap.
        needs_report = bool(requested & {"hotspots", "clusters"})
        report = (
            self.architecture_report(top_n=top_n, max_communities=max_communities)
            if needs_report
            else None
        )
        with self._db.connect() as conn:
            generation_row = conn.execute(
                "SELECT value FROM index_metadata WHERE key = 'index_generation';"
            ).fetchone()
            generation = str(generation_row["value"]) if generation_row is not None else None
            total_symbols = int(conn.execute("SELECT COUNT(*) AS n FROM symbols;").fetchone()["n"])
        edge_stats = report.edge_stats if report is not None else edge_resolution_stats(self._db)
        total_edges = sum(int(stat["total"]) for stat in edge_stats.values())
        resolved_edges = sum(int(stat["resolved"]) for stat in edge_stats.values())
        stats: dict[str, Any] = {
            "symbols_extracted": total_symbols,
            "edges_total": total_edges,
            "edges_resolved": resolved_edges,
            "edge_coverage": round(resolved_edges / total_edges, 3) if total_edges else 0.0,
        }
        if report is not None:
            stats.update(report.stats)

        payload: dict[str, Any] = {
            "outcome": "resolved",
            "aspects": sorted(requested),
            "index_generation": generation,
            "stats": stats,
        }
        if report is not None:
            payload["suggested_questions"] = report.suggested_questions
        if requested & {"overview", "structure"}:
            payload["languages"] = self._symbol_language_counts()
            payload["packages"] = self._package_symbol_counts(limit=max(top_n, 10))
        if "overview" in requested or "entry_points" in requested:
            payload["entry_points"] = self._entry_point_summary(limit=10)
        if "dependencies" in requested:
            payload["edge_stats"] = edge_stats
        if "hotspots" in requested and report is not None:
            payload["hotspots"] = report.god_nodes
        if "clusters" in requested and report is not None:
            payload["clusters"] = report.communities
        if "cycles" in requested:
            payload["cycles"] = self._import_sccs()
            payload["cycle_semantics"] = (
                "strongly connected components over resolved module imports; "
                "each component contains a cycle"
            )
        payload["elapsed_ms"] = round((time.monotonic() - start) * 1000, 1)
        return payload

    def _symbol_language_counts(self) -> dict[str, int]:
        """Return ``{language: symbol_count}`` in deterministic order."""
        with self._db.connect() as conn:
            return {
                str(row["language"]): int(row["total"])
                for row in conn.execute(
                    "SELECT language, COUNT(*) AS total FROM symbols "
                    "GROUP BY language ORDER BY language;"
                )
            }

    def _package_symbol_counts(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Aggregate symbol counts by parent directory, most populated first."""
        counts: dict[str, int] = {}
        with self._db.connect() as conn:
            for row in conn.execute(
                "SELECT file_path, COUNT(*) AS total FROM symbols GROUP BY file_path;"
            ):
                relative = self._relative_path(str(row["file_path"] or ""))
                directory = relative.rsplit("/", 1)[0] if "/" in relative else "."
                counts[directory] = counts.get(directory, 0) + int(row["total"])
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [{"path": path, "symbols": total} for path, total in ordered[:limit]]

    def _entry_point_summary(self, *, limit: int = 10) -> dict[str, Any]:
        """Summarise stored entry-point classifications, with a legacy fallback."""
        from code_search.engine.graph_surface import _entry_point_reason, _has_derived_data

        by_reason: dict[str, int] = {}
        examples: list[dict[str, Any]] = []
        with self._db.connect() as conn:
            use_stored = _has_derived_data(conn)
            if use_stored:
                for row in conn.execute(
                    "SELECT COALESCE(entry_point_reason, 'unknown') AS reason, "
                    "COUNT(*) AS total FROM symbols WHERE is_entry_point = 1 "
                    "GROUP BY COALESCE(entry_point_reason, 'unknown') ORDER BY reason;"
                ):
                    by_reason[str(row["reason"])] = int(row["total"])
                rows = conn.execute(
                    "SELECT s.fqn, s.name, s.kind, s.file_path, s.line_start, "
                    "s.entry_point_reason AS reason FROM symbols s "
                    "WHERE s.is_entry_point = 1 "
                    "ORDER BY s.importance DESC, s.fqn LIMIT ?;",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT s.fqn, s.name, s.kind, s.file_path, s.line_start, "
                    "p.fqn AS parent_fqn FROM symbols s "
                    "LEFT JOIN symbols p ON p.id = s.parent_symbol_id "
                    "WHERE s.kind IN ('function','method','constructor') "
                    "ORDER BY s.fqn;"
                ).fetchall()
        if not use_stored:
            for row in rows:
                reason = _entry_point_reason(
                    str(row["file_path"] or ""),
                    str(row["name"]),
                    str(row["kind"]),
                    row["parent_fqn"],
                )
                if reason is None:
                    continue
                by_reason[reason] = by_reason.get(reason, 0) + 1
                if len(examples) < limit:
                    examples.append(
                        {
                            "fqn": row["fqn"],
                            "kind": row["kind"],
                            "name": row["name"],
                            "file_path": self._relative_path(str(row["file_path"] or "")),
                            "line_start": row["line_start"],
                            "reason": reason,
                        }
                    )
        else:
            for row in rows:
                examples.append(
                    {
                        "fqn": row["fqn"],
                        "kind": row["kind"],
                        "name": row["name"],
                        "file_path": self._relative_path(str(row["file_path"] or "")),
                        "line_start": row["line_start"],
                        "reason": row["reason"],
                    }
                )
        return {
            "total": sum(by_reason.values()),
            "by_reason": dict(sorted(by_reason.items())),
            "examples": examples,
            "classification": "stored" if use_stored else "phase1_heuristic",
        }

    def _import_sccs(self, max_edges: int = 20000) -> list[list[str]]:
        """Return import cycles as strongly connected components (Tarjan).

        Iterative Tarjan avoids recursion limits on large module graphs. Only
        components with more than one module (or a self-import) are returned,
        sorted deterministically.
        """
        edges = self._modules.all_edges("IMPORTS")[:max_edges]
        adjacency: dict[str, set[str]] = {}
        nodes: set[str] = set()
        for edge in edges:
            source = str(edge.get("source_path") or "")
            target = str(edge.get("target_path") or "")
            if not source or not target or not edge.get("resolved"):
                continue
            nodes.update((source, target))
            adjacency.setdefault(source, set()).add(target)
            adjacency.setdefault(target, set())

        index_counter = 0
        indices: dict[str, int] = {}
        lowlink: dict[str, int] = {}
        stack: list[str] = []
        on_stack: set[str] = set()
        components: list[list[str]] = []

        for start in sorted(nodes):
            if start in indices:
                continue
            indices[start] = lowlink[start] = index_counter
            index_counter += 1
            stack.append(start)
            on_stack.add(start)
            work: list[tuple[str, Any]] = [(start, iter(sorted(adjacency.get(start, set()))))]
            while work:
                node, neighbors = work[-1]
                advanced = False
                for neighbor in neighbors:
                    if neighbor not in indices:
                        indices[neighbor] = lowlink[neighbor] = index_counter
                        index_counter += 1
                        stack.append(neighbor)
                        on_stack.add(neighbor)
                        work.append((neighbor, iter(sorted(adjacency.get(neighbor, set())))))
                        advanced = True
                        break
                    if neighbor in on_stack:
                        lowlink[node] = min(lowlink[node], indices[neighbor])
                if advanced:
                    continue
                work.pop()
                if lowlink[node] == indices[node]:
                    component: list[str] = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        component.append(member)
                        if member == node:
                            break
                    if len(component) > 1 or node in adjacency.get(node, set()):
                        components.append(sorted(component))
                if work:
                    parent = work[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[node])

        return sorted(components)[:20]

    @staticmethod
    def _label_propagation(
        adjacency: dict[int, set[int]],
        max_communities: int,
    ) -> list[dict[str, Any]]:
        """Deterministic label propagation over the entity graph."""
        labels: dict[int, int] = {node: node for node in adjacency}
        for _ in range(10):
            changed = False
            for node in sorted(labels):
                counts: dict[int, int] = {}
                for neighbor in sorted(adjacency.get(node, set())):
                    label = labels[neighbor]
                    counts[label] = counts.get(label, 0) + 1
                if not counts:
                    continue
                best = min(counts, key=lambda label: (-counts[label], label))
                if best != labels[node]:
                    labels[node] = best
                    changed = True
            if not changed:
                break
        groups: dict[int, list[int]] = {}
        for node, label in labels.items():
            groups.setdefault(label, []).append(node)
        ordered = sorted(groups.values(), key=lambda members: (-len(members), min(members)))
        result: list[dict[str, Any]] = []
        for members in ordered[:max_communities]:
            if len(members) < 2:
                continue
            result.append(
                {
                    "label": 0,
                    "label_fqn": "",
                    "size": len(members),
                    "members": sorted(members),
                }
            )
        return result

    def _import_cycles(self, max_edges: int = 5000) -> list[list[str]]:
        """Return deterministic import cycles from resolved ``module_edges``."""
        edges = self._modules.all_edges("IMPORTS")[:max_edges]
        adjacency: dict[str, set[str]] = {}
        for edge in edges:
            if edge.get("resolved") and edge.get("target_path"):
                adjacency.setdefault(str(edge["source_path"]), set()).add(str(edge["target_path"]))
        cycles: list[list[str]] = []
        seen_cycles: set[tuple[str, ...]] = set()
        visited: set[str] = set()
        for start in sorted(adjacency):
            if start in visited:
                continue
            stack: list[tuple[str, list[str]]] = [(start, [start])]
            local: set[str] = set()
            while stack:
                node, path = stack.pop()
                local.add(node)
                for neighbor in sorted(adjacency.get(node, set())):
                    if neighbor == start and len(path) >= 2:
                        key = tuple(sorted(path))
                        if key not in seen_cycles:
                            seen_cycles.add(key)
                            cycles.append([*path, start])
                    elif neighbor not in path and neighbor not in local:
                        stack.append((neighbor, [*path, neighbor]))
            visited |= local
            if len(cycles) >= 20:
                break
        return cycles

    @staticmethod
    def _suggest_questions(
        god_nodes: list[dict[str, Any]],
        cycles: list[list[str]],
        isolated: list[dict[str, Any]],
    ) -> list[str]:
        """Derive deterministic follow-up questions from the report."""
        questions: list[str] = []
        for node in god_nodes[:5]:
            questions.append(f"How does {display_symbol(str(node['fqn']))} connect to its callers?")
        for cycle in cycles[:3]:
            questions.append(f"Why does the import cycle {' -> '.join(cycle)} exist?")
        for node in isolated[:3]:
            questions.append(f"Is {display_symbol(str(node['fqn']))} still used anywhere?")
        return questions[:10]

    # ------------------------------------------------------------------
    # Ordering and budget
    # ------------------------------------------------------------------
    @staticmethod
    def _order_nodes(nodes: Any, seed_keys: set[str]) -> list[GraphNode]:
        """Order nodes by seed membership, distance, kind, and FQN."""

        def key(node: GraphNode) -> tuple[int, int, int, str]:
            return (
                0 if node.key in seed_keys else 1,
                node.distance,
                0 if node.source == "symbol" else 1,
                node.fqn,
            )

        return sorted(nodes, key=key)

    @staticmethod
    def _order_edges(edges: list[GraphEdge], nodes: dict[str, GraphNode]) -> list[GraphEdge]:
        """Order edges by source distance, confidence, relation, and endpoints."""

        def key(edge: GraphEdge) -> tuple[int, int, str, str, str]:
            source_node = nodes.get(edge.source)
            return (
                source_node.distance if source_node else 0,
                CONFIDENCE_ORDER.get(edge.confidence, 9),
                edge.relation,
                edge.source,
                edge.target,
            )

        return sorted(edges, key=key)

    def _trim_to_budget(self, answer: GraphAnswer, token_budget: int) -> None:
        """Trim nodes/edges deterministically when the answer exceeds budget."""
        budget = max(50, token_budget)
        seed_keys = {n.key for n in answer.seeds}
        while self._estimate_tokens(answer) > budget:
            removable = [n for n in answer.nodes if n.key not in seed_keys]
            if not removable:
                break
            drop = removable[-1]
            answer.nodes = [n for n in answer.nodes if n.key != drop.key]
            answer.edges = [e for e in answer.edges if drop.key not in (e.source, e.target)]
            answer.truncated = True

    @staticmethod
    def _estimate_tokens(answer: GraphAnswer) -> int:
        """Estimate the rendered answer size in tokens (chars / 4)."""
        lines = [f"query: {answer.question}", f"seeds: {len(answer.seeds)}"]
        lines.extend(f"{n.fqn} {n.kind} {n.file_path}" for n in answer.nodes)
        lines.extend(edge.render() for edge in answer.edges)
        return max(1, len("\n".join(lines)) // 4)


def render_query_text(answer: GraphAnswer, *, root: str | Path | None = None) -> str:
    """Render a :class:`GraphAnswer` as compact, agent-friendly text."""
    if answer.outcome == "no_seed":
        return "graph query: no graph seed resolved; retry with an explicit symbol name"
    seed_keys = {n.key for n in answer.seeds}
    header = (
        f'graph query: "{answer.question}" | seeds: '
        f"{', '.join(display_symbol(n.fqn) for n in answer.seeds)} | "
        f"nodes={len(answer.nodes)} edges={len(answer.edges)}"
        f"{' truncated' if answer.truncated else ''}"
    )
    lines = [header]
    grouped: dict[str, list[GraphNode]] = {}
    for node in answer.nodes:
        grouped.setdefault(relative_display(node.file_path, root) or "external", []).append(node)
    for file_path in sorted(grouped):
        lines.append(file_path)
        for node in grouped[file_path]:
            marker = "*" if node.key in seed_keys else " "
            location = f":{node.line_start}" if node.line_start is not None else ""
            reason = f" — {node.reason}" if node.key in seed_keys and node.reason else ""
            lines.append(f"  {marker} {display_symbol(node.fqn)} ({node.kind}){location}{reason}")
    relations = [edge for edge in answer.edges if edge.relation != "CONTAINS"]
    if relations:
        lines.append("relations:")
        lines.extend(f"  {_render_edge(edge)}" for edge in relations)
    return "\n".join(lines)


def render_path_text(answer: PathAnswer) -> str:
    """Render a :class:`PathAnswer` as a hop-by-hop chain."""
    if answer.outcome != "resolved":
        suffix = ""
        if answer.candidates:
            names = ", ".join(display_symbol(str(c.get("fqn", ""))) for c in answer.candidates[:3])
            suffix = f" ({names})"
        return f"path: {answer.outcome}: {answer.explanation or ''}{suffix}".strip()
    source = display_symbol(answer.source.fqn) if answer.source else "?"
    target = display_symbol(answer.target.fqn) if answer.target else "?"
    lines = [
        f"path: {source} -> {target} "
        f"({len(answer.hops)} hops, {'undirected' if answer.undirected else 'directed'})"
    ]
    lines.extend(f"  {_render_edge(hop)}" for hop in answer.hops)
    return "\n".join(lines)


def render_explain_text(answer: ExplainAnswer, *, root: str | Path | None = None) -> str:
    """Render an :class:`ExplainAnswer` with metadata, relations, and rationale.

    Containment is reported as a compact member list instead of a relation
    edge per member, and remaining relations are grouped by direction.
    """
    if answer.outcome != "resolved" or answer.symbol is None:
        suffix = f": {answer.outcome}"
        if answer.candidates:
            suffix += (
                " ("
                + ", ".join(display_symbol(str(c.get("fqn", ""))) for c in answer.candidates[:5])
                + ")"
            )
        return f"explain{suffix}"
    symbol = answer.symbol
    node_by_key = {node.key: node for node in answer.nodes}
    members = [
        node_by_key[edge.target]
        for edge in answer.edges
        if edge.relation == "CONTAINS"
        and edge.direction == "forward"
        and edge.source == symbol.key
        and edge.target in node_by_key
    ]
    relations = [edge for edge in answer.edges if edge.relation != "CONTAINS"]
    outgoing = [edge for edge in relations if edge.direction == "forward"]
    incoming = [edge for edge in relations if edge.direction == "reverse"]
    location = relative_display(symbol.file_path, root)
    lines = [
        f"explain: {display_symbol(symbol.fqn)}",
        f"  kind: {symbol.kind}",
        f"  location: {location}:{symbol.line_start}",
        f"  summary: {len(members)} members | {len(outgoing)} outgoing | {len(incoming)} incoming",
    ]
    if symbol.signature:
        lines.append(f"  signature: {symbol.signature}")
    if symbol.docstring:
        lines.append(f"  docstring: {symbol.docstring[:200]}")
    if members:
        lines.append(f"  members ({len(members)}):")
        for member in members:
            lines.append(f"    {display_symbol(member.fqn)} ({member.kind})")
    for label, edges in (("outgoing", outgoing), ("incoming", incoming)):
        if not edges:
            continue
        grouped_relations: dict[str, list[GraphEdge]] = {}
        for edge in edges:
            grouped_relations.setdefault(edge.relation, []).append(edge)
        lines.append(f"  {label}:")
        for relation in sorted(grouped_relations):
            lines.append(f"    {relation}:")
            lines.extend(f"      {_render_edge(edge)}" for edge in grouped_relations[relation])
    if answer.rationale:
        lines.append("  rationale:")
        for item in answer.rationale:
            item_path = relative_display(str(item["file_path"]), root)
            lines.append(
                f"    {item['kind']} {item_path}:{item['line_start']} {item['text'][:160]}"
            )
    if answer.doc_links:
        lines.append("  linked docs:")
        for link in answer.doc_links:
            doc_path = relative_display(str(link["doc_file_path"]), root)
            lines.append(
                f"    {doc_path}:{link['doc_line_start']} ({link['method']}, {link['score']:.2f})"
            )
    return "\n".join(lines)


def render_impact_text(answer: ImpactAnswer, *, root: str | Path | None = None) -> str:
    """Render an :class:`ImpactAnswer` with production and test buckets."""
    summary = answer.summary
    lines = [
        f"impact: {summary.get('symbols', 0)} symbols in "
        f"{summary.get('files', 0)} files "
        f"({summary.get('tests', summary.get('test_symbols', 0))} tests) from "
        f"{summary.get('changed_files', 0)} changed files"
    ]
    grouped: dict[str, list[GraphNode]] = {}
    for node in answer.impacted:
        grouped.setdefault(relative_display(node.file_path, root), []).append(node)
    for path in answer.files:
        grouped.setdefault(path, [])
    ordered_paths = [path for path in answer.files if path in grouped]
    known_paths = set(ordered_paths)
    ordered_paths.extend(path for path in grouped if path not in known_paths)
    production = [path for path in ordered_paths if not _is_test_file(path)]
    tests = [path for path in ordered_paths if _is_test_file(path)]
    for label, paths in (("production", production), ("tests", tests)):
        if not paths:
            continue
        lines.append(f"{label} ({len(paths)} files):")
        for path in paths:
            lines.append(f"  {path}")
            for node in grouped[path]:
                location = f":{node.line_start}" if node.line_start is not None else ""
                lines.append(f"    {display_symbol(node.fqn)} ({node.kind}){location}")
    return "\n".join(lines)


def render_changes_text(payload: dict[str, Any], *, root: str | Path | None = None) -> str:
    """Render a ``detect_changes`` payload as compact text."""
    outcome = payload.get("outcome")
    if outcome == "invalid_argument":
        return f"Invalid change request: {payload.get('error')}"
    if outcome == "no_changes":
        return "No changed files: pass paths or --since/--base-branch."
    summary = payload.get("summary", {})
    lines = [
        f"changes ({payload.get('scope', 'impact')}, "
        f"{payload.get('changed_source', 'explicit')}): "
        f"{summary.get('changed_files', len(payload.get('changed_files', [])))} changed files, "
        f"{summary.get('symbols', 0)} symbols in {summary.get('files', 0)} files"
    ]
    if payload.get("changed_files"):
        lines.append("Changed:")
        lines.extend(f"  {path}" for path in payload["changed_files"])
    risks = payload.get("risk_summary") or {}
    if risks:
        lines.append(
            "Risk: " + ", ".join(f"{level}={count}" for level, count in risks.items() if count)
        )
    by_file: dict[str, list[dict[str, Any]]] = {}
    for node in payload.get("impacted", []):
        by_file.setdefault(relative_display(node.get("file_path"), root), []).append(node)
    for path in payload.get("files", []):
        by_file.setdefault(path, [])
    for label, paths in (
        ("Production", payload.get("production_files", [])),
        ("Tests", payload.get("test_files", [])),
    ):
        if not paths:
            continue
        lines.append(f"{label} ({len(paths)} files):")
        for path in paths:
            lines.append(f"  {path}")
            for node in by_file.get(path, []):
                risk = (payload.get("risks") or {}).get(node["fqn"], "")
                risk_label = f", risk={risk}" if risk else ""
                location = f":{node['line_start']}" if node.get("line_start") is not None else ""
                lines.append(
                    f"    {display_symbol(str(node['fqn']))} "
                    f"({node.get('kind')}{risk_label}){location}"
                )
    if payload.get("truncated"):
        lines.append("  (truncated; raise --max-nodes or lower --depth)")
    lines.append(
        f"Direction: {payload.get('direction')} via "
        f"{', '.join(payload.get('via') or []) or 'none'}"
        f"{' (fixpoint)' if payload.get('fixpoint') else ''}"
    )
    return "\n".join(lines)


def render_architecture_aspects_text(payload: dict[str, Any]) -> str:
    """Render a bounded architecture aspect payload as compact text."""
    if payload.get("outcome") == "invalid_argument":
        return f"Invalid architecture request: {payload.get('error')}"
    lines = [f"Architecture ({', '.join(payload.get('aspects', []))})"]
    stats = payload.get("stats", {})
    if stats:
        if "symbols" in stats:
            lines.append(
                f"Symbols: {int(stats.get('symbols', 0)):,} resolved of "
                f"{int(stats.get('symbols_extracted', 0)):,}; "
                f"edge coverage {float(stats.get('edge_coverage', 0.0)):.3f}"
            )
        else:
            lines.append(
                f"Symbols: {int(stats.get('symbols_extracted', 0)):,}; "
                f"edge coverage {float(stats.get('edge_coverage', 0.0)):.3f}"
            )
    if "languages" in payload:
        rendered = ", ".join(
            f"{language}={count:,}" for language, count in payload["languages"].items()
        )
        lines.append(f"Languages: {rendered or 'none'}")
    if "packages" in payload:
        lines.append("Packages:")
        for package in payload["packages"]:
            lines.append(f"  {package['path']}: {package['symbols']:,}")
    if "entry_points" in payload:
        entry_points = payload["entry_points"]
        reasons = ", ".join(
            f"{reason}={count:,}" for reason, count in entry_points.get("by_reason", {}).items()
        )
        lines.append(f"Entry points: {int(entry_points.get('total', 0)):,} ({reasons or 'none'})")
    if "edge_stats" in payload:
        lines.append("Edge types:")
        for edge_type, stat in sorted(payload["edge_stats"].items()):
            lines.append(
                f"  {edge_type:<12} {int(stat.get('total', 0)):,} "
                f"({int(stat.get('resolved', 0)):,} resolved)"
            )
    if "hotspots" in payload:
        lines.append("Hotspots:")
        for node in payload["hotspots"]:
            lines.append(
                f"  {display_symbol(str(node['fqn']))} ({node['kind']}, degree {node['degree']})"
            )
    if "clusters" in payload:
        lines.append(f"Clusters: {len(payload['clusters'])}")
        for cluster in payload["clusters"]:
            lines.append(
                f"  {cluster.get('label_fqn') or cluster.get('label')} "
                f"({int(cluster.get('size', 0))} members)"
            )
    if "cycles" in payload:
        lines.append(f"Cycles ({payload.get('cycle_semantics', 'strongly connected components')}):")
        for cycle in payload["cycles"]:
            lines.append(f"  {' -> '.join(cycle)}")
        if not payload["cycles"]:
            lines.append("  none recorded")
    if payload.get("suggested_questions"):
        lines.append("Suggested questions:")
        lines.extend(f"  - {question}" for question in payload["suggested_questions"])
    return "\n".join(lines)


def render_architecture_markdown(report: ArchitectureReport) -> str:
    """Render an :class:`ArchitectureReport` as deterministic Markdown."""
    lines = ["# Graph Architecture Report", ""]
    lines.append(
        f"Symbols: {report.stats.get('symbols', 0)} | "
        f"Resolved edges: {report.stats.get('edges', 0)}"
    )
    if "symbols_extracted" in report.stats:
        lines.append(
            f"Symbol coverage: {report.stats.get('symbol_coverage', 0.0):.1%} "
            f"({report.stats.get('symbols', 0)} connected / "
            f"{report.stats.get('symbols_extracted', 0)} extracted) | "
            f"Edge coverage: {report.stats.get('edge_coverage', 0.0):.1%} "
            f"({report.stats.get('edges_resolved', 0)} / "
            f"{report.stats.get('edges_total', 0)})"
        )
    lines.append("")
    lines.append("## God nodes")
    if report.god_nodes:
        lines.append("")
        lines.append("| Symbol | Kind | Degree | File |")
        lines.append("|---|---|---:|---|")
        for node in report.god_nodes:
            lines.append(
                f"| `{display_symbol(str(node['fqn']))}` | {node['kind']} "
                f"| {node['degree']} | {node['file_path']} |"
            )
    else:
        lines.append("")
        lines.append("_No resolved call edges yet._")

    lines.append("")
    lines.append("## Communities")
    if report.communities:
        for community in report.communities:
            names = ", ".join(
                f"`{display_symbol(str(member['fqn']))}`" for member in community["members"][:8]
            )
            label = community["label_fqn"] or community["label"]
            lines.append(
                f"- **{display_symbol(str(label))}** ({community['size']} members): {names}"
            )
    else:
        lines.append("_No multi-node communities._")

    lines.append("")
    lines.append("## Import cycles")
    if report.import_cycles:
        for cycle in report.import_cycles:
            lines.append(f"- {' -> '.join(cycle)}")
    else:
        lines.append("_No import cycles._")

    lines.append("")
    lines.append("## Suggested questions")
    for question in report.suggested_questions:
        lines.append(f"- {question}")
    return "\n".join(lines) + "\n"


def compact_json(payload: dict[str, Any]) -> str:
    """Serialise *payload* without indentation for compact agent transport."""
    return json.dumps(payload, default=str, separators=(",", ":"))


def symbol_source_slice(symbol: dict[str, Any]) -> str:
    """Return the source slice for *symbol* (used by tests and callers)."""
    return read_source_slice(
        str(symbol.get("file_path") or ""),
        symbol.get("line_start"),
        symbol.get("line_end"),
    )
