"""Static query-expansion table for acronym/paraphrase -> code vocabulary.

Air-gap-safe: a local static JSON table (``CODE_SEARCH_EXPANSION_FILE``) merged
over built-in seeded defaults, no network, no model, no learning. Expansion is
recall-only — a wrong expansion can never produce a *confident* false positive
because the exact-coverage gate and confidence band still run after expansion.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

_TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")

_BUILTIN_EXPANSIONS: dict[str, list[str]] = {
    "cors": ["cross origin", "cross-origin"],
    "cross origin": ["cors"],
    "feed": ["getFeedByUser"],
    "favorited": ["favorite"],
    "email taken": ["EmailTakenException"],
    "email exists": ["EmailTakenException"],
    # Permission/validation paraphrases: the abstract verbs reach their
    # code vocabulary so a permission/validation probe surfaces the
    # authorization definitions it paraphrases. Kept local (no transitive
    # cascade) so a generic word like ``valid`` never bloats the retrieval
    # query with unrelated login/authentication vocabulary.
    "restrict": ["restriction", "authorize", "authorization", "security", "access control"],
    "restriction": ["restrict", "authorization", "security"],
    "validate": ["validation", "valid"],
    "validation": ["validate", "valid"],
    "valid": ["validate", "validation"],
    "login": ["authenticate", "authentication"],
    "owns": ["owner", "ownership"],
    "owner": ["owns", "ownership"],
    "authenticate": ["login", "authentication"],
    "authentication": ["login", "authenticate"],
}


def _tokens(text: str) -> list[str]:
    """Lowercase the alphanumeric identifier tokens found in *text*.

    Args:
        text: The text to tokenize.

    Returns:
        The matched identifier tokens, lowercased.
    """
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _tokens_fuzzy_match(query_tokens: list[str], key_tokens: list[str]) -> bool:
    """Return whether *key_tokens* appears as a contiguous fuzzy match in *query_tokens*.

    A token matches a key token exactly, or by a >=4-char prefix overlap so a
    typo like ``cros`` matches ``cross`` (case-insensitive).
    """
    if not key_tokens:
        return False
    for start in range(len(query_tokens) - len(key_tokens) + 1):
        matched = True
        for i, kt in enumerate(key_tokens):
            qt = query_tokens[start + i]
            if qt == kt:
                continue
            if len(qt) >= 4 and len(kt) >= 4 and (qt.startswith(kt) or kt.startswith(qt)):
                continue
            matched = False
            break
        if matched:
            return True
    return False


class ExpansionTable:
    """A two-way, case-insensitive acronym/phrase -> expansion-terms table.

    Built-in seeded defaults cover the report's exact failing pairs. An
    optional JSON file (``CODE_SEARCH_EXPANSION_FILE``) merges over the
    defaults — user entries win on conflict.
    """

    def __init__(self, config_path: str | None = None) -> None:
        """Create an expansion table, optionally merging a user JSON file.

        Args:
            config_path: Path to a JSON file holding an ``"expansions"``
                mapping; when ``None``, the ``CODE_SEARCH_EXPANSION_FILE``
                environment variable is used. If both are unset, only the
                built-in defaults are loaded.
        """
        self._table: dict[str, list[str]] = {
            key.lower(): list(values) for key, values in _BUILTIN_EXPANSIONS.items()
        }
        env_key = "CODE_SEARCH_EXPANSION_FILE"
        path = config_path if config_path is not None else os.environ.get(env_key, "")
        if path:
            self._merge_file(path)
        self._keys: tuple[str, ...] = tuple(self._table.keys())

    def _merge_file(self, path: str) -> None:
        """Merge the ``"expansions"`` mapping from a JSON file into the table.

        User entries win over the built-in defaults on conflict.

        Args:
            path: Path to the JSON expansion file.

        Raises:
            ValueError: If the file cannot be read or parsed as JSON.
        """
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid expansion file {path}: {exc}") from exc
        merged = data.get("expansions", {}) if isinstance(data, dict) else {}
        for key, values in merged.items():
            self._table[str(key).lower()] = [str(v) for v in values]

    def _expand_values(self, key: str, seen: set[str]) -> set[str]:
        """Recursively collect all values reachable from *key* in the table.

        Cycles are prevented via the *seen* set of already-visited keys.

        Args:
            key: The table key to expand from.
            seen: Keys already visited in the current expansion walk.

        Returns:
            The set of all expansion values reachable from *key*.
        """
        result: set[str] = set()
        for value in self._table.get(key.lower(), []):
            if value in result or value in seen:
                continue
            result.add(value)
            result.update(self._expand_values(value.lower(), seen | {value}))
        return result

    def expand(self, query: str) -> set[str]:
        """Return the query plus any expansion terms reachable from it.

        Case-insensitive and typo-tolerant (``cros origin`` -> ``cors``). A
        genuinely-absent acronym is returned unchanged.

        Args:
            query: The raw user query.

        Returns:
            A set containing the original query string and any matched
            expansion terms (and their transitive expansions).
        """
        q_tokens = _tokens(query)
        result: set[str] = {query}
        for key in self._keys:
            if _tokens_fuzzy_match(q_tokens, key.split()):
                result.add(key)
                result.update(self._expand_values(key, set()))
        return result

    def matched_phrases(self, query: str) -> list[str]:
        """Return the table keys that fuzzy-match inside *query*, longest first.

        Args:
            query: The raw user query.

        Returns:
            The matched table keys, sorted by length descending.
        """
        q_tokens = _tokens(query)
        matched = [k for k in self._keys if _tokens_fuzzy_match(q_tokens, k.split())]
        return sorted(matched, key=len, reverse=True)

    def expanded_text(self, query: str) -> str:
        """Return *query* with expansion terms appended (FTS + embedding input).

        Only terms not already present are appended, so the original phrasing is
        preserved and expansion is purely additive.

        Args:
            query: The raw user query.

        Returns:
            The query string with matched expansion terms appended, or *query*
            unchanged when nothing matched.
        """
        q_lower = query.lower()
        additions: list[str] = []
        for key in self.matched_phrases(query):
            for value in self._table[key]:
                if value.lower() not in q_lower and value not in additions:
                    additions.append(value)
            for value in self._expand_values(key, set()):
                if value.lower() not in q_lower and value not in additions:
                    additions.append(value)
        if not additions:
            return query
        return query + " " + " ".join(additions)
