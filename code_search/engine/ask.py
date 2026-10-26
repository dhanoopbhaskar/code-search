"""Single-question router over the existing retrieval surfaces.

``ask`` maps a natural-language question to the surface that can answer it —
``symbol`` for identifiers and definitions, the call graph for caller/callee
questions, implementation lookup for interface questions, exhaustive search for
quoted literals, and ranked search otherwise — and returns one compact answer
instead of making the caller choose among fifteen commands.

The router deliberately delegates every answer to the shared engine rule
(:meth:`SymbolStore.resolve_name`, ``EdgeStore.get_call_graph_page``,
:func:`find_implementations`, ``HybridSearch.search``) so an ``ask`` response
cannot disagree with the dedicated surface for the same request.
"""

from __future__ import annotations

import json
import re
from typing import Any

#: Default soft output budget in tokens (roughly ``chars / 4``).
DEFAULT_BUDGET_TOKENS = 1200

#: Maximum source lines included inline in a definition answer.
_DEFINITION_LINES = 40

_QUOTED_LITERAL = re.compile(r"""["'`]([^"'`]+)["'`]""")
_IDENTIFIER = re.compile(r"^[A-Za-z_$][\w$]*(?:[.:#][A-Za-z_$][\w$]*)*(?:\([^)]*\))?$")

_ROUTES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(?:who|what)\s+calls?\s+(?:into\s+)?(.+?)\??$", re.IGNORECASE), "callers"),
    (re.compile(r"^(?:callers|usages)\s+of\s+(.+?)\??$", re.IGNORECASE), "callers"),
    (re.compile(r"^who\s+invokes?\s+(.+?)\??$", re.IGNORECASE), "callers"),
    (re.compile(r"^what\s+does\s+(.+?)\s+(?:call|invoke)\??$", re.IGNORECASE), "callees"),
    (re.compile(r"^(?:callees|dependencies)\s+of\s+(.+?)\??$", re.IGNORECASE), "callees"),
    (re.compile(r"^(?:who|what)\s+implements?\s+(.+?)\??$", re.IGNORECASE), "implementations"),
    (re.compile(r"^implementations?\s+of\s+(.+?)\??$", re.IGNORECASE), "implementations"),
    (
        re.compile(r"^(?:where\s+is|where's)\s+(.+?)\s+(?:defined|declared)\??$", re.IGNORECASE),
        "definition",
    ),
    (re.compile(r"^(?:definition|declaration)\s+of\s+(.+?)\??$", re.IGNORECASE), "definition"),
    (re.compile(r"^what\s+is\s+(.+?)\??$", re.IGNORECASE), "definition"),
)


def _clean_target(raw: str) -> str:
    """Strip surrounding quotes and trailing punctuation from a route target."""
    return raw.strip().strip("`'\"").strip().rstrip("?.!,")


def _route(question: str) -> tuple[str, str | None]:
    """Return ``(intent, target)`` for *question*.

    A quoted literal wins over phrase routing because the quotes are an
    explicit request for exact text. Failing that, the first phrase pattern that
    matches selects the surface. Otherwise a bare identifier-shaped question is
    a definition lookup and everything else is ranked search.
    """
    literal = _QUOTED_LITERAL.search(question)
    if literal is not None:
        return "literal", literal.group(1)
    for pattern, intent in _ROUTES:
        match = pattern.match(question.strip())
        if match is not None:
            return intent, _clean_target(match.group(1))
    cleaned = _clean_target(question)
    if _IDENTIFIER.match(cleaned):
        return "definition", cleaned
    return "ranked", None


def _symbol_summary(symbol: dict[str, Any], redactor: Any | None) -> dict[str, Any]:
    """Return the compact identity/location fields of *symbol*.

    Args:
        symbol: A resolved symbol row.
        redactor: Optional redactor applied to the inline source.

    Returns:
        A payload with no absolute paths beyond the caller-supplied value.
    """
    source = "\n".join((symbol.get("source_code") or "").splitlines()[:_DEFINITION_LINES])
    redacted_count = 0
    if redactor is not None and source:
        source, redacted_count = redactor.redact(source)
    return {
        "fqn": symbol.get("fqn"),
        "canonical_fqn": symbol.get("canonical_fqn"),
        "name": symbol.get("name"),
        "kind": symbol.get("kind"),
        "file_path": symbol.get("file_path"),
        "line_start": symbol.get("line_start"),
        "line_end": symbol.get("line_end"),
        "signature": symbol.get("signature"),
        "docstring": symbol.get("docstring"),
        "source_code": source,
        "redacted_count": redacted_count,
    }


