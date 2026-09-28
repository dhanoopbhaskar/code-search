"""Lexical relevance threshold for the rescue tier.

Defines the floor parameters that gate the rescue tier, ensuring
pure-gibberish queries return ``no_match`` while borderline queries
still return results.
"""

from __future__ import annotations

from typing import Any

# Default configuration per rescue_floor_contract.md
DEFAULT_LEXICAL_THRESHOLD: float = 0.15
DEFAULT_PURE_GIBBERISH_NO_MATCH: bool = True
DEFAULT_BORDERLINE_REAL_ALLOWED: bool = True
DEFAULT_NO_MATCH_ENVELOPE: str = (
    "No relevant results found. The query text does not match any indexed content."
)


def evaluate_rescue_floor(
    query_tokens: list[str],
    indexed_content_tokens: set[str],
    lexical_score: float,
) -> dict[str, Any]:
    """Evaluate whether the rescue tier should return results based on the lexical floor.

    Args:
        query_tokens: Individual tokens from the user query.
        indexed_content_tokens: Tokens from the indexed content.
        lexical_score: Computed lexical relevance score.

    Returns:
        dict with keys:
        - ``return_rescue`` (bool): Whether to return rescue tier results
        - ``pure_gibberish`` (bool): Whether query is pure-gibberish
        - ``borderline_real`` (bool): Whether query has one meaningful token
        - ``envelope`` (str | None): Envelope text if rescue is gated, None otherwise
    """
    # Pure-gibberish detection: zero meaningful overlap with indexed content
    has_meaningful_overlap = bool(
        query_tokens
        and indexed_content_tokens
        and any(token in indexed_content_tokens for token in query_tokens)
    )

    pure_gibberish = not has_meaningful_overlap

    borderline_real = not pure_gibberish  # has at least one meaningful token

    # Apply lexical threshold
    return_rescue = (lexical_score >= DEFAULT_LEXICAL_THRESHOLD and not pure_gibberish) or (
        DEFAULT_BORDERLINE_REAL_ALLOWED and borderline_real and lexical_score > 0.0
    )

    envelope = DEFAULT_NO_MATCH_ENVELOPE if not return_rescue and pure_gibberish else None

    return {
        "return_rescue": return_rescue,
        "pure_gibberish": pure_gibberish,
        "borderline_real": borderline_real,
        "envelope": envelope,
    }
