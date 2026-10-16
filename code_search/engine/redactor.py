"""Secret redaction and air-gap enforcement for enterprise compliance.

Redact uses regex-based pattern matching to detect and replace secrets
(API keys, tokens, passwords, etc.) with a ``[REDACTED]`` placeholder.
Air-gap enforcement monkey-patches ``socket`` to prevent outbound
connections at runtime.
"""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Generator
from typing import Any

logger = logging.getLogger(__name__)

# List of ``(name, label, compiled_pattern)`` tuples for secret detection.
SECRET_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "api_key",
        "API key (generic)",
        re.compile(
            r"(?i)(?:api[_-]?key|api[_-]?secret|app[_-]?secret)\s*[:=]\s*['\"]([^'\"]{8,})['\"]"
        ),
    ),
    ("jwt", "JWT token", re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]+")),
    ("aws_key", "AWS access key", re.compile(r"(?i)AKIA[0-9A-Z]{16}")),
    (
        "aws_secret",
        "AWS secret key",
        re.compile(r"(?i)aws[_-]?secret[_-]?access[_-]?key\s*[:=]\s*['\"]([^'\"]{8,})['\"]"),
    ),
    ("private_key", "Private key (PEM)", re.compile(r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----")),
    (
        "password",
        "Password assignment",
        re.compile(r"(?i)(?:password|passwd|pwd)\s*[:=]\s*['\"]([^'\"]{4,})['\"]"),
    ),
    ("token", "Auth token/bearer", re.compile(r"(?i)(?:bearer|token|auth)\s+[a-zA-Z0-9_\-]{20,}")),
    ("github_token", "GitHub token", re.compile(r"(?i)ghp_[a-zA-Z0-9]{36}")),
    ("slack_token", "Slack token", re.compile(r"xox[baprs]-[a-zA-Z0-9\-]{10,}")),
    (
        "connection_string",
        "Database connection string",
        re.compile(r"(?i)(?:postgres(?:ql)?|mysql|mongodb|redis)://[^@\s]+:[^@\s]+@"),
    ),
    ("ssl_key", "SSL/TLS key", re.compile(r"-----BEGIN\s+CERTIFICATE-----")),
    ("npm_token", "npm token", re.compile(r"(?i)npm_[a-zA-Z0-9]{36}")),
    (
        "generic_secret",
        "Generic secret value",
        re.compile(r"""['\"](?:sk|pk|rk|ek)_[a-zA-Z0-9]{8,}['\"]"""),
    ),
    (
        "property_secret",
        "Property-file secret value",
        re.compile(
            r"(?i)(?:secret|token|apikey|api[_-]?key|credential|jwt[._-]?secret|"
            r"encryption[._-]?key|signing[._-]?key)\s*[=:]\s*(?:"
            r"['\"][^'\"]{4,}['\"]"  # quoted string literal
            r"|(?:sk|pk|rk|ek)_[a-zA-Z0-9]{8,}"  # well-known secret prefix
            r"|eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+"  # JWT
            r")"
        ),
    ),
    (
        "spring_secret",
        "Spring Boot config secret",
        re.compile(
            r"(?i)(?:spring\.(?:datasource|security|mail)\.(?:password|username)|"
            r"jwt\.(?:secret|token|key))\s*=\s*(\S{8,})"
        ),
    ),
]

REDACTED_PLACEHOLDER = "[REDACTED]"

_JWT_SHAPE = re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]+(\.[a-zA-Z0-9_-]+)?")
_CONNECTION_STRING_SHAPE = re.compile(r"://[^@\s]+:[^@\s]+@")


def _is_method_invocation_expression(span: str) -> bool:
    """Return True if *span* reads as a code expression rather than a secret.

    Method-invocation expressions contain a ``(`` and/or a ``.`` (member
    access) but carry none of the markers of a genuine secret: no quoted
    string literal, no JWT shape, no connection-string shape. A ``key=value``
    assignment (``jwt.secret=...``, ``spring.datasource.password=...``) is a
    config-file secret, not a code expression, so it is never excluded here.
    """
    if "(" not in span and "." not in span:
        return False
    if "=" in span and "." in span and "(" not in span:
        return False
    if '"' in span or "'" in span:
        return False
    if _JWT_SHAPE.search(span):
        return False
    return not _CONNECTION_STRING_SHAPE.search(span)


_download_exempt: int = 0


@contextlib.contextmanager
def allow_downloads() -> Generator[None, None, None]:
    """Context manager that temporarily allows outbound socket connections.

    Increments ``_download_exempt`` counter so that ``air_gap_enforcement``
    skips socket blocking while this context is active.
    """
    global _download_exempt
    _download_exempt += 1
    try:
        yield
    finally:
        _download_exempt -= 1