def _resolution_failure(envelope: dict[str, Any], answer_type: str) -> dict[str, Any]:
    """Build the honest not-found/ambiguous answer for a failed resolution."""
    return {
        "answer_type": answer_type,
        "outcome": envelope.get("outcome", answer_type),
        "candidates": envelope.get("candidates", []),
        "suggestion": envelope.get("suggestion"),
        "answer": None,
    }


def _call_graph_answer(
    comps: dict[str, Any],
    target: str,
    direction: str,
    limit: int,
) -> dict[str, Any]:
    """Answer a caller/callee question from the shared call-graph page."""
    envelope = comps["symbol_store"].resolve_name(target, prefer_type=True)
    if envelope["kind"] != "exact" or envelope["symbol"] is None:
        failure = _resolution_failure(envelope, envelope["kind"])
        failure["answer_type"] = "callers" if direction == "callers" else "callees"
        return failure
    symbol = envelope["symbol"]
    graph = comps["edge_store"].get_call_graph_page(
        symbol["id"], direction, 1, limit=limit, offset=0
    )
    rows = graph.get(direction, [])
    return {
        "answer_type": direction,
        "outcome": "resolved",
        "answer": {
            "symbol": _symbol_summary(symbol, None),
            direction: rows,
            "paging": graph.get("paging"),
        },
    }


def _implementations_answer(comps: dict[str, Any], target: str, limit: int) -> dict[str, Any]:
    """Answer an implementation question from the shared implementation rule."""
    from code_search.engine.implementations import find_implementations

    result = find_implementations(
        comps["symbol_store"],
        comps["edge_store"],
        target,
        max_depth=int(getattr(comps["settings"], "max_graph_depth", 5)),
    )
    rows = list(result.get("implementations") or [])[:limit]
    declaring = result.get("declaring_type") or {}
    return {
        "answer_type": "implementations",
        "outcome": result.get("outcome"),
        "answer": {
            "target": declaring.get("fqn") or result.get("symbol"),
            "implementations": rows,
            "total": len(result.get("implementations") or []),
        },
    }


def _definition_answer(comps: dict[str, Any], target: str) -> dict[str, Any]:
    """Answer a definition question from the shared resolution rule."""
    envelope = comps["symbol_store"].resolve_name(target, prefer_type=True)
    if envelope["kind"] != "exact" or envelope["symbol"] is None:
        return _resolution_failure(envelope, "definition")
    return {
        "answer_type": "definition",
        "outcome": envelope.get("outcome", "resolved"),
        "answer": _symbol_summary(envelope["symbol"], comps.get("redactor")),
    }


def _search_answer(
    comps: dict[str, Any],
    query: str,
    *,
    limit: int,
    strict: bool,
    include_tests: bool,
    content: str | None,
    mode: str,
    matching: str | None,
) -> dict[str, Any]:
    """Answer from the ranked or exhaustive search path, compacted for agents."""
    from code_search.engine.response_service import compact_results, relativize_results

    envelope = comps["search"].search(
        query=query,
        limit=limit,
        include_tests=include_tests,
        mode=mode,
        content=content,
        matching=matching,
        strict=strict,
    )
    root = comps["metadata"].get("index_root")
    rows = compact_results(envelope.get("results") or [], 10)
    rows = relativize_results(rows, root)
    return {
        "answer_type": "literal" if mode == "exhaustive" else "ranked",
        "outcome": "no_match" if envelope.get("no_match") else "resolved",
        "answer": {
            "results": rows,
            "confidence": envelope.get("confidence"),
            "explanation": envelope.get("explanation"),
            "total_matches": envelope.get("total_matches", envelope.get("total_count")),
            "no_match": bool(envelope.get("no_match")),
            "alternatives": relativize_results(
                compact_results(envelope.get("alternatives") or [], 10), root
            ),
            "mode": envelope.get("mode"),
        },
    }


def _relativize_payload(payload: Any, root: str | None) -> Any:
    """Strip the index root from every path-like field in *payload*.

    ``file_path`` and ``fqn`` carry the absolute index prefix on the engine
    surface. An ``ask`` answer is an agent-facing payload, so it uses the same
    repo-relative spelling as compact search results.

    Args:
        payload: The answer payload (nested dicts/lists).
        root: The indexed repository root.

    Returns:
        The same structure with portable path spellings.
    """
    if not root:
        return payload
    from pathlib import Path

    from code_search.engine.graph_query import relative_display

    prefix = str(Path(root).resolve())

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if (
                    key in ("file_path", "fqn")
                    and isinstance(value, str)
                    and value.startswith(prefix)
                ):
                    if key == "fqn":
                        node[key] = value[len(prefix) :].lstrip("/\\")
                    else:
                        node[key] = relative_display(value, root)
                elif isinstance(value, (dict, list)):
                    _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(payload)
    return payload


