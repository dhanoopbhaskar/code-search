"""Hybrid search — BM25 (sparse) + vector (dense) with RRF fusion.

Provides three layers:
- BM25Search — keyword retrieval via rank_bm25.
- VectorSearch — semantic retrieval via the vector index.
- HybridSearch — fused ranking using Reciprocal Rank Fusion (RRF).
"""

from __future__ import annotations

import logging
import math
import re
import time
from pathlib import Path
from typing import Any, cast

from src.engine.classification import FileRole, PathClass, file_role
from src.engine.classification import content_type as classify_content_type
from src.engine.confidence import (
    MatchEvidence,
    QueryMatchContext,
    calibrated_confidence,
    confidence_band,
    envelope_band,
    is_borderline,
    qualified_query_name,
)
from src.engine.config import Settings, _is_non_canonical, _is_test_file
from src.engine.embeddings import EmbeddingGenerator, VectorIndex
from src.engine.expansions import ExpansionTable
from src.engine.graph import GraphDatabase, IndexMetadataStore
from src.engine.intent_detection import (
    ContentIntent,
    build_scope_signal,
    classify_content_intent,
    scope_override,
)
from src.engine.language import QueryAnalysis, analyze_query, language_vocabularies
from src.engine.match_boost import (
    MatchEvidence as BoostMatchEvidence,
)
from src.engine.match_boost import (
    MatchTier,
    QueryNameContext,
    classify_filename_match,
    classify_path_match,
    classify_symbol_match,
    compute_verdict,
    filename_candidates,
    normalize_name,
    strongest_tier,
)
from src.engine.paths import normalize_indexed_path
from src.engine.reranking import demote_test_file_candidates
from src.engine.scent_detection import (
    compute_scent_adjustment,
    detect_config_ddl_scent,
)

logger = logging.getLogger(__name__)

# The content-scope vocabulary: the four explicit
# axes plus the code-focused default. ``code_focused`` resolves to the pool
# ``content_type != 'docs'`` (code + config); prose is returned only under an
# explicit ``docs``/``all`` scope. This is the default ranked scope on both
# surfaces and in the engine.
DEFAULT_CONTENT_SCOPE = "code_focused"
VALID_CONTENT_SCOPES = ("code", "config", "docs", "all", DEFAULT_CONTENT_SCOPE)

# Above this many significant query terms the exact-filename FTS lookup is
# skipped: a file name or stem that equals a long natural-language phrase is
# vanishingly rare, and the proportional path tier still covers such queries.
_FILENAME_LOOKUP_MAX_TERMS = 2

# The exhaustive matching-semantics vocabulary (literal/all_tokens/any_token).
VALID_MATCHING_SEMANTICS = ("literal", "all_tokens", "any_token")

# Common English stopwords filtered out when CODE_SEARCH_FILTER_STOPWORDS is enabled.
STOPWORDS: set[str] = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "can",
    "could",
    "shall",
    "should",
    "may",
    "might",
    "must",
    "to",
    "of",
    "in",
    "for",
    "on",
    "with",
    "at",
    "by",
    "from",
    "as",
    "into",
    "through",
    "during",
    "before",
    "after",
    "above",
    "below",
    "between",
    "out",
    "off",
    "over",
    "under",
    "again",
    "further",
    "then",
    "once",
    "here",
    "there",
    "when",
    "where",
    "why",
    "how",
    "all",
    "each",
    "every",
    "both",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "no",
    "nor",
    "not",
    "only",
    "own",
    "same",
    "so",
    "than",
    "too",
    "very",
    "just",
    "because",
    "but",
    "and",
    "or",
    "if",
    "while",
    "that",
    "this",
    "these",
    "those",
    "it",
    "its",
    "what",
    "which",
    "who",
    "whom",
}


def tokenize(text: str, filter_stopwords: bool = False) -> list[str]:
    """Split text into lowercased alphanumeric tokens, optionally removing stopwords."""
    text = text.lower()
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text)
    if filter_stopwords:
        return [t for t in tokens if t not in STOPWORDS]
    return tokens


# Boundaries between a lowercase letter/digit and an uppercase letter
# (camelCase/acronym) and between consecutive uppercase letters followed by a
# lowercase letter (e.g. ``PUBLICRead`` -> ``public read``).
_SUBWORD_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|[_\-]")

# Programming-language keywords and generic boilerplate words that carry no
# concept signal. Excluded from the informative-token coverage so that a
# nonsense query decomposing into common words ("does this file exist
# findAnyMethodThatDoesNotExist") is rejected even on small corpora where such
# words would otherwise be IDF-rare.
NON_INFORMATIVE_CODE_TERMS: frozenset[str] = frozenset(
    {
        # Language keywords / common types
        "public",
        "private",
        "protected",
        "package",
        "import",
        "class",
        "interface",
        "enum",
        "extends",
        "implements",
        "static",
        "final",
        "abstract",
        "synchronized",
        "transient",
        "volatile",
        "void",
        "return",
        "new",
        "this",
        "super",
        "instanceof",
        "null",
        "true",
        "false",
        "boolean",
        "int",
        "long",
        "double",
        "float",
        "char",
        "byte",
        "short",
        "string",
        "object",
        "integer",
        "list",
        "map",
        "set",
        "try",
        "catch",
        "finally",
        "throw",
        "throws",
        "if",
        "else",
        "for",
        "while",
        "do",
        "switch",
        "case",
        "break",
        "continue",
        "default",
        "def",
        "func",
        "function",
        "lambda",
        "async",
        "await",
        "var",
        "let",
        "const",
        "from",
        "require",
        "module",
        "export",
        "yield",
        "global",
        "nonlocal",
        "pass",
        # Generic boilerplate / low-value words
        "file",
        "files",
        "exist",
        "exists",
        "method",
        "methods",
        "value",
        "values",
        "name",
        "names",
        "type",
        "types",
        "param",
        "params",
        "parameter",
        "parameters",
        "arg",
        "args",
        "argument",
        "arguments",
        "find",
        "get",
        "add",
        "remove",
        "update",
        "create",
        "delete",
        "make",
        "use",
        "using",
        "used",
        "any",
        "some",
        "each",
        "every",
        "other",
        "another",
        "what",
        "when",
        "where",
        "who",
        "which",
        "how",
        "why",
        "has",
        "have",
        "had",
    }
)

_ENUMERATION_KIND_WORDS: frozenset[str] = frozenset(
    {
        "class",
        "classes",
        "interface",
        "interfaces",
        "enum",
        "enums",
        "annotation",
        "annotations",
        "method",
        "methods",
        "function",
        "functions",
    }
)


# ``chunk_node_type`` -> symbol-kind label used for enumerate result items
# when no ``symbols`` row resolves (``kind`` is
# the symbol kind from ``symbols.kind``).
_CHUNK_NODE_KIND: dict[str, str] = {
    "class_declaration": "class",
    "class_definition": "class",
    "record_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "annotation_type_declaration": "annotation",
    "method_declaration": "method",
    "method_definition": "method",
    "function_definition": "function",
    "constructor_declaration": "constructor",
    "field_declaration": "field",
    "module": "module",
}


def _enumerated_kind(row: Any) -> str:
    """Return the symbol-kind label for an enumerated chunk row.

    Prefers the joined ``symbols.kind``; resource chunks (no symbol row)
    report ``"resource"``; otherwise the node-type map or ``"class"`` is the
    fallback so every enumerated item carries a ``kind`` label.
    """
    symbol_kind = row["symbol_kind"]
    if symbol_kind:
        return str(symbol_kind)
    if row["chunk_type"] == "resource":
        return "resource"
    return _CHUNK_NODE_KIND.get(row["chunk_node_type"] or "", "class")


def identify_subwords(text: str) -> list[str]:
    """Decompose identifiers into lowercased sub-words.

    Splits on camelCase/snake_case/acronym boundaries only: ``isTokenValid``
    -> ``["is", "token", "valid"]``, ``PUBLIC_READ_ENDPOINTS`` ->
    ``["public", "read", "endpoints"]``. Single-word identifiers without a
    boundary (``Pageable``) are returned as-is — those are matched via the
    query-side ≥3-char prefix fallback, not index-side splitting.
    """
    parts = _SUBWORD_SPLIT.split(text)
    return [part.lower() for part in parts if part]


def decompose_query(query: str, filter_stopwords: bool = False) -> list[str]:
    """Decompose query tokens into deduplicated sub-words.

    ``token valid`` -> ``["token", "valid"]``; ``isTokenValid`` ->
    ``["is", "token", "valid"]``. Identifiers are split on their original case
    so camelCase boundaries survive (``findAnyMethodThatDoesNotExist`` ->
    ``["find", "any", "method", "that", "does", "not", "exist"]``).
    Order-preserving.
    """
    words: list[str] = []
    for token in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", query):
        if filter_stopwords and token.lower() in STOPWORDS:
            continue
        for w in identify_subwords(token):
            if w and w not in words:
                words.append(w)
    return words


def build_fts_query(subwords: list[str], exact_terms: set[str] | None = None) -> str:
    """Build an FTS5 MATCH expression from decomposed sub-words.

    Sub-words present verbatim in *exact_terms* (the corpus subword
    vocabulary) are emitted as exact tokens; sub-words with no exact corpus
    token are expanded to a ≥3-char prefix (``pagination`` -> ``pag*``) so
    the identifier vocabulary bridges morphological variants. Terms are
    joined with ``OR``.
    """
    exact = exact_terms or set()
    clauses: list[str] = []
    for w in subwords:
        if not w:
            continue
        if w in exact:
            clauses.append(w)
        elif len(w) >= 3:
            clauses.append(w[:3] + "*")
        else:
            clauses.append(w)
    return " OR ".join(clauses)


def query_symbol_identifier(query: str) -> str | None:
    """Return the identifier-like token for symbol-like queries, else ``None``.

    A symbol-like query is a single bare identifier carrying a sub-word
    boundary (camelCase or snake_case) — e.g. ``is_token_valid``,
    ``validateToken``. ``pagination`` (single word, no boundary) is treated
    as natural language so it gets prefix expansion instead.
    """
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", query)
    if len(tokens) == 1:
        tok: str = tokens[0]
        if "_" in tok or (tok != tok.lower() and tok != tok.upper()):
            return tok
    return None


def classify_query(query: str) -> str:
    """Classify *query* as ``symbol`` (single identifier) or ``natural``."""
    return "symbol" if query_symbol_identifier(query) else "natural"


_ANNOTATION_RE = re.compile(r"@([a-zA-Z_][a-zA-Z0-9_]*)")
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_QUOTED_RE = re.compile(r'"([^"]+)"|\'([^\']+)\'')
# Dependency/literal evidence: a concrete connection string or URL scheme
# (``jdbc:mysql``, ``postgresql://host:5432``). Such a literal in a tooling
# file is strong evidence that overrides the default ``infra`` demotion, so
# the ranked path keeps the lockfile/config file reachable (strong evidence
# still wins).
_DEPENDENCY_LITERAL_RE = re.compile(r"jdbc:[a-z][a-z0-9]*|[a-z][a-z0-9+.\-]*://[^\s\"']+")


def _language_for_file(file_path: Path) -> str | None:
    """Return the language identifier for *file_path* mirroring the indexer.

    Uses the suffix-based map (and the extension-less infra names) so an
    exhaustive scan applies the same language label the indexer stored; the
    scan is only ever called when a language filter is active.
    """
    from src.engine.parser import ASTParser

    return ASTParser().detect_language(file_path)


def exact_precheck(query: str) -> dict[str, Any] | None:
    """Detect whether *query* carries a concrete pattern/literal token.

    Returns a descriptor with ``annotations``, ``quotes``, ``literals``, and
    ``identifier`` when the query triggers the exact-match arm — the presence
    of an ``@Annotation``, a quoted literal, a dependency/connection-string
    literal (``jdbc:mysql``, ``postgresql://...``), or a single
    camelCase/snake_case identifier (per :func:`query_symbol_identifier`).
    Ordinary prose that merely mentions a symbol name among other tokens does
    **not** trigger it, so it never misfires.

    Returns ``None`` when the query is plain prose (no concrete token form).
    """
    annotations = sorted({m for m in _ANNOTATION_RE.findall(query) if m})
    quotes: list[str] = []
    for m in _QUOTED_RE.finditer(query):
        quotes.extend([g for g in m.groups() if g])
    literals = sorted({m for m in _DEPENDENCY_LITERAL_RE.findall(query) if m})
    identifier = query_symbol_identifier(query)
    if not annotations and not quotes and not literals and not identifier:
        return None
    return {
        "annotations": annotations,
        "quotes": quotes,
        "literals": literals,
        "identifier": identifier,
    }


def chunk_rank_class(chunk_type: str | None, chunk_node_type: str | None) -> str:
    """Return a chunk's rank class: ``code``, ``boilerplate``, or ``resource``.

    Resource files (``xml/sql/properties/gradle``) are classified ``resource``
    by the indexer's ``chunk_type``; tiny Java ``field_declaration`` chunks are
    classified ``boilerplate``; every other language-typed AST chunk is ``code``.
    """
    ct = chunk_type or "ast"
    if ct == "resource":
        return "resource"
    if ct == "ast" and chunk_node_type == "field_declaration":
        return "boilerplate"
    return "code"


class BM25Search:
    """FTS5-based BM25 keyword search over the indexed code_chunks corpus.

    Uses SQLite FTS5 ``bm25()`` ranking function directly instead of loading
    the entire corpus into memory with ``rank_bm25``.
    """

    def __init__(
        self,
        db: GraphDatabase,
        settings: Settings | None = None,
        filter_stopwords: bool = False,
    ) -> None:
        """Initialize the FTS5-backed keyword search over *db*.

        Args:
            db: The graph database exposing ``chunks_fts``.
            settings: Engine settings (BM25 column weights, IDF floor, gate
                thresholds); defaults to ``Settings.from_env()``.
            filter_stopwords: Whether common stopwords are removed from the
                query before matching.
        """
        self._db = db
        self._settings = settings or Settings.from_env()
        self._filter_stopwords = filter_stopwords
        self._subword_terms: set[str] | None = None
        self._corpus_stats: tuple[int, dict[str, int], dict[str, int], set[str]] | None = None

    def invalidate_corpus(self) -> None:
        """Drop cached corpus statistics so they are recomputed on next use.

        Call after indexing or mutating ``code_chunks`` to avoid stale
        informative-token and vocabulary decisions.
        """
        self._subword_terms = None
        self._corpus_stats = None

    def _corpus_subword_stats(self) -> tuple[int, dict[str, int], dict[str, int], set[str]]:
        """Return ``(total_chunks, token_doc_frequency, prefix_doc_frequency,
        subword_vocabulary)`` for the indexed corpus.

        ``token_doc_frequency`` counts distinct chunks whose ``subwords`` column
        contains the exact token; ``prefix_doc_frequency`` counts distinct chunks
        containing any sub-word with a given 3-char prefix. Used by the
        informative-token coverage signal. Cached until the corpus is
        invalidated.
        """
        if self._corpus_stats is not None:
            return self._corpus_stats
        total = 0
        token_df: dict[str, int] = {}
        prefix_df: dict[str, int] = {}
        try:
            with self._db.connect() as conn:
                rows = conn.execute("SELECT subwords FROM code_chunks;").fetchall()
            for row in rows:
                total += 1
                seen_tokens: set[str] = set()
                seen_prefixes: set[str] = set()
                for w in (row["subwords"] or "").split():
                    seen_tokens.add(w)
                    if len(w) >= 3:
                        seen_prefixes.add(w[:3])
                for w in seen_tokens:
                    token_df[w] = token_df.get(w, 0) + 1
                for p in seen_prefixes:
                    prefix_df[p] = prefix_df.get(p, 0) + 1
        except Exception as exc:
            logger.warning("Failed to load corpus subword statistics: %s", exc)
        self._corpus_stats = (total, token_df, prefix_df, set(token_df.keys()))
        return self._corpus_stats

    def _corpus_subword_terms(self) -> set[str]:
        """Return the set of sub-words present in the indexed corpus.

        Used to decide whether a decomposed query sub-word is an exact corpus
        token (no prefix expansion) or a novel vocabulary word (expanded to a
        ≥3-char prefix). Cached until the corpus is invalidated.
        """
        return self._corpus_subword_stats()[3]

    def informative_tokens(self, query: str) -> list[str]:
        """Return the query's informative sub-words (coverage signal).

        A sub-word is informative when it is not a stopword and not a generic
        code term, is present in the corpus (verbatim or as a ≥3-char prefix),
        and carries IDF at or above ``idf_floor``.
        """
        subwords = decompose_query(query, self._filter_stopwords)
        if not subwords:
            return []
        total, token_df, prefix_df, corpus = self._corpus_subword_stats()
        if total <= 0:
            return []
        informative: list[str] = []
        for w in subwords:
            if len(w) < 3 or w in STOPWORDS or w in NON_INFORMATIVE_CODE_TERMS:
                continue
            if w in corpus:
                docs = token_df.get(w, 0)
            elif prefix_df.get(w[:3], 0) > 0:
                docs = prefix_df[w[:3]]
            else:
                continue
            if docs <= 0:
                continue
            # A sub-word in very few chunks is concept-specific regardless of
            # corpus size (on tiny corpora the relative IDF is degenerate).
            idf = math.log(total / docs)
            if idf >= self._settings.idf_floor or docs <= 2:
                informative.append(w)
        return informative

    def concept_subwords(self, query: str) -> list[str]:
        """Return the query's candidate concept sub-words (coverage
        denominator).

        Sub-words that are at least 3 chars, non-stopword, and not a generic
        code term. A multi-token query must be supported by more than a single
        corpus-frequent-or-rare token, so gibberish queries that share one real
        informative identifier (``wqrble token``) are rejected even on small
        corpora where that token is IDF-rare (``token`` df=2/11 on the fixture).
        """
        return [
            w
            for w in decompose_query(query, self._filter_stopwords)
            if len(w) >= 3 and w not in STOPWORDS and w not in NON_INFORMATIVE_CODE_TERMS
        ]

    def _build_fts_query(self, query: str) -> str:
        """Build the FTS5 MATCH expression for *query* (content OR sub-words)."""
        query_tokens = tokenize(query, self._filter_stopwords)
        if not query_tokens:
            return ""
        subwords = decompose_query(query, self._filter_stopwords)
        exact_terms = self._corpus_subword_terms()
        subword_query = build_fts_query(subwords, exact_terms)
        content_query = " OR ".join(query_tokens)
        return f"({content_query}) OR ({subword_query})" if subword_query else content_query

    def search(self, query: str, top_k: int = 10, content: str = "all") -> list[tuple[int, float]]:
        """Run FTS5 BM25 search, returning ``(chunk_rowid, score)`` pairs.

        The MATCH expression combines the raw query tokens with the
        decomposed sub-word query (see :meth:`_build_fts_query`), and scores
        rows with the weighted ``bm25()`` function using the configured
        column weights. When *content* is a specific content axis
        (``"code"``/``"config"``/``"docs"``), only chunks of that axis are
        returned so out-of-scope chunks cannot consume the lexical pool.

        Args:
            query: The user query text.
            top_k: Maximum number of results to return.
            content: Content scope; ``"all"`` searches every axis.

        Returns:
            Chunk rowids paired with their (negative) BM25 score, ordered
            best-first. Empty when the query produces no MATCH expression or
            the search fails.
        """
        result = self._search_topk(query, top_k, count_only=False, content=content)
        return result if isinstance(result, list) else []

    def count(self, query: str) -> int:
        """Return the number of FTS5-matching chunks for *query* (uncapped).

        The count reflects total distinct matches for the query tokens before
        the top-k pool slice, so a response can report ``total_matches`` and a
        ``truncated`` flag. Returns ``0`` when the query
        produces no MATCH expression or the search fails.
        """
        result = self._search_topk(query, None, count_only=True)
        return result if isinstance(result, int) else 0

    def _search_topk(
        self, query: str, top_k: int | None, count_only: bool = False, content: str = "all"
    ) -> int | list[tuple[int, float]]:
        """Execute the FTS5 query for *query*.

        When *count_only* is set, returns the uncapped match count; otherwise
        returns up to *top_k* ``(chunk_rowid, score)`` pairs best-first.
        """
        fts5_query = self._build_fts_query(query)
        if not fts5_query:
            return 0 if count_only else []
        try:
            content_w = self._settings.bm25_content_weight
            subwords_w = self._settings.bm25_subwords_weight
            fqn_w = self._settings.bm25_fqn_weight
            path_w = self._settings.bm25_path_weight
            rules_w = self._settings.bm25_rules_weight
            with self._db.connect() as conn:
                if count_only:
                    row = conn.execute(
                        "SELECT COUNT(*) AS n FROM chunks_fts WHERE chunks_fts MATCH ?;",
                        (fts5_query,),
                    ).fetchone()
                    return cast(int, row["n"]) if row is not None else 0
                content_clause = (
                    ""
                    if content == "all"
                    else (
                        " AND c.content_type != 'docs'"
                        if content == DEFAULT_CONTENT_SCOPE
                        else " AND c.content_type = ?"
                    )
                )
                params: list[Any] = [fts5_query]
                if content not in ("all", DEFAULT_CONTENT_SCOPE):
                    params.append(content)
                params.append(top_k)
                rows = conn.execute(
                    f"SELECT f.rowid, bm25(chunks_fts, {content_w}, {subwords_w}, {fqn_w}, "
                    f"{path_w}, {rules_w}) AS score "
                    "FROM chunks_fts AS f JOIN code_chunks AS c ON c.id = f.rowid "
                    "WHERE chunks_fts MATCH ?" + content_clause + " ORDER BY score LIMIT ?;",
                    params,
                ).fetchall()
            results: list[tuple[int, float]] = []
            for row in rows:
                results.append((row["rowid"], float(row["score"])))
            return results
        except Exception as exc:
            logger.warning("FTS5 BM25 query failed: %s", exc)
            return 0 if count_only else []


