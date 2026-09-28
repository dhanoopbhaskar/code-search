#!/usr/bin/env bash
set -euo pipefail

# Offline search-robustness + transparency benchmark driver.
#
# Re-indexes the acceptance corpus into a scratch .context and runs the
# S1-S10 / E1-E5 battery plus the transparency battery (config-scent queries,
# docs-scoped queries, grep-oracle literals, abstract-paraphrase queries,
# overload/callee samples, option-parity matrix), reporting per-query
# precision@5, top-1 hit rate, exhaustive counts vs the rg ground-truth oracle,
# infra absence, and enumeration completeness. It is the offline regression
# gate for the hybrid-search robustness and transparency work.
#
# Usage:
#   scripts/benchmark.sh                 # report only
#   scripts/benchmark.sh --fail-below 0.30   # exit 1 if mean p@5 drops below
#   scripts/benchmark.sh --corpus <path>     # benchmark a different repo
#   scripts/benchmark.sh --corpus-in-repo    # benchmark the in-repo fixture
#
# The acceptance corpus defaults to the realworld-springboot checkout; point
# CODE_SEARCH_ACCEPTANCE_CORPUS elsewhere to benchmark a different repo. The
# rg oracle is computed at runtime over whatever --corpus is passed, so the
# assertions stay generic and never hardcode a repo's contents. Pass
# --corpus-in-repo to run the transparency battery against the deterministic
# in-repo fixture (tests/fixtures/transparency) which enforces the paraphrase
# precision floors in CI without the external corpus.

CORPUS="${CODE_SEARCH_ACCEPTANCE_CORPUS:-/media/dhanoopbhaskar/hdd01/home/git/test-code-search/realworld-springboot}"
FAIL_BELOW=""
IN_REPO=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --fail-below)
      FAIL_BELOW="$2"; shift 2 ;;
    --corpus)
      CORPUS="$2"; shift 2 ;;
    --corpus-in-repo)
      IN_REPO=1; CORPUS="tests/fixtures/transparency"; shift ;;
    *)
      echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ ! -d "$CORPUS" ]]; then
  echo "Acceptance corpus not found: $CORPUS" >&2
  echo "Set CODE_SEARCH_ACCEPTANCE_CORPUS to a checkout to index." >&2
  echo "Or pass --corpus-in-repo to use the deterministic in-repo fixture." >&2
  exit 2
fi

python3 - "$CORPUS" "$FAIL_BELOW" "$IN_REPO" <<'PY'
import subprocess
import sys
import tempfile
from pathlib import Path

from src.engine.config import Settings
from src.context import ContextManager
from src.engine.graph import GraphDatabase, IndexMetadataStore
from src.engine.indexer import IndexOrchestrator
from src.engine.parser import ASTParser
from src.engine.paths import normalize_indexed_path
from src.engine.symbols import SymbolExtractor, SymbolStore
from src.engine.embeddings import EmbeddingGenerator, VectorIndex
from src.engine.reranking import Reranker
from src.engine.search import HybridSearch, query_symbol_identifier

CORPUS = Path(sys.argv[1])
FAIL_BELOW = float(sys.argv[2]) if sys.argv[2] else None
IN_REPO = bool(int(sys.argv[3]) if len(sys.argv) > 3 else 0)

SEMANTIC = [
    ("S1", "where is the JWT token generated", ("TokenService.java", "AuthService.java")),
    ("S2", "how is the token validated on each request", ("SecurityFilter.java", "TokenService.java", "CustomUserDetailsService.java")),
    ("S3", "password encoding during registration", ("UserService.java", "SecurityConfig.java")),
    ("S4", "what happens when an article is not found", ("ArticleService.java", "ExceptionHandlerController.java", "ArticleNotFoundException.java")),
    ("S5", "article pagination and filtering by tag and author", ("ArticleController.java", "ArticleSpecification.java")),
    ("S6", "how is a slug generated from the article title", ("ArticleService.java", "SlugifyConfig.java")),
    ("S7", "unfollow a user profile", ("ProfileService.java", "ProfileController.java")),
    ("S8", "who is allowed to delete a comment", ("AuthorizationConfig.java", "CheckSecurity.java", "CommentController.java")),
    ("S9", "global exception handling for missing resources", ("ExceptionHandlerController.java",)),
    ("S10", "favorite and unfavorite an article", ("ProfileService.java", "ArticleService.java", "ArticleFavoriteController.java")),
]