def _next_steps(payload: dict[str, Any]) -> list[str]:
    """Return follow-up command suggestions for *payload*."""
    answer = payload.get("answer") or {}
    answer_type = payload.get("answer_type")
    if answer_type == "definition" and answer.get("fqn"):
        fqn = answer["fqn"]
        return [
            f"code-search view {fqn} --outline",
            f"code-search graph {fqn} --direction callers",
            f"code-search explain {fqn}",
        ]
    if answer_type in ("callers", "callees"):
        symbol = (answer.get("symbol") or {}).get("fqn")
        if symbol:
            return [
                f"code-search graph {symbol} --direction callers --limit 50",
                f"code-search graph {symbol} --direction callees --limit 50",
                f"code-search explain {symbol}",
            ]
    if answer_type == "implementations":
        target = answer.get("target")
        if isinstance(target, str):
            return [f"code-search implementations {target}", f"code-search explain {target}"]
    results = answer.get("results") or []
    if results:
        first = results[0]
        suggestions = []
        if first.get("fqn"):
            suggestions.append(f"code-search view {first['fqn']} --outline")
            suggestions.append(f"code-search symbol {first['fqn']}")
        if first.get("file_path"):
            suggestions.append(f"code-search outline {first['file_path']}")
        return suggestions
    return ['code-search search "<broader query>"']


def _payload_size(payload: dict[str, Any]) -> int:
    """Return the serialized character size of *payload*."""
    return len(json.dumps(payload, default=str))


def _fit_budget(payload: dict[str, Any], budget_tokens: int) -> dict[str, Any]:
    """Trim list rows and inline source until the payload fits *budget_tokens*.

    Trimming is deterministic: rows are dropped from the end of the first
    present answer list, then inline source is removed, then the payload is
    returned as-is. The response records ``truncated: true`` when anything was
    removed.

    Args:
        payload: The answer payload to trim in place.
        budget_tokens: Soft token budget (``chars / 4`` approximation).

    Returns:
        The trimmed payload.
    """
    max_chars = max(200, int(budget_tokens) * 4)
    if _payload_size(payload) <= max_chars:
        return payload
    answer = payload.get("answer")
    if isinstance(answer, dict):
        for key in ("results", "callers", "callees", "implementations", "alternatives"):
            rows = answer.get(key)
            if not isinstance(rows, list):
                continue
            while rows and _payload_size(payload) > max_chars:
                rows.pop()
                payload["truncated"] = True
        if _payload_size(payload) > max_chars and answer.get("source_code"):
            answer["source_code"] = ""
            answer["source_omitted"] = True
            payload["truncated"] = True
    if _payload_size(payload) > max_chars:
        payload["budget_exceeded"] = True
    return payload


def ask(
    comps: dict[str, Any],
    question: str,
    *,
    limit: int = 10,
    budget: int = DEFAULT_BUDGET_TOKENS,
    strict: bool = False,
    include_tests: bool = False,
    content: str | None = None,
) -> dict[str, Any]:
    """Route *question* to the surface that can answer it.

    Args:
        comps: The initialised component registry (``symbol_store``,
            ``edge_store``, ``search``, ``metadata``, ``settings``).
        question: The user's question (natural language, identifier, FQN, or a
            quoted literal).
        limit: Maximum rows in a callers/callees/implementations/ranked answer.
        budget: Soft output budget in tokens.
        strict: Apply the strict abstention gate to ranked search answers.
        include_tests: Include test files in search answers.
        content: Optional content scope for search answers.

    Returns:
        A compact payload with ``question``, ``answer_type``, ``outcome``,
        ``answer``, and ``next``. ``truncated``/``budget_exceeded`` appear when
        trimming was necessary.
    """
    question = question.strip()
    intent, target = _route(question)

    if intent == "callers" and target:
        payload = _call_graph_answer(comps, target, "callers", limit)
    elif intent == "callees" and target:
        payload = _call_graph_answer(comps, target, "callees", limit)
    elif intent == "implementations" and target:
        payload = _implementations_answer(comps, target, limit)
    elif intent == "definition" and target:
        payload = _definition_answer(comps, target)
    elif intent == "literal" and target:
        payload = _search_answer(
            comps,
            target,
            limit=limit,
            strict=False,
            include_tests=include_tests,
            content=content,
            mode="exhaustive",
            matching="literal",
        )
    else:
        payload = _search_answer(
            comps,
            question,
            limit=limit,
            strict=strict,
            include_tests=include_tests,
            content=content,
            mode="ranked",
            matching=None,
        )

    payload.setdefault("question", question)
    payload = _relativize_payload(payload, comps["metadata"].get("index_root"))
    payload["next"] = _next_steps(payload)
    return _fit_budget(payload, budget)
