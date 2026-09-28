"""Query-time language inference and definition-intent detection.

Produces the query-analysis entity: ``expanded_text`` (via
``ExpansionTable``), ``exact_tokens`` (exact corpus-vocabulary sub-words only —
never prefix — the root-cause fix), ``coverage`` computed AFTER expansion
(expand-first, then gate ordering), ``inferred_language`` (explicit > symbol >
vocab), and ``definition_intent``/``definition_target`` resolved via
``SymbolStore.resolve_name``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src.engine.config import Settings

_DEFINITION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"definition\s+of\s+(.+)", re.IGNORECASE),
    re.compile(r"where\s+is\s+(.+?)\s+defined", re.IGNORECASE),
    re.compile(r"what\s+is\s+(.+)", re.IGNORECASE),
    re.compile(r"define\s+(.+)", re.IGNORECASE),
)

_SYMBOL_CHARS = re.compile(r"[^A-Za-z0-9_.]")


@dataclass
class QueryAnalysis:
    """The query-time trust-signal entity.

    Produced by :func:`analyze_query` and consumed by the search/rerank
    pipeline to drive the trust gates.

    Attributes:
        query: The raw query as received.
        expanded_text: The query after synonym/expansion resolution.
        exact_tokens: Corpus-vocabulary sub-words present in the expanded text
            (exact matches only, never prefix).
        coverage: The fraction of concept sub-words that appear exactly in the
            vocabulary — computed after expansion and gating ordering.
        inferred_language: The language inferred for the query, or ``None`` to
            keep search unscoped.
        definition_intent: Whether the query asks for a definition.
        definition_target: The resolved symbol FQN when definition intent is
            detected and the target resolves, else ``None``.
    """

    query: str
    expanded_text: str
    exact_tokens: list[str] = field(default_factory=list)
    coverage: float = 0.0
    inferred_language: str | None = None
    definition_intent: bool = False
    definition_target: str | None = None


def _concept_subwords(text: str) -> list[str]:
    """Return the concept tokens of *text* that count toward coverage.

    Sub-words qualify as concept tokens when they are at least 3 characters
    long, are not a stopword, and are not a generic code term — they form the
    coverage denominator.

    Args:
        text: The text (usually the expanded query) to decompose.

    Returns:
        The qualifying concept sub-words, in decomposition order.
    """
    from src.engine.search import NON_INFORMATIVE_CODE_TERMS, STOPWORDS, decompose_query

    return [
        w
        for w in decompose_query(text)
        if len(w) >= 3 and w not in STOPWORDS and w not in NON_INFORMATIVE_CODE_TERMS
    ]


def _clean_symbol_target(raw: str) -> str:
    """Strip punctuation and whitespace from a definition target expression.

    Keeps only ``[A-Za-z0-9_.]`` characters (preserving dotted FQNs) so the
    captured pattern group from a definition phrase can be fed to
    ``SymbolStore.resolve_name``.

    Args:
        raw: The raw captured target text from a definition pattern.

    Returns:
        The cleaned symbol target string; may be empty if nothing remained.
    """
    return _SYMBOL_CHARS.sub("", raw.strip())


def language_vocabularies(db: Any) -> dict[str, set[str]]:
    """Map each indexed language to the set of exact sub-words in its chunks.

    Args:
        db: A database exposing a ``connect()`` context manager whose
            ``code_chunks`` table has ``language`` and ``subwords`` columns.

    Returns:
        A mapping of language name to the set of sub-words observed in that
        language's chunks; empty when the lookup fails or no rows exist.
    """
    result: dict[str, set[str]] = {}
    try:
        with db.connect() as conn:
            rows = conn.execute("SELECT language, subwords FROM code_chunks;").fetchall()
        for row in rows:
            lang = row["language"] or "unknown"
            bucket = result.setdefault(lang, set())
            for w in (row["subwords"] or "").split():
                bucket.add(w)
    except Exception:
        pass
    return result


def infer_query_language(
    query: str,
    symbol_store: Any | None = None,
    vocab_by_language: dict[str, set[str]] | None = None,
) -> str | None:
    """Infer the query's language: symbol-resolved leaf > single-language vocab.

    A single-token query that resolves to an exact symbol first wins via the
    symbol's stored language. Otherwise the query's concept sub-words are
    matched against each language's vocabulary, and a language is returned
    only when exactly one language contains all of them. ``None`` keeps the
    search unscoped. An explicit ``language`` argument is handled by the
    caller and never overridden here.

    Args:
        query: The raw user query.
        symbol_store: Optional symbol store used to resolve single-token
            queries to an exact symbol with a known language.
        vocab_by_language: Per-language exact sub-word vocabularies, as
            returned by :func:`language_vocabularies`.

    Returns:
        The inferred language name, or ``None`` when the language is ambiguous
        or undeterminable.
    """
    if symbol_store is not None and " " not in query.strip():
        try:
            envelope = symbol_store.resolve_name(query, max_candidates=1)
        except Exception:
            envelope = {"kind": "not_found", "symbol": None}
        if envelope.get("kind") == "exact":
            symbol = envelope.get("symbol") or {}
            lang = symbol.get("language")
            if isinstance(lang, str) and lang:
                return lang

    if not vocab_by_language:
        return None
    exact_subwords = _concept_subwords(query)
    languages_with_hits: set[str] = set()
    for w in exact_subwords:
        for lang, vocab in vocab_by_language.items():
            if w in vocab:
                languages_with_hits.add(lang)
    if len(languages_with_hits) == 1:
        return next(iter(languages_with_hits))
    return None


def detect_definition_intent(
    query: str,
    symbol_store: Any | None = None,
) -> tuple[bool, str | None]:
    """Return ``(definition_intent, definition_target)``.

    ``definition_target`` is the FQN of the symbol resolved from the target
    expression when definition phrasing is detected AND the target resolves via
    ``SymbolStore.resolve_name``.

    Args:
        query: The raw user query.
        symbol_store: Optional symbol store used to resolve the captured
            definition target to a canonical FQN.

    Returns:
        A tuple of ``(definition_intent, definition_target)`` where
        *definition_target* is the resolved FQN or ``None`` when no target was
        captured or resolved.
    """
    for pattern in _DEFINITION_PATTERNS:
        match = pattern.search(query)
        if not match:
            continue
        target = _clean_symbol_target(match.group(1))
        if not target:
            continue
        resolved_fqn: str | None = None
        if symbol_store is not None:
            try:
                envelope = symbol_store.resolve_name(target, max_candidates=1)
            except Exception:
                envelope = {"kind": "not_found", "symbol": None}
            if envelope.get("kind") == "exact":
                symbol = envelope.get("symbol") or {}
                resolved_fqn = symbol.get("fqn") or None
        return True, resolved_fqn
    return False, None


def embedded_symbols(query: str, symbol_store: Any | None = None) -> list[str]:
    """Return the resolved symbol short names embedded in an NL *query*.

    Scans identifier-shaped tokens (camelCase / snake_case words) and keeps
    only those that resolve EXACTLY via ``SymbolStore.resolve_name`` — a
    prefix/substring resemblance never fires. Common capitalized
    words (``The``, ``This``) that are not actual symbols resolve to nothing
    and are skipped.

    Args:
        query: The raw user query (case preserved, so ``StateManager`` in
            prose resolves while ``statemanager`` does not).
        symbol_store: An optional symbol store used for exact resolution;
            ``None`` returns an empty list (the caller owns the gate).

    Returns:
        The sorted unique resolved symbol names.
    """
    if symbol_store is None:
        return []
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", query)
    found: set[str] = set()
    for tok in tokens:
        if "_" not in tok and not (tok != tok.lower() and tok != tok.upper()):
            continue
        try:
            envelope = symbol_store.resolve_name(tok, max_candidates=1)
        except Exception:
            continue
        if envelope.get("kind") != "exact":
            continue
        symbol = envelope.get("symbol") or {}
        name = symbol.get("name")
        if isinstance(name, str) and name == tok:
            found.add(name)
    return sorted(found)


_UNSET = object()


def analyze_query(
    query: str,
    settings: Settings,
    vocabulary: set[str] | None = None,
    expansion_table: Any | None = None,
    symbol_store: Any | None = None,
    vocab_by_language: dict[str, set[str]] | None = None,
    explicit_language: str | None = None,
) -> QueryAnalysis:
    """Build the Query Analysis entity for *query* (the ONE shared rule).

    ``coverage`` is always computed AFTER expansion and over exact tokens only
    (never prefix). ``inferred_language`` respects an explicit language first.

    Args:
        query: The raw user query.
        settings: Runtime settings, used to locate the expansion table when
            none is supplied.
        vocabulary: The exact corpus vocabulary (all sub-words in the index);
            when ``None``, coverage and exact tokens resolve to zero/empty.
        expansion_table: An :class:`~src.engine.expansions.ExpansionTable`;
            built from ``settings.expansion_file`` when ``None``.
        symbol_store: Optional symbol store for definition-target resolution
            and language inference.
        vocab_by_language: Per-language vocabularies for language inference.
        explicit_language: Language supplied by the caller; always takes
            precedence over inferred language.

    Returns:
        A :class:`QueryAnalysis` carrying the expanded text, exact tokens,
        coverage, inferred language, and definition intent.
    """
    expanded_text = query
    table = expansion_table
    if table is None and settings.expansion_file:
        from src.engine.expansions import ExpansionTable

        table = ExpansionTable(config_path=settings.expansion_file)
    if table is not None:
        expanded_text = table.expanded_text(query)

    concept = _concept_subwords(expanded_text)
    exact_tokens = [w for w in concept if w in (vocabulary or set())]
    coverage = len(exact_tokens) / len(concept) if concept else 0.0

    if explicit_language is not None:
        inferred_language: str | None = explicit_language
    else:
        inferred_language = infer_query_language(
            query,
            symbol_store=symbol_store,
            vocab_by_language=vocab_by_language,
        )

    definition_intent, definition_target = detect_definition_intent(query, symbol_store)

    return QueryAnalysis(
        query=query,
        expanded_text=expanded_text,
        exact_tokens=exact_tokens,
        coverage=coverage,
        inferred_language=inferred_language,
        definition_intent=definition_intent,
        definition_target=definition_target,
    )