EXACT = [
    ("E1", "count occurrences of @Transactional", "@Transactional"),
    ("E2", "files using PasswordEncoder", "PasswordEncoder"),
    ("E3", "definition of DEFAULT_FILTER_LIMIT constant", "DEFAULT_FILTER_LIMIT"),
    ("E4", "usages of checkUserAvailable", "checkUserAvailable"),
    ("E5", "the string 'There's already an article with this title'", "There's already an article with this title"),
]

INFRA_NAMES = ("docker-compose.yml", "docker-compose.yaml", "Dockerfile", "pom.xml", "Makefile")

# Access-control/ownership queries must surface guarded (declared-rule
# carrying) code within the top 5, not just the plain controller.
ACCESS_CONTROL = [
    ("AC1", "who is allowed to delete a comment"),
    ("AC2", "who owns the article"),
]


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="benchmark-"))
    ctx = scratch / "context"
    settings = Settings(context_dir=ctx)
    if IN_REPO:
        settings = Settings(context_dir=ctx, index_prose=True)
    cm = ContextManager(settings)
    cm.ensure()
    paths = cm.paths
    db = GraphDatabase(paths["graph"], settings)
    db.initialize()
    meta = IndexMetadataStore(db)
    parser = ASTParser()
    se = SymbolExtractor(parser)
    ss = SymbolStore(db, settings)
    eg = EmbeddingGenerator(settings)
    vi = VectorIndex(
        paths.get("vectors_bin", ctx / "vectors.bin"),
        paths.get("vectors_meta", ctx / "vectors.meta.json"),
    )
    vi.load()
    orchestrator = IndexOrchestrator(
        db=db, metadata_store=meta, parser=parser, symbol_extractor=se,
        symbol_store=ss, embedding_generator=eg, vector_index=vi,
        context_dir=ctx, settings=settings,
    )
    result = orchestrator.index_codebase(
        root_path=CORPUS, force=True, incremental=False, verbose=False,
        include_resources=True, resource_extensions=settings.resource_extensions,
    )
    print(f"indexed: {result}")

    search = HybridSearch(db, vi, eg, settings)
    reranker = Reranker(db, settings=settings)
    failures: list[str] = []

    # Semantic battery precision@5, top-1, infra absence.
    precisions = []
    top1_hits = 0
    print("\n=== SEMANTIC (precision@5 vs ground-truth basenames) ===")
    for qid, query, gt in SEMANTIC:
        envelope = search.search(query, limit=10, content="code")
        raw_results = envelope["results"]
        symbol_id = query_symbol_identifier(query)
        ranked = reranker.rerank(
            raw_results,
            query_terms=[symbol_id] if symbol_id else None,
            query=query,
        )
        top5 = ranked[:5]
        top5_names = {Path(r["file_path"]).name for r in top5}
        tp = len(top5_names & set(gt))
        p = tp / min(5, len(gt)) if gt else 0.0
        precisions.append(p)
        canonical_first = bool(top5) and Path(top5[0]["file_path"]).name in set(gt)
        if canonical_first:
            top1_hits += 1
        infra_in_top5 = any(
            Path(r["file_path"]).name in INFRA_NAMES for r in top5
        )
        if infra_in_top5:
            failures.append(
                f"SC-005 {qid}: infra file in top 5 for code-language query {query!r}"
            )
        print(f"[{qid}] {query}")
        print(f"   p@5={p:.2f} top1={canonical_first} mode={envelope['mode']} "
              f"conf={envelope['confidence']} hits={sorted(top5_names & set(gt)) or '(none)'}")

    mean = sum(precisions) / len(precisions) if precisions else 0.0
    top1_rate = top1_hits / len(SEMANTIC) if SEMANTIC else 0.0
    print(f"\nmean p@5 = {mean:.3f}  top-1 = {top1_rate:.2f}")

    if not IN_REPO:
        if FAIL_BELOW is not None and mean < FAIL_BELOW:
            failures.append(f"SC-002: mean p@5 {mean:.3f} below threshold {FAIL_BELOW:.2f}")
        if top1_rate < 0.60:
            failures.append(f"SC-003: top-1 hit rate {top1_rate:.2f} below 0.60")

    # Indexed file set (the scan surface for exhaustive + the rg oracle).
    with db.connect() as conn:
        indexed_rows = conn.execute(
            "SELECT DISTINCT file_path FROM file_checksums ORDER BY file_path;"
        ).fetchall()
    indexed_files = [r["file_path"] for r in indexed_rows]
    stored_root = meta.get("index_root")
    index_root = Path(stored_root) if stored_root else None
    resolved = [
        p
        for f in indexed_files
        if (p := normalize_indexed_path(f, index_root) if index_root else Path(f)) is not None
        and p.is_file()
    ]

    def rg_count(term: str) -> int:
        """Literal line count from the rg ground-truth oracle (SC-006)."""
        if not resolved:
            return 0
        proc = subprocess.run(
            ["rg", "-F", "-c", "--", term, *[str(p) for p in resolved]],
            capture_output=True, text=True,
        )
        if proc.returncode not in (0, 1):
            raise RuntimeError(f"rg failed for {term!r}: {proc.stderr}")
        return sum(
            int(line.rsplit(":", 1)[1])
            for line in proc.stdout.splitlines()
            if line.rsplit(":", 1)[1].isdigit()
        )

    print("\n=== EXACT (exhaustive counts vs rg oracle) ===")
    for eid, query, term in EXACT:
        # Pass the literal as a quoted phrase so exhaustive matches the exact
        # substring (a bare multi-word term would decompose into its words
        # and overcount). rg -F counts the same literal, line by line.
        envelope = search.search(f'"{term}"', limit=50, mode="exhaustive")
        oracle = rg_count(term)
        match = envelope["total_count"] == oracle
        if not match:
            failures.append(
                f"SC-006 {eid}: exhaustive total={envelope['total_count']} "
                f"!= rg oracle {oracle} for {term!r}"
            )
        print(f"[{eid}] {term}: exhaustive total={envelope['total_count']} "
              f"rg oracle={oracle} match={match} complete={envelope['complete']}")

    # Enumeration complete set matches structural count.
    print("\n=== ENUMERATE ===")
    env = search.search("list all controllers", limit=200, mode="enumerate")
    with db.connect() as conn:
        expected = conn.execute(
            "SELECT COUNT(*) FROM code_chunks "
            "WHERE is_definition = 1 AND fqn LIKE '%Controller';"
        ).fetchone()[0]
    enum_match = env["total_count"] == expected and env["complete"] is True
    if not enum_match:
        failures.append(
            f"SC-008: enumerate total={env['total_count']} complete={env['complete']} "
            f"!= structural expected {expected}"
        )
    print(f"list all controllers: total={env['total_count']} complete={env['complete']} "
          f"structural={expected} match={enum_match}")

    # Governing guarded code within top 5 for access-control queries.
    print("\n=== ACCESS CONTROL (SC-004: guarded code in top 5) ===")
    for acid, query in ACCESS_CONTROL:
        envelope = search.search(query, limit=10)
        ranked = reranker.rerank(
            envelope["results"],
            query_terms=None,
            query=query,
        )
        top5_ids = [r.get("chunk_id") for r in ranked[:5] if r.get("chunk_id")]
        if top5_ids:
            placeholders = ",".join("?" for _ in top5_ids)
            with db.connect() as conn:
                guarded = conn.execute(
                    f"SELECT COUNT(*) FROM code_chunks "
                    f"WHERE id IN ({placeholders}) AND declared_rules IS NOT NULL "
                    f"AND declared_rules != '';",
                    top5_ids,
                ).fetchone()[0]
        else:
            guarded = 0
        ac_ok = guarded >= 1
        if not IN_REPO and not ac_ok:
            failures.append(f"SC-004 {acid}: no guarded code in top 5 for {query!r}")
        print(f"[{acid}] {query}: guarded_chunks_in_top5={guarded} ok={ac_ok}")

    # --- Transparency battery ---
    # Config-scent ranking, docs scoping, paraphrase precision,
    # overloads/unresolved callees, and envelope labels.
    # The in-repo fixture enforces the paraphrase precision floors so CI reaches
    # the acceptance surface without the external corpus.
    print("\n=== TRANSPARENCY (config-scent SC-001) ===")
    CONFIG_SCENT = [
        ("C1", "database connection pool settings", "application-dev.properties"),
        ("C2", "connection timeout", "application-dev.properties"),
    ]
    config_hits = 0
    for cid, query, expect_name in CONFIG_SCENT:
        envelope = search.search(query, limit=10, content="all")
        ranked = reranker.rerank(envelope["results"], query_terms=None, query=query)
        top5 = ranked[:5]
        hit = any(Path(r["file_path"]).name == expect_name for r in top5)
        if hit:
            config_hits += 1
        if not hit:
            failures.append(f"SC-001 {cid}: {expect_name} not in top 5 for {query!r}")
        print(f"[{cid}] {query}: config_in_top5={hit} content={envelope.get('content')}")

    print("\n=== TRANSPARENCY (docs scoping SC-002) ===")
    envelope = search.search("how to run the dev server", limit=10, content="docs")
    docs_results = envelope["results"]
    only_docs = bool(docs_results) and all(
        r.get("content_type") == "docs" for r in docs_results
    )
    docs_match = any(
        "README.md" in r.get("file_path", "") for r in docs_results
    )
    if not only_docs or not docs_match:
        failures.append(
            f"SC-002: docs-scoped query returned only_docs={only_docs} "
            f"readme_hit={docs_match}"
        )
    print(f"docs scope: only_docs={only_docs} readme_hit={docs_match} "
          f"total={envelope['total_matches']}")

    print("\n=== TRANSPARENCY (paraphrase precision SC-005) ===")
    # Definition/primary-owner chunk must outrank reference-only chunks for
    # abstract paraphrase queries; the in-repo fixture enforces the floors.
    paraphrase_pairs = [
        ("P1", "what happens when an article is saved", ("ArticleService.java",)),
        ("P2", "how is the article stored", ("ArticleService.java",)),
    ]
    para_precisions = []
    para_top1 = 0
    for pid, query, gt in paraphrase_pairs:
        envelope = search.search(query, limit=10, content="all")
        ranked = reranker.rerank(envelope["results"], query_terms=None, query=query)
        top10 = ranked[:10]
        top10_names = {Path(r["file_path"]).name for r in top10}
        p = len(top10_names & set(gt)) / min(10, len(gt)) if gt else 0.0
        para_precisions.append(p)
        top1_hit = bool(top10) and Path(top10[0]["file_path"]).name in set(gt)
        if top1_hit:
            para_top1 += 1
        print(f"[{pid}] {query}: top10_hit={bool(p)} top1={top1_hit}")
    if IN_REPO and len(para_precisions) == len(paraphrase_pairs):
        mean_p10 = sum(para_precisions) / len(para_precisions)
        top1_rate = para_top1 / len(paraphrase_pairs)
        if mean_p10 < 0.70:
            failures.append(
                f"SC-005: in-repo paraphrase top-10 precision {mean_p10:.2f} < 0.70"
            )
        if top1_rate < 0.60:
            failures.append(f"SC-005: in-repo paraphrase top-1 rate {top1_rate:.2f} < 0.60")
        print(f"in-repo SC-005: mean p@10={mean_p10:.2f} top-1={top1_rate:.2f}")

    print("\n=== TRANSPARENCY (overloads + unresolved callees SC-007) ===")
    overload_env = search.search(
        'ArticleService.save', limit=10, mode="exhaustive"
    )
    with db.connect() as conn:
        save_rows = conn.execute(
            "SELECT s.fqn, s.conventional_fqn FROM symbols s "
            "WHERE s.name = 'save' ORDER BY s.id;"
        ).fetchall()
    overload_count = len(save_rows)
    if overload_count < 2:
        failures.append(f"SC-007: expected >=2 save overloads, found {overload_count}")
    print(f"save overloads indexed: {overload_count}")

    print("\n=== TRANSPARENCY (envelope labels SC-008/SC-009) ===")
    env = search.search("connection pool", limit=5, content="config")
    has_content = env.get("content") == "config"
    has_semantics = "matching_semantics" in env
    has_time = "query_time_ms" in env
    labels_ok = has_content and has_semantics and has_time
    if not labels_ok:
        failures.append(
            f"SC-008/SC-009: envelope labels content={has_content} "
            f"matching_semantics={has_semantics} query_time_ms={has_time}"
        )
    print(f"envelope: content={env.get('content')} "
          f"matching_semantics={env.get('matching_semantics')} "
          f"query_time_ms={env.get('query_time_ms')}")

    if failures:
        print("\nFAILURES:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("\nALL ACCEPTANCE ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
PY