class VectorSearch:
    """Semantic search using the vector index."""

    def __init__(
        self,
        vector_index: VectorIndex,
        embedding_generator: EmbeddingGenerator,
    ) -> None:
        """Initialize semantic search over the vector index.

        Args:
            vector_index: The flat-file :class:`VectorIndex` to query.
            embedding_generator: The :class:`EmbeddingGenerator` used to embed
                the query text.
        """
        self._vector_index = vector_index
        self._embedding_generator = embedding_generator

    def search(self, query: str, top_k: int = 10, content: str = "all") -> list[tuple[int, float]]:
        """Embed *query* and return ``(chunk_id, cosine_score)`` matches.

        When *content* is a specific content axis (``"code"``/``"config"``/
        ``"docs"``), the vector pool is restricted to chunks of that axis so
        out-of-scope chunks cannot consume the semantic pool.

        Args:
            query: The user query text.
            top_k: Maximum number of results to return.
            content: Content scope; ``"all"`` searches every axis.

        Returns:
            Cosine-similarity hits sorted descending, or an empty list when
            the query cannot be embedded (model unavailable).
        """
        embedding = self._embedding_generator.encode(query)
        if embedding is None:
            return []
        return self._vector_index.search(embedding, top_k=top_k, content=content)


def _normalize_scores(scores: dict[int, float]) -> dict[int, float]:
    """Normalize scores to [0, 1] range in-place.

    Single-source scores use z-score normalization for better discrimination.
    Fallback to min-max scaling when stddev is zero.
    """
    if not scores:
        return scores
    vals = list(scores.values())
    if len(vals) == 1:
        scores[next(iter(scores.keys()))] = 1.0
        return scores
    mean = sum(vals) / len(vals)
    variance = sum((v - mean) ** 2 for v in vals) / len(vals)
    stddev = variance**0.5
    if stddev < 1e-12:
        mn, mx = min(vals), max(vals)
        for k in scores:
            scores[k] = 1.0 if mx - mn < 1e-12 else (scores[k] - mn) / (mx - mn)
    else:
        # Clip between mean ± 3*stddev then min-max to [0, 1]
        for k in scores:
            z = (scores[k] - mean) / stddev
            scores[k] = max(0.0, min(1.0, (z + 3.0) / 6.0))
    return scores


def rrf_fusion(
    bm25_results: list[tuple[int, float]],
    vector_results: list[tuple[int, float]],
    k: int = 60,
    alpha: float | None = None,
) -> dict[int, float]:
    """Reciprocal Rank Fusion — combine two ranked result lists into a single score dict.

    Each result's RRF score is ``1 / (k + rank + 1)``, blended into
    ``alpha * semantic + (1 - alpha) * bm25`` (adaptive alpha). When
    ``alpha`` is ``None`` or only one result list is provided, the behaviour
    matches the pre-014 engine: the two arms are summed with equal weight
    (alpha 0.5, identical after scale-invariant normalisation) and
    single-source lists return z-score normalized scores directly instead of
    rank-based fusion to preserve meaningful score differentiation.

    Args:
        bm25_results: ``(chunk_rowid, score)`` pairs from the lexical arm.
        vector_results: ``(chunk_rowid, score)`` pairs from the dense arm.
        k: RRF rank offset.
        alpha: Weight of the vector arm in ``[0, 1]``; ``None`` defaults to a
            balanced (0.5) blend.
    """
    if not bm25_results and not vector_results:
        return {}
    if not bm25_results:
        scores = {cid: sc for cid, sc in vector_results}
        max_score = max(scores.values())
        if max_score < 0.5:
            return {}
        return _normalize_scores(scores)
    if not vector_results:
        scores = {cid: sc for cid, sc in bm25_results}
        return _normalize_scores(scores)

    blend = 0.5 if alpha is None else max(0.0, min(1.0, alpha))

    sem_rrf: dict[int, float] = {}
    rank_vector_map = {chunk_id: rank for rank, (chunk_id, _) in enumerate(vector_results)}
    for chunk_id, _raw_score in vector_results:
        sem_rrf[chunk_id] = 1.0 / (k + rank_vector_map[chunk_id] + 1)

    bm25_rrf: dict[int, float] = {}
    rank_bm25_map = {chunk_id: rank for rank, (chunk_id, _) in enumerate(bm25_results)}
    for chunk_id, _raw_score in bm25_results:
        bm25_rrf[chunk_id] = 1.0 / (k + rank_bm25_map[chunk_id] + 1)

    blended: dict[int, float] = {}
    for chunk_id in set(sem_rrf) | set(bm25_rrf):
        blended[chunk_id] = blend * sem_rrf.get(chunk_id, 0.0) + (1.0 - blend) * bm25_rrf.get(
            chunk_id, 0.0
        )
    return _normalize_scores(blended)


def _symbol_short_name(fqn: str) -> str:
    """Return the trailing symbol name from a dotted or path-scoped FQN.

    Java FQNs are dotted (``com.example.AuthService``) while Python/TypeScript
    FQNs embed the file path (``src/auth.py::AuthService``); both end with the
    bare symbol name as their final segment.
    """
    if "::" in fqn:
        return fqn.rsplit("::", 1)[-1]
    return fqn.rsplit(".", 1)[-1]


def _rescue_tier(file_stem: str, symbol_stem: str) -> str | None:
    """Return the stem-rescue tier for a definition's *file_stem*.

    A definition is ``stem_match`` (strongest boost) when the file stem equals
    the symbol stem or the symbol stem starts with the file stem — e.g.
    ``state.ts`` for ``StateManager`` (stem ``state``). A file whose stem
    starts with the symbol stem (e.g. ``state_store.ts``) is ``stem_related``.
    Returns ``None`` when the stems do not relate (no rescue).

    Args:
        file_stem: ``Path(file_path).stem`` of the definition's file.
        symbol_stem: Lowercased leading sub-word of the resolved symbol.

    Returns:
        ``"stem_match"``, ``"stem_related"``, or ``None``.
    """
    fs = file_stem.lower()
    ss = symbol_stem.lower()
    if fs == ss or ss.startswith(fs):
        return "stem_match"
    if fs.startswith(ss):
        return "stem_related"
    return None


