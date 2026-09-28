"""Result reranking — boosts definitions, penalises test files, applies session weights.

Scoring pipeline executed after the initial BM25 + vector hybrid retrieval.
"""

from __future__ import annotations

import logging
from typing import Any

from src.engine.classification import FileRole, PathClass
from src.engine.config import Settings
from src.engine.graph import GraphDatabase
from src.engine.session import SessionDatabase

logger = logging.getLogger(__name__)


def demote_test_file_candidates(
    bm25_results: list[tuple[int, float]],
    vector_results: list[tuple[int, float]],
    test_chunk_ids: set[int],
    penalty: float,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Demote test-file chunks inside the candidate pool (pre-fusion).

    Scales each test-file chunk's rank score by *penalty* in both ranked
    lists so keyword-dense test classes cannot outrank production code on
    density alone before ``rrf_fusion`` combines the arms. Each arm
    keeps its input ordering convention (best-first): the lexical arm's
    scores are negative (more negative = better), the dense arm's scores are
    positive (higher = better). Production chunks pass through untouched.

    Args:
        bm25_results: ``(chunk_rowid, score)`` pairs from the lexical arm.
        vector_results: ``(chunk_rowid, score)`` pairs from the dense arm.
        test_chunk_ids: Row ids of chunks living in test/spec files.
        penalty: Multiplicative demotion (``settings.noise_penalty``).

    Returns:
        The two ranked lists with test-file scores scaled by *penalty*.
    """
    if not test_chunk_ids or penalty >= 1.0:
        return bm25_results, vector_results

    def _demote(results: list[tuple[int, float]], ascending: bool) -> list[tuple[int, float]]:
        scaled = [
            (cid, sc * penalty) if cid in test_chunk_ids else (cid, sc) for cid, sc in results
        ]
        return sorted(scaled, key=lambda pair: pair[1], reverse=not ascending)

    return _demote(bm25_results, ascending=True), _demote(vector_results, ascending=False)


def _fqn_matches(fqn: str, query_fragments: list[str]) -> bool:
    """Return whether *fqn* references any of the queried symbol fragments.

    The queried symbol identifier (e.g. ``is_token_valid``) is compared
    case-insensitively against the chunk's FQN, so a definition chunk for the
    queried symbol matches while unrelated definition chunks do not.
    """
    fqn = fqn.lower()
    return any(fragment in fqn for fragment in query_fragments)


class Reranker:
    """Adjusts raw search scores using four signals:

    1. **Definition boost** — chunks marked as definitions get a score multiplier.
    2. **Test-file penalty** — chunks in test/spec files are down-weighted.
    3. **Non-canonical penalty** — examples/legacy/generated chunks are
       down-weighted (demoted, never excluded).
    4. **Session weight** — recently accessed files receive a decay-based boost.
    """

    def __init__(
        self,
        db: GraphDatabase,
        session_db: SessionDatabase | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Create a reranker wired to the graph and session databases.

        Args:
            db: The graph database used to look up result metadata.
            session_db: Optional session database used to fetch per-file
                session weights; when ``None``, session weighting is skipped.
            settings: Runtime settings; defaults to
                :func:`src.engine.config.Settings.from_env` when omitted.
        """
        self._db = db
        self._session_db = session_db
        self._settings = settings or Settings.from_env()

    def rerank(
        self,
        results: list[dict[str, Any]],
        query_terms: list[str] | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        """Reorder *results* in place by applying all four scoring signals.

        Applies the definition boost (only when the chunk's FQN references a
        queried fragment), the test-file and non-canonical penalties, and the
        per-file session weight. Final scores are clamped to ``[0.0, 1.0]``
        and each result gains a ``"session_weight"`` key.

        When *query* is supplied, the definition-owner boost raises the owner
        symbol's definition chunk under definition-intent queries and the
        model-file penalty demotes model/DTO/assembler/exception plumbing
        files under behavior-intent queries.

        Args:
            results: Raw search results, each a dict containing at least
                ``"file_path"``, ``"score"``, and the optional flags
                ``"is_definition"``, ``"fqn"``, ``"is_test_file"``, and
                ``"is_non_canonical"``. Mutated in place.
            query_terms: Tokenized query terms used to match definition FQNs;
                when ``None`` or empty, definitions are boosted without an FQN
                guard.
            query: The raw user query; when provided, intent-based boosts are
                applied.

        Returns:
            The same list, sorted by adjusted score in descending order.
        """
        if not results:
            return results

        file_paths = [r["file_path"] for r in results]
        session_weights = self._get_session_weights(file_paths)

        boost = self._settings.definition_boost
        penalty = self._settings.noise_penalty
        non_canonical_penalty = self._settings.non_canonical_penalty
        dts_penalty = self._settings.dts_penalty
        barrel_penalty = self._settings.barrel_penalty
        owner_boost = self._settings.definition_owner_boost
        model_penalty = self._settings.model_file_penalty

        query_fragments = [t.lower() for t in (query_terms or [])]
        definition_intent, behavior_intent, scaffold_topic, authorization_intent = (
            self._query_intents(query)
        )

        for r in results:
            score = r["score"]
            is_owner_definition = (
                definition_intent
                and r.get("is_definition", False)
                and query_fragments
                and _fqn_matches(r.get("fqn", ""), query_fragments)
            )
            if is_owner_definition:
                score *= owner_boost
            elif r.get("is_definition", False) and (
                not query_fragments or _fqn_matches(r.get("fqn", ""), query_fragments)
            ):
                score *= boost
            # Authorization intent — a question about who
            # may access/restrict behavior boosts the definition/annotation
            # chunks of authorization-relevant code (security checks,
            # ``@PreAuthorize``/``@Secured`` guards, access-control config).
            # The ``declared_rules`` shape marks annotation-guarded chunks.
            if (
                authorization_intent
                and (r.get("is_definition", False) or r.get("declared_rules"))
                and query_fragments
                and _fqn_matches(r.get("fqn", ""), query_fragments)
            ):
                score *= owner_boost
            # Explicit annotation/DTO boost for authorization paraphrases.
            # When a query is about access control/validation, raise chunks
            # carrying @interface, @Secured, or @Valid annotations above
            # generic boilerplate that only matches lexically.
            if authorization_intent and r.get("is_definition", False):
                has_annotation = any(
                    kw in (r.get("fqn", "") or "").lower()
                    for kw in {"@preauthorize", "@secured", "@valid", "authenticate"}
                )
                if has_annotation:
                    score *= 1.3  # annotation boost for authorization queries
            if r.get("is_test_file", False):
                score *= penalty
            if r.get("is_non_canonical", False):
                score *= non_canonical_penalty
            # Lexical-echo demotion. Reference-only chunks inside
            # model/DTO/assembler/exception plumbing match query words without
            # carrying the answer, so demote them for behavior-intent
            # paraphrase queries and for any lexical-echo-only match. A query
            # that names the generic construct itself (scaffold_topic) lifts
            # the demotion so on-topic scaffolding still ranks.
            # Demotion is multiplicative and strictly positive — never a hard
            # drop.
            if r.get("file_role") in (
                FileRole.MODEL,
                FileRole.DTO,
                FileRole.ASSEMBLER,
                FileRole.EXCEPTION,
            ):
                lexical_echo_only = not r.get("is_definition", False)
                if not scaffold_topic and (behavior_intent or lexical_echo_only):
                    score *= model_penalty
            # Infra file penalties: relative re-ranking for tooling/build files
            # INFRA files (root-level *.sh, package-lock.json, pom.xml,
            # maven-wrapper.properties, docker-compose.yml) are deprioritized
            # for code queries but remain reachable with strong literal
            # evidence (e.g. jdbc:mysql). The deboost is multiplicative and
            # strictly positive so files with strong content can still rank.
            # A definition-owner chunk is the reconciled answer to a
            # definition-intent query, so it keeps its boost instead of being
            # demoted below a same-scored code reference.
            if r.get("file_role") == FileRole.INFRA and not is_owner_definition:
                score *= self._settings.resource_deboost
            # Path penalties: multiplicative, strictly positive, so a
            # demoted declaration/barrel file stays reachable.
            path_class = r.get("path_class")
            if path_class == PathClass.DTS:
                score *= dts_penalty
            elif path_class == PathClass.BARREL:
                score *= barrel_penalty
            if r["file_path"] in session_weights:
                score *= session_weights[r["file_path"]]
            score = max(0.0, min(1.0, score))
            r["score"] = score
            r["session_weight"] = session_weights.get(r["file_path"], 1.0)
            # Preserve the score_sources breakdown: mark the
            # pass as applied without dropping the persisted components.
            if "score_sources" in r and isinstance(r["score_sources"], dict):
                r["score_sources"]["reranked"] = True

        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    def _query_intents(self, query: str | None) -> tuple[bool, bool, bool, bool]:
        """Return ``(definition_intent, behavior_intent, scaffold_topic,
        authorization_intent)``.

        Intent is detected from the query's decomposed sub-words against the
        configured intent vocabularies. ``scaffold_topic`` is true when the
        query names a generic scaffold construct (``exception``, ``dto``,
        ``model``, ...), which lifts the scaffolding demotion so on-topic
        scaffolding still ranks; ``authorization_intent`` is true when the
        query asks about access control/authorization — no *query*
        means no intent is active.
        """
        if not query:
            return False, False, False, False
        from src.engine.search import decompose_query

        tokens = set(decompose_query(query))
        return (
            bool(tokens & set(self._settings.definition_intent_words)),
            bool(tokens & set(self._settings.behavior_intent_words)),
            bool(tokens & set(self._settings.scaffold_topic_words)),
            bool(tokens & set(self._settings.authorization_intent_words)),
        )

    def _get_session_weights(self, file_paths: list[str]) -> dict[str, float]:
        """Look up the session weight for each of the given file paths.

        Returns an empty mapping when no session database is configured or the
        lookup fails, in which case session weighting is effectively disabled.

        Args:
            file_paths: The stored file paths of the current results.

        Returns:
            A mapping of file path to weight score; missing paths are absent.
        """
        if self._session_db is None:
            return {}
        try:
            rows = self._session_db.get_weights_for_files(file_paths)
            weights: dict[str, float] = {}
            for row in rows:
                weights[row["file_path"]] = float(row["weight_score"])
            return weights
        except Exception as exc:
            logger.debug("Session weight lookup failed: %s", exc)
            return {}
