"""Result reranking — boosts definitions, penalises test files, applies session weights.

Scoring pipeline executed after the initial BM25 + vector hybrid retrieval.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from code_search.engine.classification import FileRole, PathClass
from code_search.engine.config import Settings
from code_search.engine.graph import GraphDatabase, IndexMetadataStore
from code_search.engine.paths import repo_relative_path
from code_search.engine.session import SessionDatabase

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


def _fqn_leaf(fqn: str) -> str:
    """Return the lowercased declaration leaf of *fqn* without parameters."""
    leaf = fqn.split("(", 1)[0]
    if "::" in leaf:
        leaf = leaf.rsplit("::", 1)[-1]
    leaf = leaf.rsplit(".", 1)[-1]
    return leaf.lower()


def _identifier_target(query: str | None) -> str | None:
    """Return the concrete identifier/config key a query names, if any.

    Recognises camelCase/snake_case identifiers (via the shared
    ``query_symbol_identifier`` rule) and dotted/``::`` config keys such as
    ``spring.datasource.url``. A natural-language phrase returns ``None``.
    """
    if not query:
        return None
    from code_search.engine.search import query_symbol_identifier

    identifier = query_symbol_identifier(query)
    if identifier:
        return identifier
    stripped = query.strip().strip("`'\"")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:[.:][A-Za-z_][A-Za-z0-9_]*)+", stripped):
        return stripped
    return None


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
                :func:`code_search.engine.config.Settings.from_env` when omitted.
        """
        self._db = db
        self._session_db = session_db
        self._settings = settings or Settings.from_env()
        self._root: Path | None = None
        self._root_resolved = False

    def _index_root(self) -> Path | None:
        """Return the indexed repository root, or ``None`` when unknown.

        Resolved once from the index metadata and cached, because every
        path-shape signal below is computed against it.

        Returns:
            The repository root the index was built from, or ``None`` when the
            metadata is missing or unreadable.
        """
        if not self._root_resolved:
            self._root_resolved = True
            try:
                stored = IndexMetadataStore(self._db).get("index_root")
            except Exception:
                stored = None
            if stored:
                self._root = Path(stored)
        return self._root

    def rerank(
        self,
        results: list[dict[str, Any]],
        query_terms: list[str] | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        """Reorder *results* in place by applying all four scoring signals.

        Applies the definition boost (only when the chunk's FQN references a
        queried fragment), the test-file and non-canonical penalties, and the
        per-file session weight. Final scores are lower-bounded at ``0.0``
        but not upper-capped, and each result gains a ``"session_weight"``
        key.

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
        # Every path-shape signal below must see the repo-relative spelling:
        # the stored path and the path-prefixed FQN embed the checkout
        # location, so matching against them makes the score depend on the
        # directory the repository happens to live in.
        root = self._index_root()

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
        from code_search.engine.intent_detection import ContentIntent, classify_content_intent

        docs_intent = classify_content_intent(query) is ContentIntent.DOCS if query else False
        config_intent = classify_content_intent(query) is ContentIntent.CONFIG if query else False
        identifier = _identifier_target(query)
        identifier_lower = identifier.lower() if identifier else None
        if query_fragments:
            concept_terms = set(query_fragments)
        else:
            from code_search.engine.search import decompose_query

            concept_terms = set(decompose_query(query or ""))
        # Concepts whose definition is present in this result pool. Only then
        # does the usage penalty apply, so a usage-only answer is never
        # penalised into nothing when the definition was not retrieved.
        named_concepts: set[str] = set()
        short_phrase = bool(concept_terms) and len(concept_terms) <= 3
        for r in results:
            if not r.get("is_definition", False):
                continue
            leaf = _fqn_leaf(str(r.get("fqn") or ""))
            if not leaf:
                continue
            if (identifier_lower is not None and leaf == identifier_lower) or (
                short_phrase and leaf in concept_terms
            ):
                named_concepts.add(leaf)

        id_boost = self._settings.identifier_definition_boost
        usage_penalty = self._settings.identifier_usage_penalty
        config_key_boost = self._settings.config_key_boost

        for r in results:
            score = r["score"]
            stored_path = str(r.get("file_path") or "")
            rel_path = repo_relative_path(stored_path, root)
            # ``fqn`` embeds the same absolute file path for path-prefixed
            # languages and raw chunks, so relativize its prefix too.
            stored_fqn = str(r.get("fqn") or "")
            rel_fqn = (
                rel_path + stored_fqn[len(stored_path) :]
                if stored_path and stored_fqn.startswith(stored_path)
                else stored_fqn
            )
            is_owner_definition = (
                definition_intent
                and r.get("is_definition", False)
                and query_fragments
                and _fqn_matches(r.get("fqn", ""), query_fragments)
            )
            leaf = _fqn_leaf(str(r.get("fqn") or ""))
            is_named_definition = bool(
                r.get("is_definition", False) and leaf and leaf in named_concepts
            )
            if is_owner_definition:
                score *= owner_boost
            elif is_named_definition:
                score *= id_boost
            elif r.get("is_definition", False) and (
                not query_fragments or _fqn_matches(r.get("fqn", ""), query_fragments)
            ):
                score *= boost
            # Definitions beat usages: once a named concept's definition is in
            # the pool, chunks that merely reference the name are demoted so a
            # usage-heavy file cannot outrank the declaration.
            if named_concepts and not r.get("is_definition", False):
                haystack = f"{rel_fqn} {r.get('content') or ''}".lower()
                if any(concept in haystack for concept in named_concepts):
                    score *= usage_penalty
            # A concrete config key (dotted or snake_case) is answered by the
            # config entry that defines it, so lift config chunks containing it.
            if (
                identifier_lower
                and r.get("content_type") == "config"
                and identifier_lower in (r.get("content") or "").lower()
            ):
                score *= config_key_boost
            # A documentation-shaped query widened to ``all`` still competes
            # with code on lexical score; lift prose so README/guide chunks
            # can answer "how do I run the tests?".
            if docs_intent and r.get("content_type") == "docs":
                from code_search.engine.classification import documentation_tier

                score *= self._settings.docs_content_boost
                tier = documentation_tier(rel_path)
                if tier == "project":
                    score *= self._settings.docs_project_boost
                elif tier == "third_party":
                    score *= self._settings.docs_third_party_penalty
                elif tier == "generated":
                    score *= self._settings.docs_generated_penalty
            if config_intent and r.get("content_type") == "config":
                from code_search.engine.classification import config_tier

                tier = config_tier(rel_path)
                if tier == "primary":
                    score *= self._settings.config_primary_boost
                elif tier in ("test", "sample", "generated"):
                    score *= self._settings.config_nonprimary_penalty
            # Module cohesion: a result inside a module whose path segment
            # exactly matches a query term is preferred over similarly named
            # clones (spring-kafka vs spring-kafka-2) when the query names the
            # module. Small and multiplicative so lexical evidence still wins.
            cohesion_terms = {term for term in query_fragments if len(term) >= 3}
            if cohesion_terms:
                segments = {part.lower() for part in Path(rel_path).parts}
                if cohesion_terms & segments:
                    score *= self._settings.module_cohesion_boost
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
            # Corpus hygiene: minified bundles and vendored web assets are
            # lexical noise, not canonical source. Exhaustive search still sees
            # them; only ranked ordering demotes them.
            # Leading slash restored so root-level ``dist/``/``node_modules/``
            # directories still match the same substring tests as before.
            lowered_path = f"/{rel_path.lstrip('/')}".lower()
            if lowered_path.endswith((".min.js", ".min.css")) or "/dist/" in lowered_path:
                score *= self._settings.minified_penalty
            if any(
                segment in lowered_path
                for segment in ("/node_modules/", "/vendor/", "/bower_components/")
            ):
                score *= self._settings.vendor_penalty
            # Path penalties: multiplicative, strictly positive, so a
            # demoted declaration/barrel file stays reachable.
            path_class = r.get("path_class")
            if path_class == PathClass.DTS:
                score *= dts_penalty
            elif path_class == PathClass.BARREL:
                score *= barrel_penalty
            if r["file_path"] in session_weights:
                score *= session_weights[r["file_path"]]
            # Keep scores non-negative, but do not clamp the upper bound: the
            # fused score legitimately exceeds 1.0 for strong matches, and
            # clamping collapsed every strong candidate to 1.00 (destroying
            # discrimination between them).
            score = max(0.0, score)
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
        from code_search.engine.search import decompose_query

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