@contextlib.contextmanager
def air_gap_enforcement() -> Generator[None, None, None]:
    """Context manager that blocks all outbound socket connections.

    Monkey-patches ``socket.socket`` to raise ``RuntimeError`` on
    ``connect()`` / ``connect_ex()``. Skips blocking when
    ``_download_exempt > 0`` (used by the ``download-models`` command).
    """
    import socket as _socket_module

    _original_socket = _socket_module.socket

    class _AirGapSocket(_original_socket):  # type: ignore[valid-type,misc]
        """Socket subclass that blocks outbound connects while installed.

        ``connect`` / ``connect_ex`` raise ``RuntimeError`` unless downloads
        are exempt (``_download_exempt > 0``) or the socket is a local
        ``AF_UNIX`` IPC socket.
        """

        def _is_local_socket(self) -> bool:
            """Return whether this socket is a local (AF_UNIX) IPC socket.

            Local unix sockets are intra-host IPC and never touch the
            network, so they are exempt from air-gap blocking.
            """
            try:
                return bool(self.family == _socket_module.AF_UNIX)
            except Exception:
                return False

        def connect(self, *args: Any, **kwargs: Any) -> None:
            """Block outbound connects unless downloads are exempt or the
            socket is local."""
            if _download_exempt > 0 or self._is_local_socket():
                return _original_socket.connect(self, *args, **kwargs)
            raise RuntimeError(
                "Air-gap violation: socket.connect() called. "
                "This application must not make outbound network connections."
            )

        def connect_ex(self, *args: Any, **kwargs: Any) -> int:
            """Block outbound non-raising connects unless exempt or local."""
            if _download_exempt > 0 or self._is_local_socket():
                return _original_socket.connect_ex(self, *args, **kwargs)
            raise RuntimeError(
                "Air-gap violation: socket.connect_ex() called. "
                "This application must not make outbound network connections."
            )

    try:
        _socket_module.socket = _AirGapSocket  # type: ignore[misc]
        yield
    finally:
        _socket_module.socket = _original_socket  # type: ignore[misc]


def verify_air_gap() -> bool:
    """Verify that air-gap enforcement is active by attempting a local connection.

    Runs one connection attempt inside :func:`air_gap_enforcement`; the
    expected ``RuntimeError`` is suppressed, so a ``True`` result confirms the
    blocking socket patch is installed.

    Returns:
        ``True`` when the enforcement context activates without error,
        ``False`` otherwise.
    """
    try:
        with air_gap_enforcement():
            import socket

            with contextlib.suppress(RuntimeError):
                socket.socket().connect(("127.0.0.1", 1))
        logger.info("Air-gap compliance check passed")
        return True
    except Exception as exc:
        logger.error("Air-gap compliance check failed: %s", exc)
        return False


class Redactor:
    """Regex-based secret redactor.

    Applies a list of secret patterns to text, replacing matches with
    ``[REDACTED]``. Tracks the number of redactions performed.
    """

    def __init__(self, patterns: list[tuple[str, str, re.Pattern[str]]] | None = None) -> None:
        """Create a redactor using the given patterns or the built-in defaults.

        Args:
            patterns: List of ``(name, label, compiled_pattern)`` tuples; when
                ``None``, the module-level :data:`SECRET_PATTERNS` are used.
        """
        self._patterns = patterns or SECRET_PATTERNS

    def redact(self, text: str) -> tuple[str, int]:
        """Redact secrets in *text*, returning ``(redacted_text, count)``.

        Applies all patterns against the original text, merges overlapping
        spans, and replaces merged spans to avoid interference between
        patterns. Matches that read as method-invocation code expressions
        rather than secrets are excluded.

        Args:
            text: The text to scan for secrets.

        Returns:
            A tuple of the redacted text and the number of distinct spans
            replaced; ``(text, 0)`` when nothing matched.
        """
        if not text:
            return text, 0
        matches: list[tuple[int, int]] = []
        for _name, _label, pattern in self._patterns:
            for m in pattern.finditer(text):
                matches.append((m.start(), m.end()))
        if not matches:
            return text, 0
        matches.sort()
        merged: list[tuple[int, int]] = [matches[0]]
        for start, end in matches[1:]:
            if start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        kept = [
            (start, end)
            for start, end in merged
            if not _is_method_invocation_expression(text[start:end])
        ]
        if not kept:
            return text, 0
        result = list(text)
        for start, end in reversed(kept):
            result[start:end] = REDACTED_PLACEHOLDER
        return "".join(result), len(kept)

    def redact_results(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Redact the ``"content"`` (and, when present, ``"line_content"``)
        fields of every result dict in place.

        Exhaustive-mode items carry the matching line in ``line_content``, so
        it is masked alongside the ranked ``content`` snippet. Each result
        gains a ``"redacted_count"`` key holding the number of spans replaced
        for that entry.

        Args:
            results: List of result dicts, each with a ``"content"`` field.

        Returns:
            The same list with redacted content and counts attached.
        """
        redacted_results = []
        total_redacted = 0
        for r in results:
            content = r.get("content") or ""
            redacted_content, redacted_count = self.redact(content)
            r["content"] = redacted_content
            line_content = r.get("line_content")
            if line_content:
                redacted_line, line_count = self.redact(line_content)
                r["line_content"] = redacted_line
                redacted_count += line_count
            r["redacted_count"] = redacted_count
            total_redacted += redacted_count
            redacted_results.append(r)
        return redacted_results
