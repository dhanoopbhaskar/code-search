"""Deterministic chunk representation for the semantic embedding layer.

Single-sources the text a chunk is embedded from: the chunk's own declaration
and body prefixed with its nearest enclosing structural context (module/file
path and declaring-type chain), bounded by the model input budget with
deterministic truncation that keeps the body ahead of the optional context.
Pure functions only — no database, model, or I/O — so the scheme is
unit-testable without an index.

``REPRESENTATION_SCHEME_VERSION`` travels with the builder: it identifies which
representation scheme produced a stored embedding so embeddings from an older
scheme are detected as stale and regenerated rather than trusted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Bump when the derivation below changes so stale embeddings are detected.
REPRESENTATION_SCHEME_VERSION = 1

#: Content axes that must not receive a code-type chain.
_NON_CODE_KINDS = frozenset({"resource", "config", "docs"})


@dataclass(frozen=True)
class EnclosingContext:
    """Nearest enclosing structural context of a chunk.

    Attributes:
        module: The chunk's module/file identity (its ``file_path``).
        chain: Container ancestor names, outermost -> innermost, excluding the
            chunk's own defining symbol.
        kind: The content axis the rule was applied for: ``code``, ``config``,
            ``resource``, or ``docs``.
    """

    module: str
    chain: tuple[str, ...]
    kind: str


def _classify_kind(chunk: dict[str, Any]) -> str:
    """Return the content axis driving the enrichment rule for *chunk*.

    A resource chunk and any chunk classified as config/docs are non-code and
    receive no declaring-type chain; everything else is code.
    """
    content_type = str(chunk.get("content_type") or "code")
    if content_type in _NON_CODE_KINDS:
        return content_type
    if str(chunk.get("chunk_type") or "ast") == "resource":
        return "resource"
    return "code"


def _smallest_containing_symbol(
    chunk: dict[str, Any], symbols: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the smallest symbol whose line span contains the chunk start.

    Mirrors the rule used by ``_resolve_chunk_fqn`` so the context is derived
    from the same attribution the chunk already carries.
    """
    chunk_start = chunk.get("line_start")
    if chunk_start is None:
        return None
    best: dict[str, Any] | None = None
    best_span: int | None = None
    for symbol in symbols:
        start = symbol.get("line_start")
        end = symbol.get("line_end")
        if start is None or end is None or chunk_start < start or chunk_start > end:
            continue
        span = end - start
        if best is None or best_span is None or span < best_span:
            best = symbol
            best_span = span
    return best


def _enclosing_chain(
    defining: dict[str, Any], by_fqn: dict[str, dict[str, Any]]
) -> tuple[str, ...]:
    """Build the outermost -> innermost ancestor-name chain for *defining*.

    Walks ``parent_fqn`` links through *by_fqn*, collecting each ancestor's
    ``name`` and excluding the defining symbol itself. Guarded against
    cycles so malformed symbol trees cannot loop.
    """
    names: list[str] = []
    seen: set[str] = set()
    parent = defining.get("parent_fqn")
    while parent and parent not in seen:
        seen.add(parent)
        ancestor = by_fqn.get(str(parent))
        if ancestor is None:
            break
        name = str(ancestor.get("name") or "").strip()
        if name:
            names.append(name)
        parent = ancestor.get("parent_fqn")
    names.reverse()
    return tuple(names)


def _module_name(file_path: str) -> str:
    """Return the chunk's module identity: its immediate package name.

    Uses the file's parent directory name (the immediate package/directory, e.g.
    ``auth`` for ``.../com/example/auth/UserAuthenticate.java``) so the
    representation names its module without dragging in the full, checkout-
    dependent path. A file at the index root falls back to its stem so the
    module context is never empty.
    """
    normalized = file_path.replace("\\", "/")
    directory, filename = normalized.rsplit("/", 1) if "/" in normalized else ("", normalized)
    if directory:
        return directory.rsplit("/", 1)[-1]
    return filename.rsplit(".", 1)[0]


def derive_enclosing_context(
    chunk: dict[str, Any], symbols: list[dict[str, Any]]
) -> EnclosingContext:
    """Derive the nearest enclosing context of *chunk* from *symbols*.

    Args:
        chunk: A parsed chunk with ``file_path``, ``line_start``, ``chunk_type``,
            and ``content_type``.
        symbols: The per-file symbol list the worker already computed.

    Returns:
        The :class:`EnclosingContext`. Code chunks carry the declaring-type
        chain; free/top-level functions fall back to the module path alone;
        resource/config/docs chunks carry the module path only with an
        empty chain.
    """
    module = _module_name(str(chunk.get("file_path", "") or ""))
    kind = _classify_kind(chunk)
    if kind != "code":
        return EnclosingContext(module=module, chain=(), kind=kind)

    defining = _smallest_containing_symbol(chunk, symbols)
    if defining is None:
        return EnclosingContext(module=module, chain=(), kind="code")
    by_fqn = {str(s["fqn"]): s for s in symbols if s.get("fqn")}
    return EnclosingContext(module=module, chain=_enclosing_chain(defining, by_fqn), kind="code")


def _format_prefix(context: EnclosingContext) -> str:
    """Render the context prefix as ``"<module> <chain>"`` (whitespace-stripped)."""
    parts = [context.module, *context.chain]
    return " ".join(part for part in parts if part).strip()


def build_embed_text(context: EnclosingContext | None, content: str, budget: int) -> str:
    """Compose the bounded text passed to the semantic model for a chunk.

    Precedence is deterministic: the full ``prefix + content`` when it
    fits the *budget*; otherwise the full content with the prefix truncated to
    the remaining budget; otherwise the content truncated head-first to the
    budget. Content therefore always takes precedence over optional context.

    Args:
        context: The chunk's enclosing context, or ``None`` when unavailable.
        content: The chunk body (declaration + body), never mutated.
        budget: Maximum characters of the returned text (floored at ``1``).

    Returns:
        The text to embed for the chunk.
    """
    body = content or ""
    limit = max(1, int(budget))
    prefix = _format_prefix(context) if isinstance(context, EnclosingContext) else ""
    if not prefix:
        return body[:limit]
    if len(prefix) + 1 + len(body) <= limit:
        return f"{prefix}\n{body}"
    remaining = limit - len(body) - 1
    if remaining > 0:
        return f"{prefix[:remaining]}\n{body}"
    return body[:limit]
