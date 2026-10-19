"""Pure natural-language query normalization.

Natural-language queries often use inflected forms (``favoriting``,
``following``, ``registered``) while the indexed code vocabulary uses the
stem (``favorite``, ``follow``, ``register``). This module provides the
morphological variants used by the lexical and confidence layers, plus a
concept collapse that prevents a single word's variants from diluting the
coverage denominator.

The functions are deliberately conservative and rule-based: they only touch
all-lowercase words, never identifiers that already decomposed cleanly, and
always keep the original word first. They perform no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable

#: Shortest word that can carry a morphological suffix worth stripping.
_MIN_INFLECTED_LENGTH = 4

#: Consonant endings that usually lost a trailing ``e`` before ``-ing``/``-ed``.
_E_RESTORE_ENDINGS = frozenset("tgcs vzk".replace(" ", ""))


def _restore_e(base: str) -> list[str]:
    """Return ``base + 'e'`` when *base* plausibly dropped a trailing ``e``.

    ``favorit`` -> ``favorite``, ``creat`` -> ``create``, ``us`` -> ``use``;
    ``follow`` stays ``follow`` because English does not spell it with a
    trailing ``e``. The heuristic is intentionally narrow so common words are
    not turned into false variants.

    Args:
        base: The word with its ``-ing``/``-ed`` suffix removed.

    Returns:
        A single-element list with the restored form, or an empty list.
    """
    if len(base) >= 3 and base[-1] in _E_RESTORE_ENDINGS:
        return [base + "e"]
    return []


def morphological_variants(word: str) -> list[str]:
    """Return *word* plus conservative base forms for common English suffixes.

    Handles plurals (``favorites`` -> ``favorite``), gerunds (``following`` ->
    ``follow``, ``favoriting`` -> ``favorit``/``favorite``), and past tense
    (``registered`` -> ``register``, ``updated`` -> ``updat``/``update``).
    Original spelling is always first and duplicates are removed; words that
    are not all-lowercase alphabetic tokens are returned unchanged so code
    identifiers keep their exact form.

    Args:
        word: A lowercased query sub-word.

    Returns:
        The variant list, starting with *word*.
    """
    out = [word]
    if len(word) < _MIN_INFLECTED_LENGTH or not word.isalpha() or not word.islower():
        return out

    candidates: list[str] = []
    if word.endswith("ies") and len(word) > 5:
        candidates.append(word[:-3] + "y")
    if word.endswith("ing") and len(word) > 5:
        base = word[:-3]
        if len(base) >= 3:
            candidates.append(base)
            if len(base) > 3 and base[-1] == base[-2] and base[-1] not in "aeiou":
                candidates.append(base[:-1])
            candidates.extend(_restore_e(base))
    if word.endswith("ed") and len(word) > 4 and not word.endswith("eed"):
        base = word[:-2]
        if len(base) >= 3:
            candidates.append(base)
            candidates.extend(_restore_e(base))
    if word.endswith("es") and len(word) > 4:
        candidates.extend([word[:-2], word[:-1]])
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 3:
        candidates.append(word[:-1])
    if word.endswith("ly") and len(word) > 5:
        candidates.append(word[:-2])

    for candidate in candidates:
        if candidate and candidate not in out:
            out.append(candidate)
    return out


def _prefix_related(left: str, right: str, min_prefix: int = 4) -> bool:
    """Return whether two terms share a prefix of at least *min_prefix* chars."""
    if left == right:
        return True
    if len(left) < min_prefix or len(right) < min_prefix:
        return False
    return left.startswith(right) or right.startswith(left)


def collapse_terms(
    terms: Iterable[str],
    min_prefix: int = 4,
    preferred: set[str] | None = None,
) -> list[str]:
    """Collapse prefix-related terms into one representative per concept.

    ``["following", "follow", "followe", "user"]`` becomes ``["follow",
    "user"]``; the shortest form is chosen so the representative is the stem
    that the indexed vocabulary is most likely to contain. Group order follows
    the first occurrence in *terms*.

    When *preferred* is supplied (typically the exact corpus vocabulary), the
    representative is the shortest member that appears in it, falling back to
    the shortest member when none does. This avoids choosing an intermediate
    stem such as ``favorit`` when the corpus spells the word ``favorite``.

    Args:
        terms: The query sub-words (possibly containing morphological variants).
        min_prefix: Minimum shared prefix length for two terms to be treated as
            the same concept.
        preferred: Optional vocabulary of exact forms to prefer.

    Returns:
        One representative per concept, in first-occurrence order.
    """
    groups: list[list[str]] = []
    for term in terms:
        if not term:
            continue
        for group in groups:
            if any(_prefix_related(term, existing, min_prefix) for existing in group):
                group.append(term)
                break
        else:
            groups.append([term])
    representatives: list[str] = []
    for group in groups:
        candidates = [term for term in group if preferred and term in preferred]
        representatives.append(min(candidates or group, key=len))
    return representatives


def concept_terms(terms: Iterable[str], min_length: int = 3) -> list[str]:
    """Return collapsed concept terms of at least *min_length* characters."""
    return [term for term in collapse_terms(terms) if len(term) >= min_length]
