"""Ground truth for the external-corpus tool-utility evaluation.

The cases are the eleven tasks measured in the code-search utility report,
reproduced from the report's benchmark script. Each case names the expected
canonical file(s), the content scope, and the retrieval kind so the harness can
score hit@k for both exact-symbol and natural-language queries.

The set is deliberately external: it requires a local checkout of the
``baeldung-tutorials`` corpus (or any repository supplied through ``--repo``).
No CI job indexes that corpus; the harness skips cleanly when it is absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Retrieval kinds. ``exact`` cases must find a canonical symbol file,
#: ``negative`` cases must abstain, the rest are positive ranking tasks.
RETRIEVAL_KINDS = ("exact", "nl", "struct", "config", "docs", "negative")


@dataclass(frozen=True)
class UtilityCase:
    """One labelled utility task.

    Attributes:
        id: Stable identifier used in the JSONL output.
        kind: One of :data:`RETRIEVAL_KINDS`.
        query: Query text submitted to the engine.
        expected_files: Path fragments that count as a hit (any one matches).
        content_scope: Optional ``--content`` value.
        grep_hint: The literal or regex the report used to validate the answer.
        expect_abstain: Whether the correct response is ``no_match``.
    """

    id: str
    kind: str
    query: str
    expected_files: tuple[str, ...] = ()
    content_scope: str | None = None
    grep_hint: str = ""
    expect_abstain: bool = False


#: The eleven report tasks, ordered as in the report's benchmark script.
GROUND_TRUTH_CASES: tuple[UtilityCase, ...] = (
    UtilityCase(
        id="exact-1",
        kind="exact",
        query="ExponentialBackoffRetryFactory",
        expected_files=(
            "spring-cloud-modules/spring-cloud-ribbon-retry/ribbon-client-service/"
            "src/main/java/com/baeldung/spring/cloud/ribbon/retry/backoff/"
            "ExponentialBackoffRetryFactory.java",
        ),
        grep_hint="ExponentialBackoffRetryFactory",
    ),
    UtilityCase(
        id="exact-2",
        kind="exact",
        query="DigestAlgorithms",
        expected_files=(
            "core-java-modules/core-java-security/src/main/java/com/baeldung/"
            "hashing/DigestAlgorithms.java",
            "core-java-modules/core-java-security-2/src/main/java/com/baeldung/"
            "hashing/DigestAlgorithms.java",
        ),
        grep_hint="DigestAlgorithms",
    ),
    UtilityCase(
        id="exact-3",
        kind="exact",
        query="ThreeWayQuickSort",
        expected_files=(
            "algorithms-modules/algorithms-sorting/src/main/java/com/baeldung/"
            "algorithms/quicksort/ThreeWayQuickSort.java",
        ),
        grep_hint="ThreeWayQuickSort",
    ),
    UtilityCase(
        id="nl-1",
        kind="nl",
        query="scan an array and return the index of the first value that repeats",
        expected_files=(
            "algorithms-modules/algorithms-miscellaneous-10/src/main/java/com/baeldung/"
            "algorithms/firstduplicate/FirstDuplicate.java",
        ),
        grep_hint="duplicate",
    ),
    UtilityCase(
        id="nl-2",
        kind="nl",
        query="combine multiple maps into a single map keeping the last value for duplicate keys",
        expected_files=(
            "core-java-modules/core-java-streams-maps/src/main/java/com/baeldung/"
            "streams/mapstreamtomap/MergeMaps.java",
        ),
        grep_hint="mergeMaps",
    ),
    UtilityCase(
        id="nl-3",
        kind="nl",
        query="compare the contents of two files using memory mapped buffers",
        expected_files=(
            "core-java-modules/core-java-12/src/main/java/com/baeldung/file/content/"
            "comparison/CompareFileContents.java",
        ),
        grep_hint="MappedByteBuffer|filesCompareBy",
    ),
    UtilityCase(
        id="nl-4",
        kind="nl",
        query="create and verify a signed JSON web token with an HMAC secret key",
        expected_files=(
            "spring-security-modules/spring-security-core/src/main/java/com/baeldung/"
            "jwtsignkey/jwtconfig/JwtUtils.java",
        ),
        grep_hint="generateJwtToken|Jwts\\.builder",
    ),
    UtilityCase(
        id="struct-1",
        kind="struct",
        query="find methods that are scheduled to run at a fixed rate",
        expected_files=(
            "spring-scheduling/src/main/java/com/baeldung/scheduling/"
            "ScheduledFixedRateExample.java",
        ),
        grep_hint="fixedRate",
    ),
    UtilityCase(
        id="config-1",
        kind="config",
        query="Kafka bootstrap servers configuration",
        expected_files=("spring-kafka/src/main/resources/application.properties",),
        content_scope="config",
        grep_hint="spring\\.kafka\\.bootstrap-servers",
    ),
    UtilityCase(
        id="docs-1",
        kind="docs",
        query="guide for sending and receiving messages with Spring Kafka",
        expected_files=("spring-kafka/README.md",),
        content_scope="docs",
        grep_hint="Kafka",
    ),
    UtilityCase(
        id="negative-1",
        kind="negative",
        query="Haskell implementation of a quantum annealing Kubernetes operator",
        expect_abstain=True,
        grep_hint="quantum annealing",
    ),
)


#: Adversarial abstention set beyond the report's single negative case.
ADVERSARIAL_NEGATIVE_CASES: tuple[UtilityCase, ...] = (
    UtilityCase(
        id="ood-fully",
        kind="negative",
        query="haskell quantum annealing",
        expect_abstain=True,
    ),
    UtilityCase(
        id="ood-partial",
        kind="negative",
        query="haskell quantum annealing kubernetes operator",
        expect_abstain=True,
    ),
    UtilityCase(
        id="ood-padded",
        kind="negative",
        query="kubernetes operator for haskell quantum annealing",
        expect_abstain=True,
    ),
    UtilityCase(
        id="ood-gibberish",
        kind="negative",
        query="zxqv wplorf blorptastic frobnicator",
        expect_abstain=True,
    ),
)


def cases(include_adversarial: bool = True) -> tuple[UtilityCase, ...]:
    """Return the labelled cases, optionally including the adversarial set."""
    if include_adversarial:
        return GROUND_TRUTH_CASES + ADVERSARIAL_NEGATIVE_CASES
    return GROUND_TRUTH_CASES


def positive_cases() -> tuple[UtilityCase, ...]:
    """Return only the eligible positive retrieval tasks."""
    return tuple(case for case in GROUND_TRUTH_CASES if not case.expect_abstain)


def hit_rank(paths: list[str], expected_files: tuple[str, ...]) -> int | None:
    """Return the 1-based rank of the first expected file in *paths*.

    Args:
        paths: Result paths in ranked order.
        expected_files: Path fragments that count as a hit.

    Returns:
        The rank of the first hit, or ``None`` when no result matches.
    """
    for rank, path in enumerate(paths, start=1):
        if any(fragment == path or fragment in path for fragment in expected_files):
            return rank
    return None


@dataclass
class CaseScore:
    """Per-case scoring record written to the JSONL output."""

    case_id: str
    kind: str
    rank: int | None
    hit_at_1: bool
    hit_at_3: bool
    hit_at_5: bool
    hit_at_10: bool
    abstained: bool
    correct: bool
    latency_ms: float
    output_bytes: int
    ranked_path: str | None = None
    model_status: str | None = None
    warmup_state: str | None = None
    scope: str | None = None
    query_time_ms: float | None = None
    mode: str = "cold"
    error: str | None = None
    extra: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        """Return the record as a JSON-serializable mapping."""
        return {
            "case_id": self.case_id,
            "kind": self.kind,
            "rank": self.rank,
            "hit_at_1": self.hit_at_1,
            "hit_at_3": self.hit_at_3,
            "hit_at_5": self.hit_at_5,
            "hit_at_10": self.hit_at_10,
            "abstained": self.abstained,
            "correct": self.correct,
            "latency_ms": self.latency_ms,
            "output_bytes": self.output_bytes,
            "ranked_path": self.ranked_path,
            "model_status": self.model_status,
            "warmup_state": self.warmup_state,
            "scope": self.scope,
            "query_time_ms": self.query_time_ms,
            "mode": self.mode,
            "error": self.error,
            **self.extra,
        }
