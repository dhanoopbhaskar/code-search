"""Exact occurrence counting for exhaustive mode.

Provides per-line occurrence counts where ``total`` = sum of ``per_line``
array, enabling verification against the grep ground-truth oracle.
"""

from __future__ import annotations

from typing import Any


def count_occurrences_per_line(
    text: str,
    pattern: str,
) -> dict[str, Any]:
    """Count occurrences of *pattern* per line in *text*.

    For each matching line, the count is the number of times *pattern*
    appears on that line. The ``total`` is the sum of all per-line counts.

    Args:
        text: The text to search within (multi-line string).
        pattern: The literal pattern to count.

    Returns:
        dict with keys:
        - ``literal``: The searched pattern
        - ``total``: Total number of occurrences across all matching lines
        - ``per_line``: List of occurrence counts, one per matching line
        - ``line_numbers``: List of line numbers (1-indexed) where matches occur
    """
    if not text or not pattern:
        return {
            "literal": pattern,
            "total": 0,
            "per_line": [],
            "line_numbers": [],
        }

    per_line: list[int] = []
    line_numbers: list[int] = []

    lines = text.splitlines()

    for idx, line in enumerate(lines, start=1):
        count = line.count(pattern)
        if count > 0:
            per_line.append(count)
            line_numbers.append(idx)

    total = sum(per_line) if per_line else 0

    return {
        "literal": pattern,
        "total": total,
        "per_line": per_line,
        "line_numbers": line_numbers,
    }