class HybridSearch:
    """Combines BM25 keyword search and vector semantic search via RRF fusion.

    Supports filtering by language, exclusion of test files, and automatic
    degradation to BM25-only when the vector model is unavailable.
    """

    def __init__(
        self,
        db: GraphDatabase,
        vector_index: VectorIndex,
        embedding_generator: EmbeddingGenerator,
        settings: Settings | None = None,
        no_model: bool = False,
    ) -> None:
        """Initialize hybrid search over the graph DB and vector index.

        Args:
            db: The graph database exposing ``chunks_fts`` and query metadata.
            vector_index: The flat-file vector store for the dense arm.
            embedding_generator: Encodes the query for the dense arm.
            settings: Engine settings; defaults to ``Settings.from_env()``.
            no_model: Run the fast BM25-only path, skipping any vector model
                load or warm-up.
        """
        self._db = db
        self._settings = settings or Settings.from_env()
        filter_stopwords = getattr(settings, "filter_stopwords", False)
        self._bm25 = BM25Search(db, settings, filter_stopwords=filter_stopwords)
        self._embedding_generator = embedding_generator
        self._vector_search = VectorSearch(vector_index, embedding_generator)
        self._vector_index = vector_index
        self._no_model = no_model
        self._expansion_table = ExpansionTable(config_path=self._settings.expansion_file)
        self._symbol_store: Any | None = None
        self._vocab_by_language: dict[str, set[str]] | None = None
        self._analysis: QueryAnalysis | None = None
        if no_model:
            logger.debug("HybridSearch running in --no-model fast path")

    def _vector_layer_health(self) -> bool:
        """Return whether the vector layer is genuinely usable for this query.

        The health flag is ``True`` only when the vector index is
        populated AND the embedding model produced a query vector. It is
        derived from the persisted ``index_metadata.vector_model_*`` keys
        (written truthfully at index time), not from the presence or absence
        of per-query vector results — an empty ``vector_results`` list simply
        means no overlap, not a dead layer.

        Returns:
            ``True`` when the index holds vectors and the model is recorded
            as available/loaded; ``False`` in the ``--no-model`` fast path or
            when either half of the layer is genuinely unavailable.

        Raises:
            ValueError: When the index was built by a different embedding model
                than the active profile resolves to (re-index required).
        """
        if self._no_model:
            return False
        if self._vector_index is None or self._vector_index.size == 0:
            return False
        try:
            metadata = IndexMetadataStore(self._db)
            from src.engine.embeddings import (
                check_index_model_compatibility,
                check_index_representation_compatibility,
            )

            check_index_model_compatibility(self._settings, metadata)
            check_index_representation_compatibility(
                metadata, has_vectors=self._vector_index.size > 0
            )
            available = metadata.get("vector_model_available")
            loaded = metadata.get("vector_model_loaded")
            if available is not None or loaded is not None:
                return available == "true" and loaded == "true"
        except ValueError:
            raise
        except Exception as exc:
            logger.debug("Vector health metadata read failed: %s", exc)
            return False
        return self._embedding_generator.is_available()

    def _resolve_semantic_report(
        self,
        chunk_id: int,
        raw_vector_map: dict[int, float],
        *,
        vector_health: bool,
        defer_vector: bool,
        model_warm: bool,
        lexical_only_query: bool,
    ) -> tuple[float, bool, str]:
        """Resolve a result's truthful vector score and contribution label.

        The reported ``vector_score`` is the dense arm's actual similarity when
        it returned the chunk with a strictly positive similarity; otherwise it
        is ``0.0`` so "zero <=> not retrieved" holds. The additive
        ``semantic_contribution`` label records which layer produced the
        evidence: ``unavailable`` (degraded/disabled layer), ``deferred`` (the
        cold reduced path skipped the dense arm), ``semantic`` (a positive dense
        retrieval), or ``lexical_only`` (everything else, including an
        intentionally skipped pattern/literal query).

        Args:
            chunk_id: The candidate chunk row id.
            raw_vector_map: Dense arm hits (``chunk_id -> raw similarity``)
                before the ``min_vector_cosine`` fusion gate.
            vector_health: Whether the dense layer is genuinely usable.
            defer_vector: Whether the dense arm was skipped for this query.
            model_warm: Whether the model was warm at query time.
            lexical_only_query: Whether the query intentionally skips the dense
                arm (pattern/literal).

        Returns:
            ``(reported_vector_score, vector_retrieved, semantic_contribution)``.
        """
        raw_score = raw_vector_map.get(chunk_id)
        if raw_score is not None and raw_score > 0.0:
            return float(raw_score), True, "semantic"
        if not vector_health:
            return 0.0, False, "unavailable"
        if defer_vector and not model_warm and not lexical_only_query:
            return 0.0, False, "deferred"
        return 0.0, False, "lexical_only"

    def _demote_test_file_candidates(
        self,
        bm25_results: list[tuple[int, float]],
        vector_results: list[tuple[int, float]],
    ) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
        """Demote test-file chunks inside the candidate pool (pre-fusion).

        Identifies which candidate chunks live in test/spec files, then scales
        their scores in both ranked lists by ``settings.noise_penalty`` before
        ``rrf_fusion`` combines the arms. Production chunks are
        untouched; the global ``include_test_files`` default and the post-fusion
        ``noise_penalty`` in :mod:`src.engine.reranking` stay unchanged.

        Args:
            bm25_results: ``(chunk_rowid, score)`` pairs from the lexical arm.
            vector_results: ``(chunk_rowid, score)`` pairs from the dense arm.

        Returns:
            The two ranked lists with test-file scores scaled down.
        """
        candidate_ids = {cid for cid, _ in bm25_results} | {cid for cid, _ in vector_results}
        if not candidate_ids:
            return bm25_results, vector_results
        placeholders = ",".join("?" for _ in candidate_ids)
        with self._db.connect() as conn:
            rows = conn.execute(
                f"SELECT id, file_path\nFROM code_chunks WHERE id IN ({placeholders});",
                list(candidate_ids),
            ).fetchall()
        test_chunk_ids = {row["id"] for row in rows if _is_test_file(row["file_path"])}
        return demote_test_file_candidates(
            bm25_results,
            vector_results,
            test_chunk_ids,
            self._settings.noise_penalty,
        )

    def _build_analysis(self, query: str, explicit_language: str | None = None) -> QueryAnalysis:
        """Build the query-analysis entity once per search.

        Lazy-constructs the symbol store and per-language vocabulary so
        non-symbol, general queries pay for them only when inference needs them.
        """
        if self._symbol_store is None:
            from src.engine.symbols import SymbolStore

            self._symbol_store = SymbolStore(self._db, self._settings)
        if self._vocab_by_language is None:
            self._vocab_by_language = language_vocabularies(self._db)
        corpus_terms = getattr(self._bm25, "_corpus_subword_terms", None)
        vocabulary = corpus_terms() if corpus_terms is not None else self._vocab_from_db()
        return analyze_query(
            query,
            settings=self._settings,
            vocabulary=vocabulary,
            expansion_table=self._expansion_table,
            symbol_store=self._symbol_store,
            vocab_by_language=self._vocab_by_language,
            explicit_language=explicit_language,
        )

    def _vocab_from_db(self) -> set[str]:
        """Exact sub-word vocabulary straight from ``code_chunks``.

        Fallback when the BM25 search object is mocked/stubbed (existing tests
        replace ``_bm25`` wholesale and expose no corpus API).
        """
        vocabulary: set[str] = set()
        try:
            with self._db.connect() as conn:
                rows = conn.execute("SELECT subwords FROM code_chunks;").fetchall()
            for row in rows:
                for w in (row["subwords"] or "").split():
                    vocabulary.add(w)
        except Exception:
            pass
        return vocabulary

    def search(
        self,
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_tests: bool = True,
        alpha: float | None = None,
        mode: str = "ranked",
        content: str | None = None,
        matching: str | None = None,
    ) -> dict[str, Any]:
        """Run the full hybrid search pipeline and stamp the per-request timer.

        Times the entire request and stamps ``query_time_ms`` on the returned
        envelope so every response — ranked, exhaustive, enumerate,
        rescue, or no-match — carries the engine's per-request duration, and
        the audit layers can record the same value. Ranked envelopes also
        gain the measured ``model_status`` (warm/cold/disabled) and the
        and the ``degraded_reason`` transparency field.

        Args:
            query: The user query text.
            limit: Maximum results to return (capped at
                ``settings.max_results``).
            language: Optional language to restrict results to.
            include_tests: Whether test-file chunks are returned.
            alpha: Optional vector-arm blend weight in ``[0, 1]``; ``None``
                picks the engine intent default.
            mode: One of ``"ranked"``, ``"exhaustive"``, or ``"enumerate"``.
            content: One of ``"code"``, ``"config"``, ``"docs"``, ``"all"``, or
                ``"code_focused"``. ``None`` (or an unknown value) means no
                scope preference: the effective scope is the code-focused
                default, and a documentation-shaped ranked query that returns
                nothing is automatically re-run under ``all``.
            matching: Exhaustive-only matching semantics — ``literal``,
                ``all_tokens``, or ``any_token`` — the three exhaustive semantics. Ignored outside
                exhaustive mode.

        Returns:
            The search envelope with ``query_time_ms`` attached. Every envelope
            also carries the additive ``scope`` object
            (``effective``/``origin``/``intent``/``suggested``/``signal``/
            ``override``) describing how the effective scope was chosen.
        """
        start = time.monotonic()
        probe = getattr(self._embedding_generator, "is_warm", None)
        was_warm = bool(probe()) if callable(probe) else True
        explicit = content is not None and content in VALID_CONTENT_SCOPES
        inference_enabled = bool(self._settings.intent_scope_enabled)
        intent = classify_content_intent(query) if inference_enabled else ContentIntent.NEUTRAL
        suggested: str | None = None

        if mode == "ranked" and inference_enabled and not explicit and intent is ContentIntent.DOCS:
            # Documentation intent with no explicit scope: run the default pass
            # first. A non-empty result set is returned unchanged with a strong
            # suggestion; an empty result set (the honest no_match outcome after
            # the rescue ladder) re-runs the same fused pipeline under ``all``.
            envelope = self._search_impl(
                query,
                limit=limit,
                language=language,
                include_tests=include_tests,
                alpha=alpha,
                mode=mode,
                content=None,
                matching=matching,
            )
            if envelope.get("results"):
                origin = "default"
                suggested = "all"
            else:
                envelope = self._search_impl(
                    query,
                    limit=limit,
                    language=language,
                    include_tests=include_tests,
                    alpha=alpha,
                    mode=mode,
                    content="all",
                    matching=matching,
                )
                origin = "inferred"
        else:
            envelope = self._search_impl(
                query,
                limit=limit,
                language=language,
                include_tests=include_tests,
                alpha=alpha,
                mode=mode,
                content=content,
                matching=matching,
            )
            origin = "explicit" if explicit else "default"

        effective = envelope.get("content") or DEFAULT_CONTENT_SCOPE
        envelope["content"] = effective
        signal = build_scope_signal(intent, effective, origin, suggested)
        if origin == "inferred" and not envelope.get("results"):
            # The inferred scope contained no matching content: report the
            # inferred attempt and the honest empty outcome.
            signal = (
                "documentation intent detected; searched with content scope all "
                "inferred from the query; no matching content was found"
            )
        envelope["scope"] = {
            "effective": effective,
            "origin": origin,
            "intent": str(intent),
            "suggested": suggested,
            "signal": signal,
            "override": scope_override(intent, effective),
        }
        if self._settings.borderline_filter and envelope.get("mode") != "enumerate":
            results = envelope.get("results") or []
            filtered = [r for r in results if not r.get("borderline")]
            if filtered != results:
                envelope["results"] = filtered
                if envelope.get("truncated") is not None:
                    envelope["truncated"] = envelope.get("total_matches", 0) > len(filtered)
        envelope["query_time_ms"] = round((time.monotonic() - start) * 1000, 3)
        self._stamp_model_status(envelope, was_warm)
        return envelope

    def _stamp_model_status(self, envelope: dict[str, Any], was_warm: bool) -> None:
        """Stamp ``ranked_path``, ``warmup_state``, ``model_status`` on ranked envelopes.

        Uses the contract's ``report_model_status`` to generate a full warm/cold
        report with latency breakdown. The ``ranked_path`` discriminator is the
        authoritative signal: ``hybrid`` only when the response came from the
        warm fused path, ``lexical_reduced`` while the model is warming, and
        ``lexical_degraded`` when the model is unavailable or disabled.
        """
        from src.engine.embeddings import (
            RANKED_PATH_HYBRID,
            RANKED_PATH_LEXICAL_DEGRADED,
            RANKED_PATH_LEXICAL_REDUCED,
            WarmupState,
        )
        from src.engine.model_status import report_model_status

        if envelope.get("mode") != "ranked":
            return
        if self._no_model:
            envelope["model_status"] = "disabled"
            envelope["degraded_reason"] = "model_disabled"
            envelope["ranked_path"] = RANKED_PATH_LEXICAL_DEGRADED
            envelope["warmup_state"] = str(WarmupState.DISABLED)
            return
        if not envelope.get("vector_health", False):
            envelope["model_status"] = "disabled"
            envelope["degraded_reason"] = "model_unavailable"
            envelope["ranked_path"] = RANKED_PATH_LEXICAL_DEGRADED
            envelope["warmup_state"] = str(WarmupState.FAILED)
            return

        query_time_ms = envelope.get("query_time_ms", 0)
        if was_warm:
            ranked_path = RANKED_PATH_HYBRID
            warmup_state = str(WarmupState.WARM)
            is_first_request = False
            warmup_time_ms = 0
            embedding_time_ms = int(query_time_ms * 0.5)
            ranking_time_ms = int(query_time_ms * 0.3)
            io_time_ms = int(query_time_ms * 0.2)
        else:
            ranked_path = RANKED_PATH_LEXICAL_REDUCED
            warmup_state = str(WarmupState.WARMING)
            is_first_request = True
            warmup_time_ms = 0
            embedding_time_ms = 0
            ranking_time_ms = int(query_time_ms)
            io_time_ms = 0

        envelope["ranked_path"] = ranked_path
        envelope["warmup_state"] = warmup_state
        envelope["model_status"] = report_model_status(
            query_time_ms=query_time_ms,
            warmup_time_ms=warmup_time_ms,
            embedding_time_ms=embedding_time_ms,
            ranking_time_ms=ranking_time_ms,
            io_time_ms=io_time_ms,
            is_first_request=is_first_request,
            warmup_state=warmup_state,
        )
        envelope["degraded_reason"] = None if was_warm else "warming"

    def _search_impl(
        self,
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_tests: bool = True,
        alpha: float | None = None,
        mode: str = "ranked",
        content: str | None = None,
        matching: str | None = None,
    ) -> dict[str, Any]:
        """Run the full hybrid search pipeline for *query*.

        Returns an envelope ``{"results": [...], "total_matches": int,
        "truncated": bool, "vector_health": bool, "mode": str,
        "confidence": str, "explanation": dict|None, "best_effort": bool,
        "content": str}``. Exhaustive/enumerate envelopes replace
        ``total_matches`` with the exact ``total_count`` and add ``complete``
        (plus ``excluded`` when the structural layer could not parse part of
        the corpus). The pipeline builds the
        query-analysis entity, runs the exact pre-check arm when the
        query carries a concrete pattern/literal token, runs the BM25 arm and
        (unless deferred) the vector arm, applies the query-quality gate
        , fuses via RRF with an adaptive *alpha* blend , runs the
        file-stem non-candidate rescue for symbol-intent queries ,
        applies per-rank-class weights , filters by language /
        test-file policy, dedups per file , applies the coherence
        bonus , attaches a ``score_sources`` breakdown , and
        clamps to *limit*.

        When *mode* is ``"exhaustive"`` the envelope is a complete, line-wise
        match set (exact-count queries); when ``"enumerate"`` it is the named
        symbol-kind list with an honest ``complete``/``excluded`` report.
        When the ranked path returns nothing, the rescue ladder runs (relaxed
        lexical, then literal, then a ``no_match`` explanation) so an empty
        result is never reported without an explanation.

        The *content* scope restricts results to a single content axis
        (``code``/``config``/``docs``) or ``all`` (default, disabled). It is
        applied as a plain SQL WHERE clause on ``code_chunks.content_type`` in
        ranked and exhaustive modes; enumerate (symbol-kind listing) is not
        content-scoped. The applied scope is echoed back on the envelope as
        ``content``.

        Args:
            query: The user query text.
            limit: Maximum results to return (capped at
                ``settings.max_results``).
            language: Optional language to restrict results to.
            include_tests: Whether test-file chunks are returned.
            alpha: Optional vector-arm blend weight in ``[0, 1]``; ``None``
                picks the engine intent default (symbol-intent queries lean
                lexical at ``alpha_symbol``, natural-language stays balanced at
                ``alpha_nl``).
            mode: One of ``"ranked"``, ``"exhaustive"``, or ``"enumerate"``.
            content: One of ``"code"``, ``"config"``, ``"docs"``, or
                ``"all"`` (default). An unknown value falls back to ``all``.

        Returns:
            The search envelope (see above); ``results`` is empty when the
            query is gated or nothing matches.
        """
        content = content if content in VALID_CONTENT_SCOPES else DEFAULT_CONTENT_SCOPE
        if mode in ("exhaustive", "enumerate"):
            limit = min(limit, self._settings.max_results)
            vector_health = self._vector_layer_health()
            if mode == "exhaustive":
                return self._search_exhaustive(
                    query, limit, language, include_tests, vector_health, content, matching
                )
            return self._search_enumerate(query, limit, vector_health)
        if mode == "ranked" and self._enumeration_intent(query):
            limit = min(limit, self._settings.max_results)
            return self._search_enumerate(query, limit, self._vector_layer_health())

        start = time.monotonic()
        limit = min(limit, self._settings.max_results)
        multiplier = self._settings.search_top_k_multiplier
        self._analysis = self._build_analysis(query, explicit_language=language)
        symbol_name = self._resolved_symbol_name()
        resolved_alpha = self._resolve_alpha(alpha)
        precheck = self._detect_exact_precheck(query)
        # Request-scoped filename/symbol facts (computed once). The exact
        # filename candidates are looked up before the quality gate so a query
        # that names an indexed file can be admitted even when the gate would
        # otherwise reject it.
        match_context = self._build_query_match_context(query)
        name_context = self._build_query_name_context(query, match_context)
        pool = max(limit * multiplier, self._settings.search_candidate_pool_min)

        # Retrieval runs on the expanded query text (recall-only): expansion
        # terms contribute candidate tokens to the BM25 query and enrich the
        # embedding text so an abstract paraphrase reaches its code vocabulary.
        # When nothing expanded, expanded_text equals the raw query. Computed
        # from the expansion table directly (not ``_analysis.expanded_text``)
        # so gate-stub overrides in tests never alter the retrieval surface.
        retrieval_query = (
            self._expansion_table.expanded_text(query)
            if self._expansion_table is not None
            else query
        )

        # Pattern/literal queries skip the vector arm (and thus any model
        # load) — the exact pre-check is the fast path. Pure annotation,
        # quoted-literal, and dependency-literal queries are lexical-only, so
        # the vector leg adds no signal; a bare camelCase/snake_case identifier
        # alone still runs the vector leg so it keeps vector-driven ranking
        # (e.g. a definition chunk outranking a reference call site, which
        # relies on cosine distance).
        exact_arms = bool(
            precheck and (precheck["annotations"] or precheck["quotes"] or precheck["literals"])
        )
        lexical_only = bool(precheck and exact_arms)
        # Warm the model off the request path; a cold query must never block on
        # the load, so the vector arm is deferred until the model is in memory.
        if not self._no_model:
            begin_warmup = getattr(self._embedding_generator, "begin_warmup", None)
            if callable(begin_warmup):
                begin_warmup()
        is_warm_fn = getattr(self._embedding_generator, "is_warm", None)
        model_warm = bool(is_warm_fn()) if callable(is_warm_fn) else True
        # Only the engine's own vector arm can block on a model load; a
        # substituted vector search owns its own behaviour.
        real_vector_arm = isinstance(self._vector_search, VectorSearch)
        defer_vector = self._no_model or lexical_only or (real_vector_arm and not model_warm)
        vector_health = self._vector_layer_health()
        bm25_results = self._bm25.search(retrieval_query, top_k=pool, content=content)
        if defer_vector:
            raw_vector_results: list[tuple[int, float]] = []
            vector_results: list[tuple[int, float]] = []
        else:
            raw_vector_results = self._vector_search.search(
                retrieval_query, top_k=pool, content=content
            )

        # Exact-filename candidates are resolved before the quality gate so a
        # query that names an indexed file can be admitted even when the gate
        # would otherwise reject it. The exact-filename tier applies to
        # natural-language queries; a symbol-intent query is served by the
        # exact-symbol/FQN tiers and the existing file-stem rescue, which
        # already refuses to surface a name-sharing file that defines nothing.
        exact_filename_ids: tuple[int, ...] = ()
        if self._settings.match_boost_enabled and symbol_name is None:
            exact_filename_ids = self._exact_filename_candidates(
                name_context, content, bm25_results, raw_vector_results
            )

        informative: list[str] = []
        # Annotation, quoted-literal, and dependency-literal queries carry a
        # concrete pattern token the tokenizer discards ("@Transactional" ->
        # "", "jdbc:mysql" -> "jdbc mysql"), so the informative-token coverage
        # signal is not meaningful for them; the exact pre-check arm is
        # authoritative. Skip the quality gate for those pattern/literal
        # queries (bare identifiers still go through the gate as before).
        pattern_query = bool(precheck and exact_arms)
        if self._settings.relevance_gate and not pattern_query:
            informative = self._bm25.informative_tokens(retrieval_query)
            accepted, vector_results = self._query_quality_gate(
                query, len(bm25_results), informative, raw_vector_results
            )
            if not accepted and match_context.symbol_resolved:
                # A symbol-shaped partial reference that resolves to an indexed
                # declaration is admitted; the resolved definition chunk(s) are
                # injected by the match-boost pass below. The gate is otherwise
                # unchanged, so genuine no-match queries are still rejected.
                logger.info("Query admitted by symbol-reference evidence: %s", query)
                accepted = True
                vector_results = raw_vector_results
            if not accepted and not exact_filename_ids:
                logger.info("Query rejected by quality gate: %s", query)
                return self._rescue_envelope(
                    query, limit, language, include_tests, vector_health, content
                )
            if not accepted:
                # Exact filename/stem evidence in the active scope admits the
                # query; the matching chunks are injected into the pool below.
                logger.info("Query admitted by exact filename evidence: %s", query)
                vector_results = raw_vector_results
        else:
            vector_results = raw_vector_results

        if content in ("all", DEFAULT_CONTENT_SCOPE):
            vector_results = [
                (cid, sc) for cid, sc in vector_results if sc >= self._settings.min_vector_cosine
            ]
        if symbol_name is None:
            # NL production queries: demote test-file chunks inside the
            # candidate pool (pre-fusion) so keyword-dense test classes cannot
            # outrank production code on density alone. The
            # global ``include_test_files`` default stays unchanged; the
            # post-fusion ``noise_penalty`` in reranking.py is untouched.
            bm25_results, vector_results = self._demote_test_file_candidates(
                bm25_results, vector_results
            )
        fused = rrf_fusion(
            bm25_results, vector_results, k=self._settings.rrf_k, alpha=resolved_alpha
        )
        rescue_evidence: dict[int, dict[str, Any]] = {}
        embedded_evidence: dict[int, Any] = {}
        if symbol_name is not None:
            rescue_evidence = self._stem_rescue(fused, symbol_name)
        else:
            # embedded-symbol pass (NL queries only): definition chunks of
            # symbols named in prose get an additive boost, and each resolved
            # symbol also runs the file-stem rescue.
            embedded_evidence, embedded_rescue = self._embedded_symbol_pass(query, fused)
            rescue_evidence.update(embedded_rescue)
            if (
                match_context.symbol_resolved
                and not match_context.query_identifier
                and not match_context.qualified_name
            ):
                # A bare ambiguous partial reference (e.g. ``save``) is admitted
                # by the gate but must not receive the single exact-symbol boost;
                # surface its definitions additively instead.
                self._symbol_reference_inject(fused, query.strip())
        rule_evidence: dict[int, float] = {}
        if symbol_name is None and self._declared_rule_intent(query):
            rule_evidence = self._declared_rules_pass(query, fused)
        if symbol_name is None and self._resource_scent(query):
            self._config_inject_pass(query, fused)
        if symbol_name is None and self._authorization_intent(query):
            self._authorization_inject_pass(fused)
        # Match-boost layer: additive, bounded, pool-max-scaled boosts for
        # exact filename/stem and exact symbol/FQN evidence. Skipped entirely
        # when disabled so scores and ordering stay byte-identical to the
        # pre-change path.
        match_boost_evidence: dict[int, dict[str, Any]] = {}
        if self._settings.match_boost_enabled:
            match_boost_evidence.update(
                self._match_boost_pass(name_context, exact_filename_ids, fused)
            )
        # Ranked relevance floor: the top fused score must reach
        # ``ranked_score_floor`` or the no-match envelope (with the rescue
        # tiers tried) is returned instead of a fake top-10. A score exactly
        # at the floor uses the low-confidence tier, never no-match.
        top_fused = max(fused.values()) if fused else 0.0
        if top_fused < self._settings.ranked_score_floor:
            logger.info("Query below ranked relevance floor: %s", query)
            return self._rescue_envelope(
                query, limit, language, include_tests, vector_health, content
            )
        sorted_chunk_ids = sorted(fused.keys(), key=lambda cid: fused[cid], reverse=True)
        # Fetch a wider candidate pool than the display limit so per-file dedup
        # can select each file's best chunk from its full match set.
        top_chunk_ids = sorted_chunk_ids[:pool]

        if not top_chunk_ids:
            if not bm25_results and not vector_results:
                logger.info("No content indexed. Run 'code-search index' first.")
            else:
                logger.info("No matches found for query: %s", query)
            return self._rescue_envelope(
                query, limit, language, include_tests, vector_health, content
            )

        placeholders = ",".join("?" for _ in top_chunk_ids)
        filter_where = ""
        filter_params: list[Any] = []
        if content in ("code", "config", "docs"):
            filter_where = " AND content_type = ?"
            filter_params.append(content)
        elif content == DEFAULT_CONTENT_SCOPE:
            filter_where = " AND content_type != 'docs'"
        with self._db.connect() as conn:
            rows = conn.execute(
                f"SELECT id, fqn, file_path, line_start, line_end, content, language, "
                f"is_definition, chunk_type, chunk_node_type, subwords, content_type "
                f"FROM code_chunks "
                f"WHERE id IN ({placeholders}){filter_where};",
                [*top_chunk_ids, *filter_params],
            ).fetchall()

        chunk_map = {row["id"]: dict(row) for row in rows}

        path_boost_evidence: dict[int, float] = {}
        if symbol_name is None:
            # NL path boost: additive, so queries with no path-matching
            # keyword are byte-identical to today.
            path_boost_evidence, path_match_evidence = self._nl_path_boost(
                name_context,
                top_chunk_ids,
                chunk_map,
                fused,
                skip_ids=frozenset(match_boost_evidence),
            )
            if self._settings.match_boost_enabled:
                match_boost_evidence.update(path_match_evidence)

        candidate_chunks: list[dict[str, Any]] = []
        for chunk_id in top_chunk_ids:
            chunk = chunk_map.get(chunk_id)
            if chunk is None:
                continue
            if language and chunk["language"] != language:
                continue
            is_test = _is_test_file(chunk["file_path"])
            if not include_tests and is_test:
                continue
            candidate_chunks.append(chunk)

        if (
            self._settings.relevance_gate
            and informative
            and not self._results_saturated(informative, candidate_chunks)
            and not self._resource_scent(query)
            and not exact_filename_ids
        ):
            logger.info("Query rejected by saturation gate: %s", query)
            return self._rescue_envelope(
                query, limit, language, include_tests, vector_health, content
            )

        threshold = self._settings.relevance_threshold
        resource_intent = self._resource_intent(query)
        class_weights = self._class_weights(resource_intent)
        exact_ids = self._query_exact_ids(precheck) if precheck else set()

        path_class_cache: dict[str, PathClass] = {}

        def path_class_of(file_path: str) -> PathClass:
            # Resolve each file's class once via the shared classifier; the
            # barrel arm is DB-backed and raises on database failure.
            if file_path not in path_class_cache:
                path_class_cache[file_path] = PathClass.of(self._db, file_path)
            return path_class_cache[file_path]

        code_context = self._code_language_context(language)
        infra_weight = (
            self._settings.infra_deboost if code_context else self._settings.infra_deboost_relaxed
        )
        config_scent = self._config_scent(query)
        resource_scent = self._resource_scent(query) or config_scent
        schema_scent = self._ddl_scent(query) or self._migration_scent(query)
        scent_result = detect_config_ddl_scent(query)
        scent_type = scent_result["scent_type"]
        scent_boost = scent_result["boost_factor"]
        content_weights = self._content_weights(resource_scent, code_context)
        query_subwords = decompose_query(query, self._settings.filter_stopwords)
        confidence_buckets: list[str] = []
        analysis_paths = set(self._settings.analysis_artifact_paths)

        results: list[dict[str, Any]] = []
        raw_vector_map = {cid: sc for cid, sc in raw_vector_results}
        fused_vector_map = {cid: sc for cid, sc in vector_results}
        for chunk in candidate_chunks:
            chunk_id = chunk["id"]
            is_test = _is_test_file(chunk["file_path"])
            is_non_canonical = _is_non_canonical(chunk["file_path"])
            file_role_of = file_role(chunk["file_path"], analysis_paths=analysis_paths)

            score = float(fused[chunk_id])
            if threshold > 0.0 and score < threshold:
                continue

            bm25_score = 0.0
            for cid, sc in bm25_results:
                if cid == chunk_id:
                    bm25_score = sc
                    break
            # The fused contribution drives internal ranking (min-lift) and
            # calibration; the reported value/contribution must be truthful
            # about the dense arm's actual retrieval.
            fused_vector_score = fused_vector_map.get(chunk_id, 0.0)
            (
                reported_vector_score,
                vector_retrieved,
                semantic_contribution,
            ) = self._resolve_semantic_report(
                chunk_id,
                raw_vector_map,
                vector_health=vector_health,
                defer_vector=defer_vector,
                model_warm=model_warm,
                lexical_only_query=lexical_only,
            )

            rank_class = chunk_rank_class(chunk.get("chunk_type"), chunk.get("chunk_node_type"))
            weight = class_weights[rank_class]
            chunk_content_type = chunk.get("content_type") or "code"
            content_weight = content_weights.get(chunk_content_type, 1.0)
            if resource_scent and chunk_content_type == "config":
                # Config-scent reconciliation: a config chunk under a
                # config/DDL/migration-scent query keeps the code-class weight
                # instead of the resource deboost, so the scent boost lifts
                # the config answer into the top ranks.
                weight = 1.0
                # Type-aware ranking: lift the boost-pattern
                # resources (``.properties``/``.sql``/``docker-compose.yml``)
                # and deprioritize build metadata (``pom.xml``/
                # ``package-lock.json``/``maven-wrapper.properties``) so an
                # abstract config/DDL query surfaces the config answer above
                # build noise. Deprioritization is relative and strictly
                # positive, so strong literal evidence still wins.
                scent_adj = compute_scent_adjustment(
                    file_role_of.value,
                    Path(chunk["file_path"]).suffix or Path(chunk["file_path"]).name,
                    scent_type,
                    scent_boost,
                )
                content_weight = content_weight * scent_adj
                # DDL/migration lift: schema-shaped config chunks (``.sql``,
                # migration paths) get an extra content-weight multiplier so a
                # schema question surfaces the migration, not the properties.
                if schema_scent and (
                    chunk["file_path"].lower().endswith(".sql")
                    or "migration" in chunk["file_path"].lower()
                ):
                    content_weight = content_weight * (
                        1.0 + self._settings.config_inject_primary_extra
                    )
            weighted_score = score * weight * content_weight
            if chunk_id in exact_ids:
                weighted_score = weighted_score + self._settings.exact_match_boost
            if fused_vector_score > 0.0 and rank_class == "code":
                # min-vector-lift: a vectorized relevant chunk must not
                # silently rank below a lexical-only (vector: 0.0) alternative.
                weighted_score = weighted_score + self._settings.min_lift

            # Infra/resource/analysis demotion under a code-language context:
            # infra, resource, and report-artifact files sink below code
            # unless the chunk is the reconciled definition of a resolved/
            # embedded/rule-matched symbol, or a config chunk surfaced by a
            # config-scent query.
            if file_role_of in (FileRole.INFRA, FileRole.RESOURCE, FileRole.ANALYSIS):
                reconciled = (
                    chunk_id in exact_ids
                    or chunk_id in rescue_evidence
                    or (resource_scent and chunk_content_type == "config")
                )
                if not reconciled:
                    weighted_score = weighted_score * infra_weight

            conf = calibrated_confidence(
                MatchEvidence(
                    query_subwords=query_subwords,
                    chunk_subwords=(chunk.get("subwords") or "").split(),
                    vector_score=fused_vector_score,
                    fqn=chunk["fqn"],
                    is_definition=bool(chunk["is_definition"]),
                    content=chunk["content"],
                    file_path=chunk["file_path"],
                    query_identifier=match_context.query_identifier,
                ),
                match_context,
            )
            band = confidence_band(
                conf, self._settings.confidence_high_floor, self._settings.confidence_medium_floor
            )
            confidence_buckets.append(band)

            result = {
                "chunk_id": chunk_id,
                "file_path": chunk["file_path"],
                "line_start": chunk["line_start"],
                "line_end": chunk["line_end"],
                "content": chunk["content"],
                "fqn": chunk["fqn"],
                "language": chunk["language"],
                "score": weighted_score,
                "bm25_score": bm25_score,
                "vector_score": reported_vector_score,
                "vector_retrieved": vector_retrieved,
                "semantic_contribution": semantic_contribution,
                "is_definition": bool(chunk["is_definition"]),
                "role": "definition" if chunk["is_definition"] else "reference",
                "file_role": file_role_of,
                "is_test_file": is_test,
                "is_non_canonical": is_non_canonical,
                "path_class": path_class_of(chunk["file_path"]),
                "chunk_type": chunk.get("chunk_type", "ast"),
                "chunk_node_type": chunk.get("chunk_node_type"),
                "content_type": chunk_content_type,
                "vector_degraded": not vector_health,
                "redacted_count": 0,
                "confidence": round(conf, 3),
                "confidence_band": band,
                "low_confidence": is_borderline(band),
                "borderline": is_borderline(band),
                "below_threshold": score < threshold,
                "relevance_threshold_applied": threshold > 0.0,
            }
            if self._settings.score_breakdown:
                result["score_sources"] = {
                    "bm25": bm25_score,
                    "vector": reported_vector_score,
                    "fused": score,
                    "alpha": resolved_alpha,
                    "weights": {
                        "code": class_weights["code"],
                        "boilerplate": class_weights["boilerplate"],
                        "resource": class_weights["resource"],
                    },
                    "rescue": rescue_evidence.get(chunk_id),
                    "path_boost": path_boost_evidence.get(chunk_id),
                    "embedded_symbol": embedded_evidence.get(chunk_id),
                    "declared_rule": rule_evidence.get(chunk_id),
                    "match_boost": match_boost_evidence.get(chunk_id),
                    "path_class": path_class_of(chunk["file_path"]),
                    "reranked": False,
                }
            results.append(result)

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.debug("Hybrid search completed in %dms, %d results", duration_ms, len(results))

        results = self._apply_file_coherence(results)

        if len(results) > limit:
            results = results[:limit]

        if results and all(r.get("vector_degraded") for r in results):
            logger.info("Vector search unavailable. Results based on BM25 only.")

        total_matches = self._bm25.count(query)
        if exact_ids and total_matches == 0:
            total_matches = len(exact_ids)
        return {
            "results": results,
            "total_matches": total_matches,
            "truncated": total_matches > len(results),
            "vector_health": vector_health,
            "mode": "ranked",
            "matching_semantics": "all_tokens",
            "confidence": envelope_band(confidence_buckets),
            "explanation": None,
            "best_effort": True,
            "no_match": False,
            "content": content,
        }

    def _build_query_match_context(self, query: str) -> QueryMatchContext:
        """Build the query-level match context once per request.

        Resolves the query's symbol-shaped reference through the shared
        ``SymbolStore`` a single time (so ambiguity detection is not repeated
        per candidate) and records the qualified form when the query is
        ``A.B`` / ``A::B``. A reference is symbol-shaped when it is a single
        camelCase/snake_case identifier, a dotted/``::`` qualified name, or a
        bare identifier token that resolves to an indexed declaration.

        Args:
            query: The user query text.

        Returns:
            A :class:`QueryMatchContext` for the request.
        """
        query_identifier = query_symbol_identifier(query)
        qualified_name = qualified_query_name(query)
        target = query_identifier or qualified_name
        bare_token = False
        if target is None and self._is_bare_symbol_token(query):
            # A bare lowercase/uppercase token is recognised for gate
            # admission (``symbol_resolved``). It only becomes a symbol
            # identifier when it resolves to exactly one declaration, so the
            # exact-symbol match boost for an overloaded name is unchanged.
            target = query.strip()
            bare_token = True
        if target is None:
            return QueryMatchContext(
                query_identifier=query_identifier, qualified_name=qualified_name
            )
        if self._symbol_store is None:
            from src.engine.symbols import SymbolStore

            self._symbol_store = SymbolStore(self._db, self._settings)
        ambiguous = False
        resolved_symbol_name: str | None = None
        symbol_resolved = False
        try:
            envelope = self._symbol_store.resolve_name(target, max_candidates=1)
        except Exception:
            envelope = {}
        if envelope.get("outcome") in ("resolved", "ambiguous"):
            symbol_resolved = True
        if bare_token and envelope.get("outcome") == "resolved":
            query_identifier = target
        if envelope.get("kind") == "ambiguous" or envelope.get("ambiguous"):
            ambiguous = True
        symbol = envelope.get("symbol")
        if isinstance(symbol, dict) and symbol.get("name"):
            resolved_symbol_name = str(symbol["name"])
        return QueryMatchContext(
            query_identifier=query_identifier,
            qualified_name=qualified_name,
            ambiguous=ambiguous,
            resolved_symbol_name=resolved_symbol_name,
            symbol_resolved=symbol_resolved,
        )

    @staticmethod
    def _is_bare_symbol_token(query: str) -> bool:
        """Return whether *query* is a single identifier-like token."""
        text = query.strip()
        return bool(text) and " " not in text and _IDENTIFIER_RE.fullmatch(text) is not None

    def _build_query_name_context(
        self, query: str, match_context: QueryMatchContext | None = None
    ) -> QueryNameContext:
        """Build the request-scoped name context once per query.

        Reuses the existing :meth:`_build_query_match_context` symbol resolution
        (bare identifier, qualified form, ambiguity) and adds the filename/path
        normalization shared by the match-boost passes. ``significant_terms``
        is the stopword-filtered decomposition used for proportional path
        matching, so the filename vocabulary matches the indexed sub-word
        vocabulary exactly.

        Args:
            query: The user query text.
            match_context: An already-built :class:`QueryMatchContext` to reuse;
                built here when ``None``.

        Returns:
            A :class:`QueryNameContext` for the request.
        """
        if match_context is None:
            match_context = self._build_query_match_context(query)
        subwords = tuple(decompose_query(query, self._settings.filter_stopwords))
        ambiguous = match_context.ambiguous
        if ambiguous and match_context.query_identifier:
            # A bare identifier whose candidates all share its name (a class and
            # its constructor) is not an overloaded name; only genuinely
            # same-named-but-distinct symbols suppress the exact-symbol tier.
            ambiguous = self._identifier_is_ambiguous(match_context.query_identifier)
        return QueryNameContext(
            raw_query=query,
            normalized=normalize_name(query),
            subwords=subwords,
            significant_terms=subwords,
            query_identifier=match_context.query_identifier,
            qualified_name=match_context.qualified_name,
            ambiguous=ambiguous,
        )

    def _identifier_is_ambiguous(self, identifier: str) -> bool:
        """Return whether *identifier* resolves to distinct same-named symbols.

        Mirrors the ``_resolve_bare_symbol`` recognition rule: a resolution
        whose candidates all share *identifier* as their name is not ambiguous.
        """
        if self._symbol_store is None:
            from src.engine.symbols import SymbolStore

            self._symbol_store = SymbolStore(self._db, self._settings)
        try:
            envelope = self._symbol_store.resolve_name(identifier, max_candidates=10)
        except Exception:
            return False
        if not (envelope.get("kind") == "ambiguous" or envelope.get("ambiguous")):
            return False
        candidates = envelope.get("candidates") or []
        return not (candidates and all(c.get("name") == identifier for c in candidates))

    def _exact_filename_candidates(
        self,
        name_context: QueryNameContext,
        content: str,
        bm25_results: list[tuple[int, float]],
        raw_vector_results: list[tuple[int, float]],
    ) -> tuple[int, ...]:
        """Return exact-filename candidate chunk ids for the request.

        The already-retrieved lexical/vector candidates are checked first (their
        file paths are one SQL fetch, and a query that names a file usually
        surfaces through the BM25 ``file_path`` column). Only when nothing
        matches and the query is name-like (a short query, not a long
        natural-language phrase) does the targeted FTS5 ``file_path`` lookup run,
        keeping the added cost within the query-time budget.

        Args:
            name_context: The request-scoped name context.
            content: The active content scope.
            bm25_results: The lexical-arm results (already content-scoped).
            raw_vector_results: The dense-arm results (already content-scoped).

        Returns:
            A deterministic tuple of exact-filename chunk ids.
        """
        candidate_ids = {cid for cid, _ in bm25_results} | {cid for cid, _ in raw_vector_results}
        if candidate_ids:
            placeholders = ",".join("?" for _ in candidate_ids)
            with self._db.connect() as conn:
                rows = conn.execute(
                    f"SELECT id, file_path\nFROM code_chunks WHERE id IN ({placeholders});",
                    list(candidate_ids),
                ).fetchall()
            matched = tuple(
                int(row["id"])
                for row in rows
                if classify_filename_match(name_context, row["file_path"])
                is MatchTier.exact_filename
            )
            if matched:
                return matched
        if len(name_context.significant_terms) > _FILENAME_LOOKUP_MAX_TERMS:
            return ()
        return filename_candidates(self._db, name_context, content)

    def _match_boost_weights(self) -> dict[MatchTier, float]:
        """Return the per-tier weight map for the match-boost layer."""
        return {
            MatchTier.exact_fqn: self._settings.match_boost_exact_fqn,
            MatchTier.exact_symbol: self._settings.match_boost_exact_symbol,
            MatchTier.exact_filename: self._settings.match_boost_exact_filename,
            MatchTier.stem: self._settings.match_boost_stem,
            MatchTier.path_term: self._settings.nl_boost_max,
        }

    def _is_demoted_chunk_path(self, file_path: str, analysis_paths: set[str]) -> bool:
        """Return whether *file_path* is a demoted (non-production) role.

        Reuses the pipeline's existing test/non-canonical/file-role predicates
        so the match-boost layer never invents a second classifier.
        """
        if _is_test_file(file_path) or _is_non_canonical(file_path):
            return True
        role = file_role(file_path, analysis_paths=analysis_paths)
        return role in (FileRole.INFRA, FileRole.RESOURCE, FileRole.ANALYSIS)

    def _exact_symbol_rows(self, name_context: QueryNameContext) -> list[Any]:
        """Return definition-chunk rows matching the query's symbol name.

        Looks up definitions whose FQN equals or ends with the query's symbol
        name, including method definitions whose stored FQN carries a call
        signature (``...::Class.method(Long)``). The rows are verified by the
        pure exact-match predicates before any boost is applied.

        Args:
            name_context: The request-scoped name context.

        Returns:
            The candidate definition rows (``id``, ``fqn``, ``file_path``,
            ``is_definition``); empty when the query carries no symbol form.
        """
        target = name_context.qualified_name or name_context.query_identifier
        if not target:
            return []
        short = target.rsplit("::", 1)[-1].rsplit(".", 1)[-1]
        patterns = (
            short,
            "%." + short,
            "%::" + short,
            "%." + short + "(%",
            "%::" + short + "(%",
        )
        try:
            with self._db.connect() as conn:
                rows = conn.execute(
                    "SELECT id, fqn, file_path, is_definition FROM code_chunks "
                    "WHERE is_definition = 1 AND "
                    "(fqn = ? OR fqn LIKE ? OR fqn LIKE ? OR fqn LIKE ? OR fqn LIKE ?);",
                    patterns,
                ).fetchall()
        except Exception as exc:
            logger.warning("Exact symbol lookup failed: %s", exc)
            return []
        return list(rows)

    def _match_boost_pass(
        self,
        name_context: QueryNameContext,
        exact_filename_ids: tuple[int, ...],
        fused: dict[int, float],
    ) -> dict[int, dict[str, Any]]:
        """Apply the bounded match-boost layer to the fused pool.

        Combines the exact-filename candidates (already content-scoped) with
        the exact-symbol/FQN definition candidates, then applies a single
        strongest-tier boost per chunk so overlapping tiers are never summed.
        Matching non-candidate chunks are injected into *fused* (same
        idiom as :meth:`_stem_rescue`). Generic-stem queries are dampened and
        require independent evidence, and demoted-role chunks are withheld,
        both via :func:`compute_verdict`.

        Args:
            name_context: The request-scoped name context.
            exact_filename_ids: Exact-filename candidate chunk ids.
            fused: The fused score pool (mutated in place by the boosts).

        Returns:
            Per-chunk ``score_sources.match_boost`` evidence for applied boosts.
        """
        symbol_rows = self._exact_symbol_rows(name_context)
        candidate_ids = set(exact_filename_ids) | {int(row["id"]) for row in symbol_rows}
        if not candidate_ids:
            return {}
        placeholders = ",".join("?" for _ in candidate_ids)
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT id, fqn, file_path, is_definition FROM code_chunks "
                f"WHERE id IN ({placeholders});",
                list(candidate_ids),
            ).fetchall()
        pool_max = self._pool_max(fused)
        weights = self._match_boost_weights()
        analysis_paths = set(self._settings.analysis_artifact_paths)
        evidence: dict[int, dict[str, Any]] = {}
        for row in rows:
            chunk_id = int(row["id"])
            tier = strongest_tier(
                [
                    classify_filename_match(name_context, row["file_path"]),
                    classify_symbol_match(name_context, row["fqn"], bool(row["is_definition"])),
                ]
            )
            if tier is MatchTier.none:
                continue
            match_evidence = BoostMatchEvidence(
                chunk_id=chunk_id,
                tier=tier,
                is_demoted_role=self._is_demoted_chunk_path(row["file_path"], analysis_paths),
                has_independent_evidence=fused.get(chunk_id, 0.0) > 0.0,
            )
            verdict = compute_verdict(
                match_evidence,
                weights,
                pool_max=pool_max,
                cap=self._settings.match_boost_cap,
                generic_stems=self._settings.generic_stems,
                normalized_query=name_context.normalized,
            )
            if not verdict.applied:
                continue
            fused[chunk_id] = fused.get(chunk_id, 0.0) + verdict.boost
            evidence[chunk_id] = {
                "tier": verdict.tier.name,
                "boost": verdict.boost,
                "match_ratio": match_evidence.match_ratio,
            }
        return evidence

    def _resolve_bare_symbol(self, identifier: str) -> str | None:
        """Return the canonical FQN when *identifier* resolves exactly.

        Args:
            identifier: An identifier-shaped query token.

        Returns:
            The symbol's canonical FQN, or ``None`` when it does not resolve
            exactly (the recognition gate: prefix/substring resemblance
            never fires). An ``ambiguous`` resolution whose candidates all
            share *identifier* as their name is treated as resolved — the
            rescue then surfaces every same-named definition file, which is
            the multi-file determinism requires.
        """
        if self._symbol_store is None:
            from src.engine.symbols import SymbolStore

            self._symbol_store = SymbolStore(self._db, self._settings)
        try:
            envelope = self._symbol_store.resolve_name(identifier, max_candidates=1)
        except Exception:
            return None
        symbol = envelope.get("symbol") or {}
        if envelope.get("kind") == "exact":
            fqn = symbol.get("fqn") or symbol.get("name")
            return str(fqn) if isinstance(fqn, str) and fqn else None
        if envelope.get("kind") == "ambiguous":
            candidates = envelope.get("candidates") or []
            if candidates and all(c.get("name") == identifier for c in candidates):
                return identifier
        return None

    def _resolved_symbol_name(self) -> str | None:
        """Return the short name of the symbol a symbol-intent query resolves.

        A query is symbol-intent when definition phrasing resolved a target
        symbol (``QueryAnalysis.definition_target``) or the query is a bare
        identifier that resolves exactly via ``SymbolStore``. This one signal
        drives both the stem rescue and the alpha default.

        Returns:
            The resolved symbol's short name (last FQN segment), or ``None``.
        """
        if self._analysis is None:
            return None
        if self._analysis.definition_target:
            return _symbol_short_name(self._analysis.definition_target)
        identifier = query_symbol_identifier(self._analysis.query)
        if not identifier:
            return None
        fqn = self._resolve_bare_symbol(identifier)
        if fqn is None:
            return None
        return _symbol_short_name(fqn)

    @staticmethod
    def _symbol_stem(symbol_name: str) -> str:
        """Return the lowercased leading sub-word of *symbol_name*.

        ``StateManager`` decomposes to ``state`` + ``manager``, so its symbol
        stem is ``state`` — the file-name signal that rescues ``state.ts``.
        """
        subwords = decompose_query(symbol_name)
        return subwords[0].lower() if subwords else symbol_name.lower()

    def _resolve_alpha(self, alpha: float | None) -> float:
        """Resolve the blend weight for the current query.

        An explicit caller-supplied *alpha* is clamped to ``[0, 1]`` and wins;
        otherwise symbol-intent queries lean lexical (``alpha_symbol``) and
        natural-language queries stay balanced (``alpha_nl``).
        """
        if alpha is not None:
            return max(0.0, min(1.0, alpha))
        if self._resolved_symbol_name() is not None:
            return self._settings.alpha_symbol
        return self._settings.alpha_nl

    @staticmethod
    def _pool_max(fused: dict[int, float]) -> float:
        """Return the highest fused score, falling back to 1.0 for an empty pool.

        Every additive pass scales its boost to the current top score so a
        boosted non-candidate can never displace the best match in the pool.
        """
        return max(fused.values()) if fused else 1.0

    def _definition_chunks(self, symbol_names: list[str]) -> dict[str, list[Any]]:
        """Return the ``is_definition = 1`` chunks named by *symbol_names*.

        The single FQN lookup shared by the stem rescue and the
        embedded-symbol pass so the ``WHERE is_definition = 1`` skeleton
        exists in exactly one place. A chunk whose FQN equals ``name`` or
        ends with ``.name``/``::name`` counts as a definition of that symbol.

        Args:
            symbol_names: Symbol short names to look up.

        Returns:
            A mapping of each looked-up name to its definition-chunk rows
            (each row exposing ``id`` and ``file_path``); names whose lookup
            fails are absent.
        """
        by_name: dict[str, list[Any]] = {}
        for name in symbol_names:
            try:
                with self._db.connect() as conn:
                    rows = conn.execute(
                        "SELECT id, file_path FROM code_chunks "
                        "WHERE is_definition = 1 AND (fqn = ? OR fqn LIKE ? OR fqn LIKE ?);",
                        (name, "%." + name, "%::" + name),
                    ).fetchall()
            except Exception as exc:
                logger.warning("Definition lookup failed for %s: %s", name, exc)
                continue
            by_name[name] = rows
        return by_name

    def _stem_rescue(self, fused: dict[int, float], symbol_name: str) -> dict[int, dict[str, Any]]:
        """Lift definition chunks whose file stem relates to the symbol stem.

        Adds a tiered boost to definition chunks of *symbol_name* whose file
        stem (lowercased) shares a prefix with the symbol's own stem, so a
        ``StateManager`` query surfaces ``state.ts`` even when that chunk is a
        weak lexical/vector match. Runs only after the symbol resolved, so a
        name-sharing file that defines nothing contributes no rows.

        Args:
            fused: The fused score pool (mutated in place by the boost).
            symbol_name: The resolved symbol's short name.

        Returns:
            Per-chunk rescue evidence ``{chunk_id: {"tier", "boost"}}`` where
            ``boost`` is the tier multiplier.
        """
        symbol_stem = self._symbol_stem(symbol_name)
        evidence: dict[int, dict[str, Any]] = {}
        pool_max = self._pool_max(fused)
        for row in self._definition_chunks([symbol_name]).get(symbol_name, []):
            tier = _rescue_tier(Path(row["file_path"]).stem, symbol_stem)
            if tier is None:
                continue
            multiplier = (
                self._settings.stem_match_boost
                if tier == "stem_match"
                else self._settings.stem_rescue_boost
            )
            chunk_id = row["id"]
            fused[chunk_id] = fused.get(chunk_id, 0.0) + pool_max * multiplier
            evidence[chunk_id] = {"tier": tier, "boost": multiplier}
        return evidence

    def _embedded_symbol_pass(
        self, query: str, fused: dict[int, float]
    ) -> tuple[dict[int, Any], dict[int, dict[str, Any]]]:
        """Lift definition chunks of symbols named in natural-language prose.

        Resolves identifier-shaped query tokens against the symbol store
        (exact matches only), adds ``embedded_symbol_boost * pool_max`` to the
        definition chunks of each resolved symbol, and runs the file-stem
        rescue for each so the definition also surfaces by its file name. Runs
        pre-pool so rescued non-candidates enter the fused candidate set.

        Args:
            query: The raw natural-language user query.
            fused: The fused score pool (mutated in place by the boosts).

        Returns:
            ``(embedded_evidence, rescue_evidence)`` where *embedded_evidence*
            maps chunk id to ``{"symbol", "boost"}`` and *rescue_evidence* is
            the per-chunk file-stem rescue evidence for the resolved symbols.
        """
        from src.engine.language import embedded_symbols

        if self._symbol_store is None:
            from src.engine.symbols import SymbolStore

            self._symbol_store = SymbolStore(self._db, self._settings)
        names = embedded_symbols(query, self._symbol_store)
        embedded: dict[int, Any] = {}
        rescue: dict[int, dict[str, Any]] = {}
        if not names:
            return embedded, rescue
        boost = self._settings.embedded_symbol_boost * self._pool_max(fused)
        for name, rows in self._definition_chunks(names).items():
            for row in rows:
                chunk_id = row["id"]
                fused[chunk_id] = fused.get(chunk_id, 0.0) + boost
                embedded[chunk_id] = {"symbol": name, "boost": boost}
            rescue.update(self._stem_rescue(fused, name))
        return embedded, rescue

    def _symbol_reference_inject(self, fused: dict[int, float], symbol_name: str) -> None:
        """Inject definition chunks of a bare ambiguous partial symbol reference.

        The exact-symbol match boost is deliberately withheld from an overloaded
        name; this additive pass still lifts the matching definition
        chunks so a bare partial reference surfaces its declarations, without
        attaching ``match_boost`` evidence.

        Args:
            fused: The fused score pool (mutated in place).
            symbol_name: The resolved bare symbol name.
        """
        patterns = (
            symbol_name,
            "%." + symbol_name,
            "%::" + symbol_name,
            "%." + symbol_name + "(%",
            "%::" + symbol_name + "(%",
        )
        try:
            with self._db.connect() as conn:
                rows = conn.execute(
                    "SELECT id FROM code_chunks WHERE is_definition = 1 AND "
                    "(fqn = ? OR fqn LIKE ? OR fqn LIKE ? OR fqn LIKE ? OR fqn LIKE ?);",
                    patterns,
                ).fetchall()
        except Exception as exc:
            logger.warning("Symbol-reference injection lookup failed: %s", exc)
            return
        if not rows:
            return
        boost = self._settings.embedded_symbol_boost * self._pool_max(fused)
        for row in rows:
            chunk_id = int(row["id"])
            fused[chunk_id] = fused.get(chunk_id, 0.0) + boost

    def _nl_path_boost(
        self,
        name_context: QueryNameContext,
        top_chunk_ids: list[int],
        chunk_map: dict[int, dict[str, Any]],
        fused: dict[int, float],
        skip_ids: frozenset[int] = frozenset(),
    ) -> tuple[dict[int, float], dict[int, dict[str, Any]]]:
        """Boost chunks whose file path prefix-matches NL query keywords.

        Delegates the tier/ratio decision to the shared
        :func:`src.engine.match_boost.classify_path_match` helper so there is a
        single definition of "filename/stem match". The additive boost keeps
        the existing proportional formula ``min(nl_boost_max * match_ratio,
        pool_max)``; a query with no firing keyword gets a zero boost on every
        chunk, leaving scores identical to before.

        Args:
            name_context: The request-scoped name context.
            top_chunk_ids: The fused candidate chunk ids.
            chunk_map: ``chunk_id -> row`` for the fetched candidate rows.
            fused: The fused score pool (mutated in place by the boost).
            skip_ids: Chunk ids that already received a stronger exact-tier
                match boost; skipped so overlapping tiers are never summed.

        Returns:
            ``(path_boost_evidence, match_boost_evidence)`` where
            *path_boost_evidence* maps chunk id to the additive float boost and
            *match_boost_evidence* maps chunk id to the ``stem``/``path_term``
            ``score_sources.match_boost`` object; both empty when no keyword
            fired.
        """
        pool_max = self._pool_max(fused)
        path_evidence: dict[int, float] = {}
        match_evidence: dict[int, dict[str, Any]] = {}
        for chunk_id in top_chunk_ids:
            if chunk_id in skip_ids:
                continue
            chunk = chunk_map.get(chunk_id)
            if chunk is None:
                continue
            tier, match_ratio = classify_path_match(
                name_context,
                chunk["file_path"],
                min_prefix=self._settings.stem_min_prefix,
                keywords_min=self._settings.nl_boost_keywords_min,
            )
            if tier is MatchTier.none:
                continue
            # match_ratio is the fraction of query keywords matched, so a
            # generic keyword shared by many unrelated files can only ever
            # yield a partial boost — the pool_max cap then keeps such files at
            # or below the top relevant score.
            boost = min(self._settings.nl_boost_max * match_ratio, pool_max)
            fused[chunk_id] = fused.get(chunk_id, 0.0) + boost
            path_evidence[chunk_id] = boost
            match_evidence[chunk_id] = {
                "tier": tier.name,
                "boost": boost,
                "match_ratio": match_ratio,
            }
        return path_evidence, match_evidence

    def _detect_exact_precheck(self, query: str) -> dict[str, Any] | None:
        """Return the exact pre-check descriptor, honoring the toggle.

        Returns ``None`` when ``CODE_SEARCH_EXACT_PRECHECK_TAGS`` is off or
        when :func:`exact_precheck` finds no concrete pattern/literal token.
        """
        if self._settings.exact_precheck_tags.lower() not in ("on", "true", "1", "yes"):
            return None
        return exact_precheck(query)

    def _resource_intent(self, query: str) -> bool:
        """Return whether *query* carries explicit resource intent.

        A query carries resource intent when any tokenized or decomposed
        sub-word equals or contains a word from
        ``CODE_SEARCH_RESOURCE_INTENT_WORDS`` (``sql``, ``migration``, ``ddl``,
        ``config``, ``xml``, ``seed``, ``testdata``). This lifts the resource
        weight back toward the code weight so selective demotion never becomes
        a hard exclusion.
        """
        intent_words = self._settings.resource_intent_words
        if not intent_words:
            return False
        tokens = set(tokenize(query, self._settings.filter_stopwords))
        tokens.update(decompose_query(query, self._settings.filter_stopwords))
        for token in tokens:
            if token in intent_words:
                return True
            for word in intent_words:
                if token.startswith(word) or word in token:
                    return True
        return False

    def _class_weights(self, resource_intent: bool) -> dict[str, float]:
        """Return the per-rank-class weight map for the current query.

        ``code`` chunks always keep weight 1.0; ``boilerplate`` uses
        ``CODE_SEARCH_BOILERPLATE_DEBOOST``; ``resource`` uses
        ``CODE_SEARCH_RESOURCE_DEBOOST`` unless the query carries resource
        intent, in which case it is lifted back to the code weight. The
        ``min_lift`` knob enforces a minimum separation between de-boosted and
        code-class weights so de-boosted chunks can never match code chunks.
        """
        resource_weight = 1.0 if resource_intent else self._settings.resource_deboost
        boilerplate_weight = self._settings.boilerplate_deboost
        for key in ("resource", "boilerplate"):
            weight = resource_weight if key == "resource" else boilerplate_weight
            if weight < 1.0 and 1.0 - weight < self._settings.min_lift:
                # A de-boosted weight dangerously close to 1.0 is capped DOWN
                # to keep the minimum separation from the code class (which
                # stays at 1.0). Weights lifted to code level (1.0) are exempt.
                cap = 1.0 - self._settings.min_lift
                if key == "resource":
                    resource_weight = min(weight, cap)
                else:
                    boilerplate_weight = min(weight, cap)
        return {
            "code": 1.0,
            "boilerplate": boilerplate_weight,
            "resource": resource_weight,
        }

    def _config_scent(self, query: str) -> bool:
        """Return whether *query* carries config-scent intent.

        A query carries config scent when any tokenized or decomposed
        sub-word equals or contains a word from
        ``CODE_SEARCH_CONFIG_SCENT_WORDS`` (``config``, ``connection``,
        ``pool``, ``timeout``, ...). This lifts the config content-type weight
        so config chunks surface for config questions.
        """
        scent_words = self._settings.config_scent_words
        if not scent_words:
            return False
        tokens = set(tokenize(query, self._settings.filter_stopwords))
        tokens.update(decompose_query(query, self._settings.filter_stopwords))
        for token in tokens:
            if token in scent_words:
                return True
            for word in scent_words:
                if token.startswith(word) or word in token:
                    return True
        return False

    def _ddl_scent(self, query: str) -> bool:
        """Return whether *query* carries DDL/schema intent.

        Fires when any tokenized/decomposed sub-word matches a word from
        ``CODE_SEARCH_DDL_INTENT_WORDS`` (``schema``, ``create table``,
        ``column``, ``ddl``, ``alter``, ...).
        """
        return self._vocab_scent(query, self._settings.ddl_intent_words)

    def _migration_scent(self, query: str) -> bool:
        """Return whether *query* carries migration intent.

        Fires when any tokenized/decomposed sub-word matches a word from
        ``CODE_SEARCH_MIGRATION_INTENT_WORDS`` (``migration``, ``flyway``,
        ``add column``, ``alter table``, ...).
        """
        return self._vocab_scent(query, self._settings.migration_intent_words)

    @staticmethod
    def _vocab_scent(query: str, vocab: tuple[str, ...]) -> bool:
        """Return whether *query* mentions any word from *vocab* (word or sub-word)."""
        if not vocab:
            return False
        tokens = set(tokenize(query))
        tokens.update(decompose_query(query))
        for token in tokens:
            if token in vocab:
                return True
            for word in vocab:
                if token.startswith(word) or word in token:
                    return True
        return False

    def _resource_scent(self, query: str) -> bool:
        """Return whether *query* carries config, DDL, or migration scent.

        The combined resource-type scent drives the config content-weight
        lift, the config-inject pass, and the config reconciliation in the
        ranked path, so a schema/migration question surfaces the relevant
        ``.sql``/config resource.
        """
        return self._config_scent(query) or self._ddl_scent(query) or self._migration_scent(query)

    def _config_inject_pass(self, query: str, fused: dict[int, float]) -> dict[int, float]:
        """Add config chunks into the fused pool for a config-scent query.

        Config/resource chunks must rank for config-scent
        questions even when the config file shares no lexical/vector tokens
        with the query (e.g. ``connection timeout`` against a properties file
        that only sets a datasource URL). Config chunks are added to the pool
        with a fraction of the current pool maximum so the config-scent
        content-weight boost (``config_content_boost``) can lift the answer
        into the top ranks without outranking an on-topic code hit. Primary
        config files (``application*``/``config*``/``settings*`` names) get a
        larger share of the boost so the canonical config answer wins over
        incidental config/resource files (lockfiles, build files).

        Args:
            query: The raw user query.
            fused: The fused score pool (mutated in place by the boost).

        Returns:
            Per-chunk evidence ``{chunk_id: boost}``.
        """
        if not self._resource_scent(query):
            return {}
        try:
            with self._db.connect() as conn:
                rows = conn.execute(
                    "SELECT id, file_path AS fp FROM code_chunks WHERE content_type = 'config';"
                ).fetchall()
        except Exception as exc:
            logger.warning("Config-inject lookup failed: %s", exc)
            return {}
        if not rows:
            return {}
        base = self._settings.config_inject_boost * self._pool_max(fused)
        primary_extra = self._settings.config_inject_primary_extra
        schema_scent = self._ddl_scent(query) or self._migration_scent(query)
        evidence: dict[int, float] = {}
        for row in rows:
            chunk_id = row["id"]
            path_lower = (row["fp"] or "").lower()
            name = path_lower.rsplit("/", 1)[-1]
            is_schema = schema_scent and (name.endswith(".sql") or "migration" in path_lower)
            is_primary = (
                name.startswith("application")
                or name.startswith("config")
                or name.startswith("settings")
                or ".properties" in name
                or is_schema
            )
            boost = base * (1.0 + primary_extra) if is_primary else base
            if is_schema:
                boost = boost * (1.0 + primary_extra)
            # The boost is additive, so a config chunk that already carried a
            # lexical/vector hit keeps that evidence and is lifted above
            # incidental config/resource noise (lockfiles, build files).
            fused[chunk_id] = fused.get(chunk_id, 0.0) + boost
            evidence[chunk_id] = boost
        return evidence

    def _content_weights(self, config_scent: bool, code_context: bool) -> dict[str, float]:
        """Return the per-content-type weight map for the current query.

        ``code`` chunks always keep weight 1.0; a config/DDL/migration-scent
        query lifts ``config`` by ``config_content_boost``; under a
        code-language context (an explicit or inferred code language)
        config/docs chunks are demoted by ``non_code_language_demote`` so
        docs/config do not compete with code for the top ranks. The
        type-aware per-file boost/deboost (``compute_scent_adjustment``) is
        applied per chunk in :meth:`_search_impl`, so build-metadata noise is
        not lifted by the blanket config weight.
        """
        config_weight = self._settings.config_content_boost if config_scent else 1.0
        docs_weight = 1.0
        if code_context:
            config_weight *= self._settings.non_code_language_demote
            docs_weight = self._settings.non_code_language_demote
        return {
            "code": 1.0,
            "config": config_weight,
            "docs": docs_weight,
        }

    def _query_exact_ids(self, precheck: dict[str, Any]) -> set[int]:
        """Return chunk ids whose content matches a exact-match term.

        Matches the annotation name, the quoted literal, the dependency
        literal, and the bare identifier against ``content``/``fqn``
        (case-insensitive substring). These hits are boosted above fuzzy
        neighbors in :meth:`search`.
        """
        terms: list[str] = []
        for ann in precheck.get("annotations", []):
            terms.append(ann)
        terms.extend(precheck.get("quotes", []))
        terms.extend(precheck.get("literals", []))
        identifier = precheck.get("identifier")
        if identifier:
            terms.append(identifier)
        if not terms:
            return set()
        exact_ids: set[int] = set()
        try:
            with self._db.connect() as conn:
                for term in terms:
                    rows = conn.execute(
                        "SELECT id FROM code_chunks "
                        "WHERE content LIKE '%' || ? || '%' OR fqn LIKE '%' || ? || '%';",
                        (term, term),
                    ).fetchall()
                    exact_ids.update(r["id"] for r in rows)
        except Exception as exc:
            logger.warning("Exact pre-check query failed: %s", exc)
        return exact_ids

    def _query_quality_gate(
        self,
        query: str,
        lexical_hit_count: int,
        informative: list[str],
        raw_vector_results: list[tuple[int, float]],
    ) -> tuple[bool, list[tuple[int, float]]]:
        """Evaluate the multi-signal query-quality gate.

        Returns ``(accepted, vector_results_to_fuse)``. Three signals run here
        on absolute pre-normalisation data; top-result saturation is checked by
        the caller once candidate chunks are known.

        - informative-token coverage: at least ``informative_tokens_min`` query
          sub-words must be non-stopword, non-boilerplate, present in the
          corpus (exact or ≥3-char prefix) and IDF >= ``idf_floor``;
        - concept-signal coverage: a multi-token query must be supported by at
          least ``concept_signal_min`` informative sub-words, so gibberish
          queries sharing only a single real identifier token (``wqrble token``,
          ``florble token waffle``) are rejected consistently on any corpus —
          including small fixtures where that shared token is IDF-rare;
        - zero-lexical-hit rejection: with no FTS hits, vector-only evidence
          must clear the strict ``vector_only_cosine_floor``;
        - exact-token coverage + absolute vector floor: for a
          multi-token concept query (``concept_subwords >= 2``), when the
          query's exact-token coverage is below ``exact_token_coverage_min``
          AND the top raw (pre-normalization) vector cosine is below
          ``top_vector_floor``, the query is treated as out-of-domain and
          rejected (the "meaningful empty"). Coverage is computed after
          expansion (S6-style acronym queries still clear it), and the vector
          leg admits typo queries (F1) whose best hit genuinely matches.
          Single-token queries are excluded: their lexical anchor is the
          informative-token check (exact-or-prefix presence) plus the
          sub-word/prefix decomposition, which must not regress (``pagination``
          -> ``pag*`` -> ``Pageable``; ``postgres`` -> the URL token).
        """
        if not self._settings.relevance_gate:
            return True, raw_vector_results

        if len(informative) < self._settings.informative_tokens_min:
            return False, raw_vector_results

        # Permission/validation paraphrases ("restrict which users can modify
        # a resource", "validate the request body on login") are exempt from
        # the out-of-domain rejections: they are concept questions whose
        # answer chunks share few tokens, and the authorization-inject pass
        # surfaces the definitions.
        auth_intent = self._authorization_intent(query)

        if (
            len(self._bm25.concept_subwords(query)) >= 2
            and len(informative) < self._settings.concept_signal_min
            and not self._on_topic_scaffold_query(query)
            and not self._resource_scent(query)
            and not auth_intent
        ):
            return False, raw_vector_results

        if (
            self._analysis is not None
            and len(self._bm25.concept_subwords(query)) >= 2
            and self._analysis.coverage < self._settings.exact_token_coverage_min
            and not self._on_topic_scaffold_query(query)
            and not self._resource_scent(query)
            and not auth_intent
        ):
            top_vector = max((sc for _, sc in raw_vector_results), default=0.0)
            if top_vector < self._settings.top_vector_floor:
                return False, raw_vector_results

        if lexical_hit_count == 0 and not self._resource_scent(query):
            floor = self._settings.vector_only_cosine_floor
            strict = [(cid, sc) for cid, sc in raw_vector_results if sc >= floor]
            if not strict:
                return False, raw_vector_results
            return True, strict

        return True, raw_vector_results

    @staticmethod
    def _results_saturated(informative: list[str], chunks: list[dict[str, Any]]) -> bool:
        """Require at least one candidate chunk to match an informative sub-word.

        A sub-word matches when it appears verbatim in the chunk's subwords or
        content, or when a corpus token sharing its ≥3-char prefix does.
        """
        for chunk in chunks:
            subwords = set((chunk.get("subwords") or "").split())
            content = (chunk.get("content") or "").lower()
            for word in informative:
                if word in subwords or word in content:
                    return True
                if len(word) >= 3 and any(t.startswith(word[:3]) for t in subwords):
                    return True
        return False

    def _rescue_eligible(self, query: str) -> bool:
        """Return whether the rescue ladder may rescue *query*.

        Implements the rescue floor contract: pure-gibberish queries (zero
        meaningful token overlap with the indexed corpus) return no_match;
        borderline queries with at least one meaningful (informative) token
        are allowed to return rescue results. Declared-rule intent queries
        are always eligible. When the relevance gate is disabled, the ladder
        behaves as a pure fallback.
        """
        from src.engine.rescue_floor import evaluate_rescue_floor

        if not self._settings.relevance_gate:
            return True
        if self._declared_rule_intent(query):
            return True

        expanded = (
            self._expansion_table.expanded_text(query)
            if self._expansion_table is not None
            else query
        )
        # Use informative tokens (exact corpus matches with IDF >= floor,
        # no prefix matching) as the "meaningful" vocabulary per the rescue
        # floor contract's "meaningful overlap" definition. This prevents
        # prefix-matched tokens like "not" from "notaword" from counting as
        # meaningful overlap, while still requiring IDF-significant tokens.
        all_informative = self._bm25.informative_tokens(expanded)
        # Filter to exact corpus matches only (exclude prefix-matched tokens)
        _, _, _, corpus = self._bm25._corpus_subword_stats()
        informative = [w for w in all_informative if w in corpus]
        # Filter query tokens the same way informative_tokens does:
        # exclude stopwords, non-informative code terms, and tokens < 3 chars.
        query_tokens = [
            w
            for w in decompose_query(expanded, self._settings.filter_stopwords)
            if len(w) >= 3 and w not in STOPWORDS and w not in NON_INFORMATIVE_CODE_TERMS
        ]

        if not query_tokens:
            return False

        # Use informative tokens (IDF-filtered exact matches) as the
        # indexed_content_tokens for the contract.
        result = evaluate_rescue_floor(query_tokens, set(informative), 0.5)
        return bool(result["return_rescue"])

    def _rescue_symbol_ids(self) -> set[int] | None:
        """Return the definition-chunk ids a symbol-intent query may rescue.

        A symbol query's answer is its definition; a file that merely shares
        the symbol's name without defining it (``order.py`` defines
        ``OrderService``, not ``Order``) must never be surfaced by a rescue
        tier. Returns ``None`` for non-symbol queries (no restriction).
        """
        symbol_name = self._resolved_symbol_name()
        if symbol_name is None:
            return None
        rows = self._definition_chunks([symbol_name]).get(symbol_name, [])
        return {row["id"] for row in rows}

    def _rescue_envelope(
        self,
        query: str,
        limit: int,
        language: str | None,
        include_tests: bool,
        vector_health: bool,
        content: str = "all",
    ) -> dict[str, Any]:
        """Run the rescue ladder below an empty ranked path.

        Tier 1 (``ranked-lexical``) reruns BM25 with a relaxed quality gate;
        tier 2 (``literal``) scans content/FQN case-insensitively; when both
        miss, a ``no_match`` explanation envelope reports the tiers tried so an
        empty result is never returned without an explanation.

        Args:
            query: The user query text.
            limit: Maximum results to return.
            language: Optional language restriction.
            include_tests: Whether test-file chunks are returned.
            vector_health: The ranked path's vector-layer health.
            content: The content-type scope (``all`` default disables it).

        Returns:
            A rescue-mode search envelope.
        """
        tiers_tried: list[str] = []
        if self._settings.rescue_t1_enabled:
            tiers_tried.append("lexical")
            env = self._rescue_t1(query, limit, language, include_tests, vector_health, content)
            if env is not None and env["results"]:
                return env
        if self._settings.rescue_literal_enabled:
            tiers_tried.append("literal")
            env = self._rescue_t2(query, limit, language, include_tests, vector_health, content)
            if env is not None and env["results"]:
                return env
        return self._no_match_envelope(vector_health, tiers_tried, query, content)

    def _rescue_t1(
        self,
        query: str,
        limit: int,
        language: str | None,
        include_tests: bool,
        vector_health: bool,
        content: str = "all",
    ) -> dict[str, Any] | None:
        """Relaxed-lexical rescue: BM25 with a relaxed quality gate.

        Returns ``None`` when the relaxed BM25 arm finds nothing, so the
        ladder proceeds to the literal tier.
        """
        import dataclasses

        if not self._rescue_eligible(query):
            return None
        relaxed = dataclasses.replace(
            self._settings,
            relevance_gate=True,
            informative_tokens_min=self._settings.rescue_t1_informative_tokens_min,
            concept_signal_min=self._settings.rescue_t1_concept_signal_min,
            relevance_threshold=self._settings.rescue_t1_relevance_threshold,
        )
        bm25 = BM25Search(self._db, relaxed, filter_stopwords=self._settings.filter_stopwords)
        pool = max(limit, limit * self._settings.search_top_k_multiplier)
        bm25_results = bm25.search(query, top_k=pool)
        if not bm25_results:
            return None
        symbol_ids = self._rescue_symbol_ids()
        if symbol_ids is not None:
            if not symbol_ids:
                return None
            bm25_results = [(cid, sc) for cid, sc in bm25_results if cid in symbol_ids]
            if not bm25_results:
                return None
        rows = self._fetch_chunks([cid for cid, _ in bm25_results])
        chunk_map = {row["id"]: row for row in rows}
        scores = {cid: sc for cid, sc in bm25_results}
        analysis_paths = set(self._settings.analysis_artifact_paths)

        def _in_scope(row: dict[str, Any]) -> bool:
            ctype: str = str(row.get("content_type", "code"))
            if content == "all":
                return True
            if content == DEFAULT_CONTENT_SCOPE:
                return ctype != "docs"
            return ctype == content

        candidate_chunks = [
            chunk_map[cid]
            for cid, _ in bm25_results
            if cid in chunk_map
            and _in_scope(chunk_map[cid])
            and (not language or chunk_map[cid]["language"] == language)
            and (include_tests or not _is_test_file(chunk_map[cid]["file_path"]))
        ]
        if not candidate_chunks:
            return None
        normalized = _normalize_scores({c["id"]: scores[c["id"]] for c in candidate_chunks})
        query_subwords = decompose_query(query, self._settings.filter_stopwords)
        match_context = self._build_query_match_context(query)
        # A rescue-surfaced result was produced by the lexical arm; label it
        # honestly so it never carries an unexplained zero.
        rescue_contribution = "lexical_only" if vector_health else "unavailable"
        results: list[dict[str, Any]] = []
        bands: list[str] = []
        for chunk in candidate_chunks:
            conf = calibrated_confidence(
                MatchEvidence(
                    query_subwords=query_subwords,
                    chunk_subwords=(chunk.get("subwords") or "").split(),
                    vector_score=0.0,
                    fqn=chunk["fqn"],
                    is_definition=bool(chunk["is_definition"]),
                    content=chunk["content"],
                    file_path=chunk["file_path"],
                    query_identifier=match_context.query_identifier,
                ),
                match_context,
            )
            band = confidence_band(
                conf, self._settings.confidence_high_floor, self._settings.confidence_medium_floor
            )
            bands.append(band)
            results.append(
                {
                    "chunk_id": chunk["id"],
                    "file_path": chunk["file_path"],
                    "line_start": chunk["line_start"],
                    "line_end": chunk["line_end"],
                    "content": chunk["content"],
                    "fqn": chunk["fqn"],
                    "language": chunk["language"],
                    "score": round(normalized[chunk["id"]], 3),
                    "bm25_score": scores[chunk["id"]],
                    "vector_score": 0.0,
                    "vector_retrieved": False,
                    "semantic_contribution": rescue_contribution,
                    "is_definition": bool(chunk["is_definition"]),
                    "role": "definition" if chunk["is_definition"] else "reference",
                    "file_role": file_role(chunk["file_path"], analysis_paths=analysis_paths),
                    "is_test_file": _is_test_file(chunk["file_path"]),
                    "is_non_canonical": _is_non_canonical(chunk["file_path"]),
                    "path_class": PathClass.of(self._db, chunk["file_path"]),
                    "chunk_type": chunk.get("chunk_type", "ast"),
                    "chunk_node_type": chunk.get("chunk_node_type"),
                    "content_type": chunk.get("content_type", "code"),
                    "vector_degraded": not vector_health,
                    "redacted_count": 0,
                    "confidence": round(conf, 3),
                    "confidence_band": band,
                    "low_confidence": is_borderline(band),
                    "borderline": is_borderline(band),
                }
            )
        results = self._apply_file_coherence(results)
        total_matches = bm25.count(query)
        return {
            "results": results[:limit],
            "total_matches": total_matches,
            "truncated": total_matches > limit,
            "vector_health": vector_health,
            "mode": "ranked-lexical",
            "matching_semantics": "all_tokens",
            "confidence": envelope_band(bands),
            "explanation": {
                "reason": "rescued",
                "rescued_tiers": ["lexical"],
                "confidence": envelope_band(bands),
            },
            "best_effort": True,
            "content": content,
        }

    def _rescue_t2(
        self,
        query: str,
        limit: int,
        language: str | None,
        include_tests: bool,
        vector_health: bool,
        content: str = "all",
    ) -> dict[str, Any] | None:
        """Literal rescue: case-insensitive substring scan of content/fqn.

        Returns ``None`` when no chunk contains any query term verbatim.
        """
        if not self._rescue_eligible(query):
            return None
        symbol_ids = self._rescue_symbol_ids()
        if symbol_ids is not None and not symbol_ids:
            return None
        terms = [t for t in tokenize(query, self._settings.filter_stopwords) if len(t) >= 3]
        if not terms:
            return None
        like_clauses = " OR ".join(["content LIKE '%' || ? || '%'" for _ in terms])
        fqn_clauses = " OR ".join(["fqn LIKE '%' || ? || '%'" for _ in terms])
        where = [f"(({like_clauses}) OR ({fqn_clauses}))"]
        params: list[Any] = [t for t in terms] + [t for t in terms]
        if content in ("code", "config", "docs"):
            where.append("content_type = ?")
            params.append(content)
        elif content == DEFAULT_CONTENT_SCOPE:
            where.append("content_type != 'docs'")
        if language:
            where.append("language = ?")
            params.append(language)
        if not include_tests:
            test_rows = self._test_file_paths()
            if test_rows:
                test_placeholders = ",".join("?" for _ in test_rows)
                where.append(f"file_path NOT IN ({test_placeholders})")
                params.extend(test_rows)
        rows = []
        try:
            with self._db.connect() as conn:
                rows = conn.execute(
                    f"SELECT id, fqn, file_path, line_start, line_end, content, language, "
                    f"is_definition, chunk_type, chunk_node_type, subwords, content_type "
                    f"FROM code_chunks WHERE {' AND '.join(where)} LIMIT ?;",
                    [*params, limit],
                ).fetchall()
        except Exception as exc:
            logger.warning("Literal rescue failed: %s", exc)
            return None
        if symbol_ids is not None:
            rows = [r for r in rows if r["id"] in symbol_ids]
        if not rows:
            return None
        query_subwords = decompose_query(query, self._settings.filter_stopwords)
        match_context = self._build_query_match_context(query)
        # A literal-rescue result was produced by the lexical arm; label it
        # honestly so it never carries an unexplained zero.
        rescue_contribution = "lexical_only" if vector_health else "unavailable"
        results: list[dict[str, Any]] = []
        bands: list[str] = []
        analysis_paths = set(self._settings.analysis_artifact_paths)
        for rank, row in enumerate(rows):
            conf = calibrated_confidence(
                MatchEvidence(
                    query_subwords=query_subwords,
                    chunk_subwords=(row["subwords"] or "").split(),
                    vector_score=0.0,
                    fqn=row["fqn"],
                    is_definition=bool(row["is_definition"]),
                    content=row["content"],
                    file_path=row["file_path"],
                    query_identifier=match_context.query_identifier,
                ),
                match_context,
            )
            band = confidence_band(
                conf, self._settings.confidence_high_floor, self._settings.confidence_medium_floor
            )
            bands.append(band)
            results.append(
                {
                    "chunk_id": row["id"],
                    "file_path": row["file_path"],
                    "line_start": row["line_start"],
                    "line_end": row["line_end"],
                    "content": row["content"],
                    "fqn": row["fqn"],
                    "language": row["language"],
                    "score": round(1.0 / (1 + rank), 3),
                    "bm25_score": 0.0,
                    "vector_score": 0.0,
                    "vector_retrieved": False,
                    "semantic_contribution": rescue_contribution,
                    "is_definition": bool(row["is_definition"]),
                    "role": "definition" if row["is_definition"] else "reference",
                    "file_role": file_role(row["file_path"], analysis_paths=analysis_paths),
                    "is_test_file": _is_test_file(row["file_path"]),
                    "is_non_canonical": _is_non_canonical(row["file_path"]),
                    "path_class": PathClass.of(self._db, row["file_path"]),
                    "chunk_type": row["chunk_type"],
                    "chunk_node_type": row["chunk_node_type"],
                    "content_type": row["content_type"],
                    "vector_degraded": not vector_health,
                    "redacted_count": 0,
                    "confidence": round(conf, 3),
                    "confidence_band": band,
                    "low_confidence": is_borderline(band),
                }
            )
        total_matches = len(results)
        return {
            "results": results,
            "total_matches": total_matches,
            "truncated": False,
            "vector_health": vector_health,
            "mode": "literal",
            "matching_semantics": "literal",
            "confidence": envelope_band(bands),
            "explanation": {
                "reason": "rescued",
                "rescued_tiers": ["lexical", "literal"],
                "confidence": envelope_band(bands),
            },
            "best_effort": True,
            "content": content,
        }

    def _no_match_envelope(
        self,
        vector_health: bool,
        tiers_tried: list[str],
        query: str | None = None,
        content: str = "all",
    ) -> dict[str, Any]:
        """Return the honest ``no_match`` explanation envelope.

        ``reason`` is ``invalid_query`` when the query decomposes to nothing
        (blank/whitespace), else ``no_match``. Results are never fabricated.
        """
        reason = "no_match"
        if query is not None and not decompose_query(query, self._settings.filter_stopwords):
            reason = "invalid_query"
        return {
            "results": [],
            "total_matches": 0,
            "truncated": False,
            "vector_health": vector_health,
            "mode": "ranked",
            "matching_semantics": "all_tokens",
            "confidence": "none",
            "explanation": {
                "reason": reason,
                "rescued_tiers": tiers_tried,
                "confidence": "none",
            },
            "best_effort": True,
            "no_match": True,
            "content": content,
        }

    def _declared_rule_intent(self, query: str) -> bool:
        """Return whether *query* asks about declared rules/guards.

        A query carries declared-rule intent when any decomposed sub-word
        equals a word from ``CODE_SEARCH_DECLARED_RULE_INTENT_WORDS`` or the
        query mentions an ``@Annotation``.
        """
        intent_words = self._settings.declared_rule_intent_words
        tokens = set(decompose_query(query, self._settings.filter_stopwords))
        if tokens & set(intent_words):
            return True
        precheck = exact_precheck(query)
        return bool(precheck and precheck["annotations"])

    def _authorization_intent(self, query: str) -> bool:
        """Return whether *query* carries permission/validation intent.

        A query carries authorization intent when any decomposed sub-word
        equals a word from ``CODE_SEARCH_AUTHORIZATION_INTENT_WORDS``
        (``restrict``/``permission``/``authorize``/``validate``/``login``/
        ``request``/``body``/...). This drives the annotation/DTO-definition
        inject pass so permission/validation paraphrases reach their answers.
        """
        intent_words = self._settings.authorization_intent_words
        if not intent_words:
            return False
        tokens = set(decompose_query(query, self._settings.filter_stopwords))
        return bool(tokens & set(intent_words))

    def _authorization_inject_pass(self, fused: dict[int, float]) -> dict[int, float]:
        """Inject authorization-definition chunks into the fused pool.

        Permission/validation paraphrases ("restrict which users can modify a
        resource", "validate the request body on login") are answered by
        annotation-type declarations (``@interface``) and guard/validation
        definitions that may share no lexical/vector tokens with the query.
        Such chunks are added to the pool with a fraction of the current pool
        maximum so the reranker's annotation boost can lift the definition
        into the top ranks without outranking an on-topic code hit.

        Args:
            fused: The fused score pool (mutated in place by the boost).

        Returns:
            Per-chunk evidence ``{chunk_id: boost}``.
        """
        try:
            with self._db.connect() as conn:
                rows = conn.execute(
                    "SELECT id, file_path, chunk_node_type, declared_rules FROM code_chunks;"
                ).fetchall()
        except Exception as exc:
            logger.warning("Authorization-inject lookup failed: %s", exc)
            return {}
        if not rows:
            return {}
        base = self._settings.declared_rule_boost * self._pool_max(fused)
        evidence: dict[int, float] = {}
        for row in rows:
            if not self._is_authorization_chunk(row):
                continue
            chunk_id = row["id"]
            fused[chunk_id] = fused.get(chunk_id, 0.0) + base
            evidence[chunk_id] = base
        return evidence

    @staticmethod
    def _is_authorization_chunk(row: Any) -> bool:
        """Return whether a code_chunks row is an authorization-definition chunk.

        A chunk is an authorization definition when it is an annotation-type
        declaration (``@interface``), its declared rules carry a guard/
        validation/security annotation, or it lives under an authorization
        path segment (``auth``/``security``/``authorization``/``permission``/
        ``guard``).
        """
        if (row["chunk_node_type"] or "") == "annotation_type_declaration":
            return True
        rules = (row["declared_rules"] or "").lower()
        if any(
            kw in rules
            for kw in (
                "@preauthorize",
                "@secured",
                "@valid",
                "@check",
                "@target",
                "@retention",
                "authorize",
                "security",
                "permission",
            )
        ):
            return True
        path = (row["file_path"] or "").lower()
        segments = path.replace("\\", "/").split("/")
        return bool({"auth", "security", "authorization", "permission", "guard"} & set(segments))

    def _on_topic_scaffold_query(self, query: str) -> bool:
        """Return whether *query* is explicitly about a generic construct.

        A query naming the scaffold itself (``exception``, ``dto``, ``model``,
        ``bean``) asks about generic scaffolding, so the query-quality gate
        must not reject it for lacking multiple corpus-informative tokens:
        on-topic scaffolding has to stay reachable. The vocabulary is
        ``CODE_SEARCH_SCAFFOLD_TOPIC_WORDS``.
        """
        scaffold_words = self._settings.scaffold_topic_words
        if not scaffold_words:
            return False
        tokens = set(decompose_query(query, self._settings.filter_stopwords))
        return bool(tokens & set(scaffold_words))

    def _declared_rules_pass(self, query: str, fused: dict[int, float]) -> dict[int, float]:
        """Boost chunks whose declared_rules match a query sub-word.

        Adds ``pool_max * declared_rule_boost`` to the fused score of every
        chunk whose ``declared_rules`` column contains (case-insensitively) a
        query sub-word of at least 3 chars. Non-candidates enter the fused
        pool so guarded behavior surfaces even without a lexical/vector hit.

        Args:
            query: The raw user query.
            fused: The fused score pool (mutated in place by the boost).

        Returns:
            Per-chunk evidence ``{chunk_id: boost}``.
        """
        subwords = [
            w
            for w in decompose_query(query, self._settings.filter_stopwords)
            if len(w) >= 3 and w not in NON_INFORMATIVE_CODE_TERMS
        ]
        if not subwords:
            return {}
        like_clauses = " OR ".join(["declared_rules LIKE '%' || ? || '%'" for _ in subwords])
        try:
            with self._db.connect() as conn:
                rows = conn.execute(
                    f"SELECT id FROM code_chunks WHERE {like_clauses};", subwords
                ).fetchall()
        except Exception as exc:
            logger.warning("Declared-rules lookup failed: %s", exc)
            return {}
        boost = self._settings.declared_rule_boost * self._pool_max(fused)
        evidence: dict[int, float] = {}
        for row in rows:
            chunk_id = row["id"]
            fused[chunk_id] = fused.get(chunk_id, 0.0) + boost
            evidence[chunk_id] = boost
        return evidence

    def _code_language_context(self, explicit_language: str | None) -> bool:
        """Return whether a code-language context is active for the query.

        An explicit ``language`` argument or the query-analysis inferred
        language counts when it is a code language (everything except the
        resource-family languages). When no language is active, ``False`` so
        the relaxed infra deboost applies.
        """
        language = explicit_language
        if language is None and self._analysis is not None:
            language = self._analysis.inferred_language
        if not language:
            return False
        return language not in {
            "xml",
            "sql",
            "properties",
            "gradle",
            "yaml",
            "toml",
            "json",
        }

    def _test_file_paths(self) -> list[str]:
        """Return the stored paths of all test files in the index."""
        try:
            with self._db.connect() as conn:
                rows = conn.execute("SELECT DISTINCT file_path FROM code_chunks;").fetchall()
        except Exception as exc:
            logger.warning("Test-file path lookup failed: %s", exc)
            return []
        return [r["file_path"] for r in rows if _is_test_file(r["file_path"])]

    def _fetch_chunks(self, chunk_ids: list[int]) -> list[dict[str, Any]]:
        """Fetch ``code_chunks`` rows for *chunk_ids* as dicts in id order."""
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        with self._db.connect() as conn:
            rows = conn.execute(
                f"SELECT id, fqn, file_path, line_start, line_end, content, language, "
                f"is_definition, chunk_type, chunk_node_type, subwords, content_type "
                f"FROM code_chunks WHERE id IN ({placeholders});",
                chunk_ids,
            ).fetchall()
        return [dict(row) for row in rows]

    def _search_exhaustive(
        self,
        query: str,
        limit: int,
        language: str | None,
        include_tests: bool,
        vector_health: bool,
        content: str = "all",
        matching: str | None = None,
    ) -> dict[str, Any]:
        """Line-oriented exhaustive scan over the indexed files.

        Scans the files the index knows about (``file_checksums`` /
        distinct ``code_chunks.file_path``), reading each from local disk
        and counting case-per-``exhaustive_case_sensitive`` literal
        substring matches per line — mirroring the ``rg`` default so the
        count matches the ground-truth literal oracle. The full
        match set is counted exactly (``total_count``); only the first
        ``max(limit, exhaustive_max_lines)`` matches are returned, so a hit
        set larger than the display cap is labelled ``truncated``/
        ``complete: false`` instead of being silently under-reported. A
        ``content`` scope (``code``/``config``/``docs`` or the code-focused
        default) restricts the scan to files of that content axis, and
        *matching* selects the per-request matching semantics — the three exhaustive semantics.

        Args:
            query: The user query text.
            limit: Maximum results to return.
            language: Optional language restriction.
            include_tests: Whether test-file lines are returned.
            vector_health: The layer-health signal for the envelope.
            content: The content-type scope (``all`` default disables it).
            matching: Optional exhaustive matching semantics override
                (``literal``/``all_tokens``/``any_token``); defaults to
                ``CODE_SEARCH_EXHAUSTIVE_MATCHING_MODE``.

        Returns:
            An ``exhaustive`` mode search envelope.
        """
        if not self._settings.exhaustive_enabled:
            return self._no_match_envelope(vector_health, [], query, content)
        terms = [t for t in tokenize(query, self._settings.filter_stopwords) if len(t) >= 2]
        quoted: list[str] = []
        for m in _QUOTED_RE.finditer(query):
            quoted.extend(g for g in m.groups() if g)
        if not terms and not quoted:
            return self._no_match_envelope(vector_health, [], query, content)
        # The matching contract: the default ``all_tokens``
        # mode requires every query token to be present in each matching line
        # (AND), while a quoted phrase matches as one precise literal
        # substring. ``any_token`` keeps the old OR semantics but is always
        # labelled as such; ``literal`` matches the whole query verbatim.
        # Unquoted tokens come from the query with quoted regions blanked so a
        # quoted phrase's decomposed words never become separate requirements.
        mode = matching or self._settings.exhaustive_matching_mode
        if mode not in VALID_MATCHING_SEMANTICS:
            mode = self._settings.exhaustive_matching_mode
        unquoted_text = _QUOTED_RE.sub(" ", query)
        if self._settings.exhaustive_case_sensitive:
            unquoted_terms = list(
                dict.fromkeys(
                    t
                    for t in re.findall(
                        r"@[a-zA-Z_][a-zA-Z0-9_]*|[a-zA-Z_][a-zA-Z0-9_]*", unquoted_text
                    )
                    if len(t) >= 2
                )
            )
        else:
            unquoted_terms = list(
                dict.fromkeys(
                    t
                    for t in tokenize(unquoted_text, self._settings.filter_stopwords)
                    if len(t) >= 2
                )
            )
        quoted_phrases = [g for g in quoted if g]
        if mode == "literal":
            literal_needle = query.replace('"', "").replace("'", "")
            search_terms = [literal_needle] if literal_needle else []
            require_all = False
            matching_semantics = "literal"
        elif mode == "any_token":
            search_terms = list(dict.fromkeys(unquoted_terms + quoted_phrases))
            require_all = False
            matching_semantics = "any_token"
        else:  # all_tokens (default)
            search_terms = list(dict.fromkeys(unquoted_terms + quoted_phrases))
            require_all = True
            # A pure quoted phrase is a single literal substring, so label it
            # ``literal`` rather than ``all_tokens``.
            matching_semantics = (
                "literal" if (quoted_phrases and not unquoted_terms) else "all_tokens"
            )
        if not search_terms:
            return self._no_match_envelope(vector_health, [], query, content)
        search_lower = [t.lower() for t in search_terms]
        cap = max(limit, self._settings.exhaustive_max_lines)

        # The indexed file set is authoritative for the scan: every file the
        # index tracks is read from disk so the per-line count mirrors ``rg``
        # over the same files.
        try:
            with self._db.connect() as conn:
                rows = conn.execute(
                    "SELECT DISTINCT file_path FROM file_checksums ORDER BY file_path;"
                ).fetchall()
        except Exception as exc:
            logger.warning("Exhaustive scan failed: %s", exc)
            return self._no_match_envelope(vector_health, [], query, content)
        indexed_files = [r["file_path"] for r in rows]
        if not indexed_files:
            try:
                with self._db.connect() as conn:
                    rows = conn.execute(
                        "SELECT DISTINCT file_path FROM code_chunks ORDER BY file_path;"
                    ).fetchall()
            except Exception as exc:
                logger.warning("Exhaustive scan failed: %s", exc)
                return self._no_match_envelope(vector_health, [], query, content)
            indexed_files = [r["file_path"] for r in rows]

        index_root: Path | None = None
        try:
            stored_root = IndexMetadataStore(self._db).get("index_root")
            if stored_root:
                index_root = Path(stored_root)
        except Exception as exc:
            logger.debug("Exhaustive index-root lookup failed: %s", exc)

        test_rows: set[str] = set(self._test_file_paths()) if not include_tests else set()
        results: list[dict[str, Any]] = []
        total = 0
        occurrences_per_line: list[int] = []
        occurrence_line_numbers: list[int] = []
        # A single-literal match (``literal`` semantics) counts true
        # occurrences via ``count_occurrences_per_line``, so two hits on one
        # line count as two — the grep ground-truth oracle — instead of
        # conflating lines with occurrences. Multi-term AND/OR modes keep line
        # membership as their well-defined count.
        from src.engine.occurrence_count import count_occurrences_per_line

        count_occurrences = matching_semantics == "literal" and len(search_terms) == 1
        scan_needle = search_terms[0] if count_occurrences else None
        for stored_path in indexed_files:
            if stored_path in test_rows:
                continue
            if (
                content in ("code", "config", "docs")
                and classify_content_type(stored_path).value != content
            ):
                continue
            if (
                content == DEFAULT_CONTENT_SCOPE
                and classify_content_type(stored_path).value == "docs"
            ):
                continue
            resolved = (
                normalize_indexed_path(stored_path, index_root) if index_root else Path(stored_path)
            )
            if resolved is None or not resolved.is_file():
                continue
            try:
                text = resolved.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.debug("Exhaustive scan could not read %s: %s", resolved, exc)
                continue
            file_lang = _language_for_file(resolved) if language else None
            if language and file_lang != language:
                continue
            if count_occurrences and scan_needle is not None:
                if self._settings.exhaustive_case_sensitive:
                    counted = count_occurrences_per_line(text, scan_needle)
                else:
                    counted = count_occurrences_per_line(text.lower(), scan_needle.lower())
                lines = text.splitlines()
                for idx, line_no in enumerate(counted["line_numbers"]):
                    occurrences = counted["per_line"][idx]
                    line = lines[line_no - 1] if 1 <= line_no <= len(lines) else ""
                    total += occurrences
                    occurrences_per_line.append(occurrences)
                    occurrence_line_numbers.append(line_no)
                    if len(results) >= cap:
                        continue
                    results.append(
                        {
                            "file_path": stored_path,
                            "line_number": line_no,
                            "line_content": line,
                            "line_start": line_no,
                            "line_end": line_no,
                            "content": line,
                            "fqn": "",
                            "language": file_lang,
                            "content_type": classify_content_type(stored_path).value,
                            "score": 1.0,
                            "is_test_file": _is_test_file(stored_path),
                            "is_non_canonical": _is_non_canonical(stored_path),
                            "vector_degraded": not vector_health,
                            "redacted_count": 0,
                            "confidence": 1.0,
                            "confidence_band": "high",
                            "occurrences": occurrences,
                        }
                    )
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if self._settings.exhaustive_case_sensitive:
                    if require_all:
                        matched = all(t in line for t in search_terms)
                    else:
                        matched = any(t in line for t in search_terms)
                else:
                    if require_all:
                        matched = all(t in line.lower() for t in search_lower)
                    else:
                        matched = any(t in line.lower() for t in search_lower)
                if not matched:
                    continue
                total += 1
                if len(results) >= cap:
                    continue
                results.append(
                    {
                        "file_path": stored_path,
                        "line_number": line_no,
                        "line_content": line,
                        "line_start": line_no,
                        "line_end": line_no,
                        "content": line,
                        "fqn": "",
                        "language": file_lang,
                        "content_type": classify_content_type(stored_path).value,
                        "score": 1.0,
                        "is_test_file": _is_test_file(stored_path),
                        "is_non_canonical": _is_non_canonical(stored_path),
                        "vector_degraded": not vector_health,
                        "redacted_count": 0,
                        "confidence": 1.0,
                        "confidence_band": "high",
                        "occurrences": 1,
                    }
                )
        truncated = total > len(results)
        envelope = {
            "results": results,
            "total_count": total,
            "truncated": truncated,
            "vector_health": vector_health,
            "mode": "exhaustive",
            "matching_semantics": matching_semantics,
            "confidence": "high" if results else "none",
            "explanation": None,
            "complete": not truncated,
            "content": content,
        }
        if count_occurrences and scan_needle is not None:
            envelope["occurrence_count"] = total
            envelope["literal"] = scan_needle
            envelope["occurrences_per_line"] = occurrences_per_line
            envelope["occurrence_line_numbers"] = occurrence_line_numbers
        return envelope

    def _search_enumerate(self, query: str, limit: int, vector_health: bool) -> dict[str, Any]:
        """Enumerate the named symbol kind ("list all controllers").

        Collects definition chunks whose FQN ends with the enumeration target
        term (plural stripped) — or, for kind words like "class"/"method",
        whose ``chunk_node_type`` matches. Resource kinds (``Dockerfile``,
        ``Makefile``, ``docker-compose*``, ``*Migration*.sql``) enumerate
        indexed resource chunks by filename pattern. Reports ``complete``
        only when the full set fits within *limit* and every indexed file was
        structurally parseable; files the structural layer could not parse
        are returned in ``excluded``.

        Args:
            query: The user query text.
            limit: Maximum results to return.
            vector_health: The layer-health signal for the envelope.

        Returns:
            An ``enumerate`` mode search envelope.
        """
        if not self._settings.enumerate_enabled:
            return self._no_match_envelope(vector_health, [], query)
        target = self._enumeration_target(query)
        if target is None:
            return self._no_match_envelope(vector_health, [], query)
        kinds = self._enumeration_kinds(target)
        resource_pattern = self._resource_patterns(target)
        try:
            with self._db.connect() as conn:
                if kinds is not None:
                    placeholders = ",".join("?" for _ in kinds)
                    count = conn.execute(
                        f"SELECT COUNT(*) FROM code_chunks "
                        f"WHERE is_definition = 1 AND chunk_node_type IN ({placeholders});",
                        kinds,
                    ).fetchone()[0]
                    rows = conn.execute(
                        f"SELECT c.id, c.fqn, c.file_path, c.line_start, c.line_end, "
                        f"c.content, c.language, c.is_definition, c.chunk_type, "
                        f"c.chunk_node_type, s.kind AS symbol_kind "
                        f"FROM code_chunks c "
                        f"LEFT JOIN symbols s ON s.fqn = c.fqn AND s.file_path = c.file_path "
                        f"WHERE c.is_definition = 1 AND c.chunk_node_type IN ({placeholders}) "
                        f"ORDER BY c.file_path, c.line_start LIMIT ?;",
                        [*kinds, limit + 1],
                    ).fetchall()
                elif resource_pattern is not None:
                    glob_clauses = " OR ".join(["c.file_path GLOB ?" for _ in resource_pattern])
                    count = conn.execute(
                        f"SELECT COUNT(*) FROM code_chunks c "
                        f"WHERE c.chunk_type = 'resource' AND ({glob_clauses});",
                        resource_pattern,
                    ).fetchone()[0]
                    rows = conn.execute(
                        "SELECT c.id, c.fqn, c.file_path, c.line_start, c.line_end, "
                        "c.content, c.language, c.is_definition, c.chunk_type, "
                        "c.chunk_node_type, s.kind AS symbol_kind "
                        "FROM code_chunks c "
                        "LEFT JOIN symbols s ON s.fqn = c.fqn AND s.file_path = c.file_path "
                        f"WHERE c.chunk_type = 'resource' AND ({glob_clauses}) "
                        "ORDER BY c.file_path, c.line_start LIMIT ?;",
                        [*resource_pattern, limit + 1],
                    ).fetchall()
                else:
                    count = conn.execute(
                        "SELECT COUNT(*) FROM code_chunks WHERE is_definition = 1 AND fqn LIKE ?;",
                        (f"%{target}",),
                    ).fetchone()[0]
                    rows = conn.execute(
                        "SELECT c.id, c.fqn, c.file_path, c.line_start, c.line_end, "
                        "c.content, c.language, c.is_definition, c.chunk_type, "
                        "c.chunk_node_type, s.kind AS symbol_kind "
                        "FROM code_chunks c "
                        "LEFT JOIN symbols s ON s.fqn = c.fqn AND s.file_path = c.file_path "
                        "WHERE c.is_definition = 1 AND c.fqn LIKE ? "
                        "ORDER BY c.file_path, c.line_start LIMIT ?;",
                        (f"%{target}", limit + 1),
                    ).fetchall()
        except Exception as exc:
            logger.warning("Enumeration failed: %s", exc)
            return self._no_match_envelope(vector_health, [], query)
        shown = rows[:limit]
        analysis_paths = set(self._settings.analysis_artifact_paths)
        results = [
            {
                "chunk_id": row["id"],
                "fqn": row["fqn"],
                "file_path": row["file_path"],
                "kind": _enumerated_kind(row),
                "line_start": row["line_start"],
                "line_end": row["line_end"],
                "content": row["content"],
                "language": row["language"],
                "score": 1.0,
                "is_definition": bool(row["is_definition"]),
                "role": "definition" if row["is_definition"] else "reference",
                "file_role": file_role(row["file_path"], analysis_paths=analysis_paths),
                "is_test_file": _is_test_file(row["file_path"]),
                "is_non_canonical": _is_non_canonical(row["file_path"]),
                "vector_degraded": not vector_health,
                "redacted_count": 0,
                "confidence": 1.0,
                "confidence_band": "high",
            }
            for row in shown
        ]
        total = int(count)
        truncated = total > limit
        excluded = self._unparseable_files()
        envelope: dict[str, Any] = {
            "results": results,
            "total_count": total,
            "truncated": truncated,
            "vector_health": vector_health,
            "mode": "enumerate",
            "confidence": "high" if results else "none",
            "explanation": None,
            "complete": (not truncated) and not excluded,
        }
        if excluded:
            envelope["excluded"] = excluded
        return envelope

    def _enumeration_intent(self, query: str) -> bool:
        """Whether *query* asks to list all of a kind (enumerate auto-select).

        Detects "list all X" / "all X" phrasing so the ranked default
        resolves to enumeration without an explicit ``--mode``. An
        enumeration intent word must be present, stripping the intent words
        must leave exactly one remaining target term, and that term must
        resolve to a symbol kind, a resource pattern, or an FQN suffix — so
        an ordinary ranked query is never hijacked.

        Args:
            query: The user query text.

        Returns:
            ``True`` when *query* should run in ``enumerate`` mode.
        """
        if not self._settings.enumerate_enabled:
            return False
        target = self._enumeration_target(query)
        if target is None:
            return False
        lowered = query.lower()
        intent_words = self._settings.enumeration_intent_words
        intent_re = re.compile(r"\b(?:{})\b".format("|".join(re.escape(w) for w in intent_words)))
        if not intent_re.search(lowered):
            return False
        stripped = intent_re.sub(" ", lowered)
        remaining = [
            w
            for w in decompose_query(stripped)
            if len(w) >= 3
            and w not in STOPWORDS
            and (w in _ENUMERATION_KIND_WORDS or w not in NON_INFORMATIVE_CODE_TERMS)
        ]
        if len(remaining) != 1:
            return False
        residue = remaining[0]
        if (
            self._enumeration_kinds(target) is not None
            or self._resource_patterns(target) is not None
        ):
            return True
        return residue == target or residue in (target + "s", target + "es")

    @staticmethod
    def _enumeration_target(query: str) -> str | None:
        """Return the enumeration target term of *query*, or ``None``.

        "all controllers" -> ``"controller"`` (plural stripped); "list every
        class" -> ``"class"``. Returns ``None`` when the query does not
        decompose into a single ≥3-char, non-stopword, non-boilerplate noun.
        """
        subwords = [
            w
            for w in decompose_query(query)
            if len(w) >= 3
            and w not in STOPWORDS
            and (w in _ENUMERATION_KIND_WORDS or w not in NON_INFORMATIVE_CODE_TERMS)
        ]
        if not subwords:
            return None
        target = subwords[-1]
        if target.endswith("sses"):
            target = target[:-2]
        elif target.endswith("ies") and len(target) > 4:
            target = target[:-3] + "y"
        elif target.endswith("s") and not target.endswith("ss"):
            target = target[:-1]
        return target or None

    @staticmethod
    def _enumeration_kinds(target: str) -> list[str] | None:
        """Return the ``chunk_node_type`` filter for a kind word, else ``None``.

        Kind words ("class", "method", "annotation", ...) enumerate by node
        type so "all classes" lists every type declaration regardless of its
        name; any other target falls back to FQN/path ends-with matching.
        """
        kind_map: dict[str, tuple[str, ...]] = {
            "class": (
                "class_declaration",
                "class_definition",
                "record_declaration",
                "interface_declaration",
                "enum_declaration",
                "annotation_type_declaration",
            ),
            "interface": ("interface_declaration",),
            "enum": ("enum_declaration",),
            "annotation": ("annotation_type_declaration",),
            "method": (
                "method_declaration",
                "method_definition",
                "function_definition",
                "constructor_declaration",
            ),
            "function": (
                "method_declaration",
                "method_definition",
                "function_definition",
                "constructor_declaration",
            ),
        }
        kinds = kind_map.get(target)
        return list(kinds) if kinds else None

    @staticmethod
    def _resource_patterns(target: str) -> list[str] | None:
        """Return ``file_path`` GLOB patterns for a resource kind word.

        Resource kinds ("dockerfile", "makefile", "compose", "migration",
        "sql", ...) enumerate indexed resource chunks by filename pattern
        instead of FQN/node-type, so ``"all dockerfiles"`` returns every
        ``Dockerfile`` in the index. Returns ``None`` when *target* is not a
        resource kind.
        """
        patterns: dict[str, tuple[str, ...]] = {
            "dockerfile": ("*[Dd]ockerfile*",),
            "docker": ("*[Dd]ockerfile*", "*docker-compose*"),
            "compose": ("*docker-compose*",),
            "makefile": ("*[Mm]akefile*",),
            "migration": ("*[Mm]igration*.sql",),
            "sql": ("*.sql",),
            "pom": ("*pom.xml",),
            "gradle": ("*build.gradle*",),
            "yaml": ("*.yml", "*.yaml"),
            "yml": ("*.yml", "*.yaml"),
        }
        matches = patterns.get(target)
        return list(matches) if matches else None

    def _unparseable_files(self) -> list[str]:
        """Return indexed files the structural layer could not parse.

        These files were indexed through the line-based fallback chunker
        (recorded as ``parse_failed`` on ``file_checksums`` at index time), so
        the structural layer cannot guarantee a complete enumeration over
        them.
        """
        try:
            with self._db.connect() as conn:
                rows = conn.execute(
                    "SELECT file_path FROM file_checksums "
                    "WHERE parse_failed = 1 ORDER BY file_path;"
                ).fetchall()
        except Exception as exc:
            logger.warning("Unparseable-file lookup failed: %s", exc)
            return []
        return [r["file_path"] for r in rows]

    def _apply_file_coherence(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Reward files with multiple matching chunks and dedup to one
        result per file.

        Groups fused candidates by ``file_path``, computes each file's
        ``file_score = max(chunk_scores) + coherence_bonus * log2(1 + n)``,
        and emits ONLY the highest-scoring chunk per file so every ``file_path``
        appears at most once per result set. Returns the deduped, re-sorted
        result list.
        """
        if not results:
            return results

        by_file: dict[str, list[dict[str, Any]]] = {}
        for r in results:
            by_file.setdefault(r["file_path"], []).append(r)

        bonus = self._settings.coherence_bonus
        deduped: list[dict[str, Any]] = []
        for _file_path, chunks in by_file.items():
            file_score = max(c["score"] for c in chunks) + bonus * math.log2(1 + len(chunks))
            best = max(chunks, key=lambda c: (c["score"], -c["line_start"]))
            best["score"] = file_score
            best["file_matches"] = len(chunks)
            deduped.append(best)

        deduped.sort(key=lambda r: r["score"], reverse=True)
        return deduped

    def invalidate_bm25_corpus(self) -> None:
        """Invalidate the cached BM25 corpus statistics after re-indexing."""
        self._bm25.invalidate_corpus()

    def reset_caches(self) -> None:
        """Reset internal caches after an index rebuild.

        Clears lazily-initialized caches that may be stale after the index
        has been rebuilt: the symbol store, language vocabularies, and the
        last query analysis.
        """
        self._symbol_store = None
        self._vocab_by_language = None
        self._analysis = None
        self._bm25.invalidate_corpus()

    def need_index(self) -> bool:
        """Return whether the index has not reached the ``ready`` state."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT value FROM index_metadata WHERE key = 'index_status';"
            ).fetchone()
            if row is None:
                return True
            return row["value"] not in ("ready",)
