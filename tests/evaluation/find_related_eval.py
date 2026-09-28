#!/usr/bin/env python3
"""Evaluation harness for find_related semantic relevance.

Runs 20 queries on the realworld-springboot benchmark (or relevance fixture)
and measures Precision@5, Recall@10, NDCG@10, and latency.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.mcp.server import _find_related_payload
from tests.conftest import FIXTURES_DIR, _indexed_components

# Ground truth for relevance fixture queries
# Each query defines the anchor and the expected relevant results
GROUND_TRUTH = {
    "ArticleService.createComment": {
        "file": "src/main/java/com/example/article/ArticleService.java",
        "line_contains": "createComment",
        "relevant": [
            "ArticleRepository",
            "ArticleController",
            "Article(",
            "Comment(",
            "CommentService",
        ],
        "irrelevant": [
            "SecurityConfig",
        ],
    },
    "ArticleService.getArticle": {
        "file": "src/main/java/com/example/article/ArticleService.java",
        "line_contains": "getArticle",
        "relevant": [
            "ArticleRepository",
            "ArticleController",
            "Article(",
            "ArticleResponse",
        ],
        "irrelevant": [
            "SecurityConfig",
        ],
    },
    "ArticleService.deleteArticle": {
        "file": "src/main/java/com/example/article/ArticleService.java",
        "line_contains": "deleteArticle",
        "relevant": [
            "ArticleRepository",
            "ArticleController",
        ],
        "irrelevant": [
            "SecurityConfig",
        ],
    },
    "ArticleRepository.save": {
        "file": "src/main/java/com/example/article/ArticleRepository.java",
        "line_contains": "save(Comment",
        "relevant": [
            "ArticleService",
            "Comment(",
            "CommentService",
        ],
        "irrelevant": [],
    },
    "ArticleRepository.findById": {
        "file": "src/main/java/com/example/article/ArticleRepository.java",
        "line_contains": "findById",
        "relevant": [
            "ArticleService",
            "ArticleController",
            "Article(",
        ],
        "irrelevant": [],
    },
    "ArticleController.createComment": {
        "file": "src/main/java/com/example/article/ArticleController.java",
        "line_contains": "createComment",
        "relevant": [
            "ArticleService",
            "ArticleRepository",
            "Comment(",
        ],
        "irrelevant": [],
    },
    "ArticleController.getArticle": {
        "file": "src/main/java/com/example/article/ArticleController.java",
        "line_contains": "getArticle",
        "relevant": [
            "ArticleService",
            "ArticleRepository",
            "Article(",
            "ArticleResponse",
        ],
        "irrelevant": [],
    },
    "CommentService.save": {
        "file": "src/main/java/com/example/article/CommentService.java",
        "line_contains": "save(Comment",
        "relevant": [
            "ArticleService",
            "ArticleRepository",
            "Comment(",
        ],
        "irrelevant": [],
    },
    "CommentService.findById": {
        "file": "src/main/java/com/example/article/CommentService.java",
        "line_contains": "findById",
        "relevant": [
            "ArticleService",
            "Comment(",
        ],
        "irrelevant": [],
    },
    "Article.": {
        "file": "src/main/java/com/example/article/Article.java",
        "line_contains": "class Article",
        "relevant": [
            "ArticleService",
            "ArticleRepository",
            "ArticleController",
            "ArticleResponse",
            "Comment(",
        ],
        "irrelevant": [],
    },
    "Comment.": {
        "file": "src/main/java/com/example/article/Comment.java",
        "line_contains": "class Comment",
        "relevant": [
            "ArticleService",
            "ArticleRepository",
            "CommentService",
            "Article(",
        ],
        "irrelevant": [],
    },
    "SecurityConfig.restrictToAuthorizedRoles": {
        "file": "src/main/java/com/example/article/SecurityConfig.java",
        "line_contains": "restrictToAuthorizedRoles",
        "relevant": [],
        "irrelevant": ["ArticleService", "ArticleRepository", "ArticleController"],
    },
    "ArticleRepository.deleteById": {
        "file": "src/main/java/com/example/article/ArticleRepository.java",
        "line_contains": "deleteById",
        "relevant": [
            "ArticleService",
        ],
        "irrelevant": [],
    },
    "ArticleResponse.getId": {
        "file": "src/main/java/com/example/article/dto/ArticleResponse.java",
        "line_contains": "getId",
        "relevant": [
            "ArticleController",
            "Article(",
        ],
        "irrelevant": [],
    },
    "ArticleResponse.setTitle": {
        "file": "src/main/java/com/example/article/dto/ArticleResponse.java",
        "line_contains": "setTitle",
        "relevant": [
            "ArticleController",
            "Article(",
        ],
        "irrelevant": [],
    },
    "Comment.getAuthor": {
        "file": "src/main/java/com/example/article/Comment.java",
        "line_contains": "getAuthor",
        "relevant": [
            "CommentService",
            "ArticleService",
        ],
        "irrelevant": [],
    },
    "Comment.setBody": {
        "file": "src/main/java/com/example/article/Comment.java",
        "line_contains": "setBody",
        "relevant": [
            "CommentService",
            "ArticleService",
        ],
        "irrelevant": [],
    },
    "CommentService.": {
        "file": "src/main/java/com/example/article/CommentService.java",
        "line_contains": "class CommentService",
        "relevant": [
            "ArticleService",
            "ArticleRepository",
            "Comment(",
        ],
        "irrelevant": [],
    },
    "ArticleController.": {
        "file": "src/main/java/com/example/article/ArticleController.java",
        "line_contains": "class ArticleController",
        "relevant": [
            "ArticleService",
            "ArticleRepository",
            "Article(",
            "Comment(",
        ],
        "irrelevant": [],
    },
    "ArticleRepository.": {
        "file": "src/main/java/com/example/article/ArticleRepository.java",
        "line_contains": "class ArticleRepository",
        "relevant": [
            "ArticleService",
            "ArticleController",
            "Article(",
            "Comment(",
        ],
        "irrelevant": [],
    },
}


def _find_line_number(file_path: Path, target: str) -> int:
    """Find the line number containing target string in file."""
    content = file_path.read_text()
    for i, line in enumerate(content.splitlines(), 1):
        if target in line:
            return i
    raise ValueError(f"Line with '{target}' not found in {file_path}")


def _is_relevant(fqn: str, relevant_patterns: list[str], irrelevant_patterns: list[str]) -> bool:
    """Check if a result FQN matches relevant patterns and not irrelevant patterns."""
    # Check irrelevant first
    for pattern in irrelevant_patterns:
        if pattern in fqn:
            return False
    # Check relevant
    return any(pattern in fqn for pattern in relevant_patterns)


def _compute_precision_at_k(
    results: list[dict], k: int, relevant_patterns: list[str], irrelevant_patterns: list[str]
) -> float:
    """Compute Precision@k."""
    if k == 0:
        return 0.0
    relevant_count = sum(
        1 for r in results[:k] if _is_relevant(r["fqn"], relevant_patterns, irrelevant_patterns)
    )
    return relevant_count / k


def _compute_recall_at_k(
    results: list[dict],
    k: int,
    relevant_patterns: list[str],
    irrelevant_patterns: list[str],
    total_relevant: int,
) -> float:
    """Compute Recall@k."""
    if total_relevant == 0:
        return 1.0  # No relevant items to find
    # Count unique relevant items found
    found_relevant = set()
    for r in results[:k]:
        for pattern in relevant_patterns:
            if pattern in r["fqn"]:
                found_relevant.add(pattern)
    return len(found_relevant) / total_relevant


def _compute_ndcg_at_k(
    results: list[dict], k: int, relevant_patterns: list[str], irrelevant_patterns: list[str]
) -> float:
    """Compute NDCG@k."""
    if k == 0:
        return 0.0

    # Compute DCG
    dcg = 0.0
    for i, r in enumerate(results[:k]):
        rel = 1.0 if _is_relevant(r["fqn"], relevant_patterns, irrelevant_patterns) else 0.0
        if i == 0:
            dcg += rel
        else:
            dcg += rel / (i + 1)

    # Compute IDCG (ideal DCG) - all relevant items at top
    ideal_rels = [1.0] * min(k, len(relevant_patterns)) + [0.0] * max(0, k - len(relevant_patterns))
    idcg = 0.0
    for i, rel in enumerate(ideal_rels):
        if i == 0:
            idcg += rel
        else:
            idcg += rel / (i + 1)

    return dcg / idcg if idcg > 0 else 0.0


def run_evaluation(
    repo_path: Path,
    context_dir: Path,
    queries: dict | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Run evaluation on the given repository."""
    comps = _indexed_components(repo_path, context_dir)

    if queries is None:
        queries = GROUND_TRUTH

    results = {}
    latencies = []

    for query_name, query_config in queries.items():
        anchor_file = repo_path / query_config["file"]
        if not anchor_file.exists():
            print(f"Warning: Anchor file not found: {anchor_file}")
            continue

        line_num = _find_line_number(anchor_file, query_config["line_contains"])

        # Run query multiple times for latency measurement
        query_latencies = []
        for _ in range(3):
            start = time.monotonic()
            data = json.loads(_find_related_payload(comps, str(anchor_file), line_num, limit))
            query_latencies.append(time.monotonic() - start)

        avg_latency = sum(query_latencies) / len(query_latencies)
        latencies.extend(query_latencies)

        result_data = data["results"]

        relevant_patterns = query_config["relevant"]
        irrelevant_patterns = query_config.get("irrelevant", [])

        p5 = _compute_precision_at_k(result_data, 5, relevant_patterns, irrelevant_patterns)
        p10 = _compute_precision_at_k(result_data, 10, relevant_patterns, irrelevant_patterns)
        r10 = _compute_recall_at_k(
            result_data, 10, relevant_patterns, irrelevant_patterns, len(relevant_patterns)
        )
        ndcg10 = _compute_ndcg_at_k(result_data, 10, relevant_patterns, irrelevant_patterns)

        results[query_name] = {
            "p5": p5,
            "p10": p10,
            "r10": r10,
            "ndcg10": ndcg10,
            "latency_ms": avg_latency * 1000,
            "result_count": len(result_data),
        }

    # Compute averages
    if results:
        avg_p5 = sum(r["p5"] for r in results.values()) / len(results)
        avg_p10 = sum(r["p10"] for r in results.values()) / len(results)
        avg_r10 = sum(r["r10"] for r in results.values()) / len(results)
        avg_ndcg10 = sum(r["ndcg10"] for r in results.values()) / len(results)
        avg_latency = sum(r["latency_ms"] for r in results.values()) / len(results)

        # p99 latency
        sorted_latencies = sorted(latencies)
        p99_idx = int(0.99 * len(sorted_latencies))
        p99_latency = sorted_latencies[p99_idx] * 1000 if sorted_latencies else 0

        summary = {
            "num_queries": len(results),
            "avg_p5": avg_p5,
            "avg_p10": avg_p10,
            "avg_r10": avg_r10,
            "avg_ndcg10": avg_ndcg10,
            "avg_latency_ms": avg_latency,
            "p99_latency_ms": p99_latency,
            "targets_met": {
                "p5_gt_60": avg_p5 > 0.60,
                "r10_gt_70": avg_r10 > 0.70,
                "p99_lt_2000ms": p99_latency < 2000,
            },
        }
    else:
        summary = {
            "num_queries": 0,
            "avg_p5": 0.0,
            "avg_p10": 0.0,
            "avg_r10": 0.0,
            "avg_ndcg10": 0.0,
            "avg_latency_ms": 0.0,
            "p99_latency_ms": 0.0,
            "targets_met": {
                "p5_gt_60": False,
                "r10_gt_70": False,
                "p99_lt_2000ms": True,
            },
        }

    return {
        "summary": summary,
        "queries": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate find_related semantic relevance")
    parser.add_argument("--repo", type=Path, help="Path to repository to evaluate")
    parser.add_argument("--context-dir", type=Path, help="Path to context directory")
    parser.add_argument("--limit", type=int, default=10, help="Number of results per query")
    parser.add_argument("--output", type=Path, help="Output JSON file for results")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.repo:
        repo_path = args.repo
        context_dir = args.context_dir or repo_path / ".context"
    else:
        # Use relevance fixture
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        repo_path = tmp / "relevance_repo"
        shutil.copytree(FIXTURES_DIR / "relevance", repo_path)
        context_dir = repo_path / ".context"

    print(f"Evaluating find_related on: {repo_path}")
    print(f"Context dir: {context_dir}")
    print(f"Queries: {len(GROUND_TRUTH)}")
    print()

    eval_results = run_evaluation(repo_path, context_dir, limit=args.limit)

    summary = eval_results["summary"]
    print("=" * 60)
    print("find_related Semantic Relevance Evaluation")
    print("=" * 60)
    print(f"Queries run: {summary['num_queries']}")
    print()
    print(
        f"{'Query':<40} | {'P@5':>6} | {'P@10':>6} | {'R@10':>6} | {'NDCG@10':>7} | {'Latency':>8}"
    )
    print("-" * 60)

    for query_name, metrics in eval_results["queries"].items():
        print(
            f"{query_name:<40} | {metrics['p5']:>6.2f} | {metrics['p10']:>6.2f} | "
            f"{metrics['r10']:>6.2f} | {metrics['ndcg10']:>7.2f} | "
            f"{metrics['latency_ms']:>7.1f}ms"
        )

    print("-" * 60)
    print(
        f"{'AVERAGE':<40} | {summary['avg_p5']:>6.2f} | {summary['avg_p10']:>6.2f} | "
        f"{summary['avg_r10']:>6.2f} | {summary['avg_ndcg10']:>7.2f} | "
        f"{summary['avg_latency_ms']:>7.1f}ms"
    )
    print()
    print(f"p99 Latency: {summary['p99_latency_ms']:.1f}ms")
    print()
    print("Targets:")
    print(
        f"  P@5 > 0.60:     "
        f"{'PASS' if summary['targets_met']['p5_gt_60'] else 'FAIL'} "
        f"({summary['avg_p5']:.2f})"
    )
    print(
        f"  R@10 > 0.70:    "
        f"{'PASS' if summary['targets_met']['r10_gt_70'] else 'FAIL'} "
        f"({summary['avg_r10']:.2f})"
    )
    print(
        f"  p99 < 2000ms:   "
        f"{'PASS' if summary['targets_met']['p99_lt_2000ms'] else 'FAIL'} "
        f"({summary['p99_latency_ms']:.1f}ms)"
    )
    print("=" * 60)

    if args.output:
        with args.output.open("w") as f:
            json.dump(eval_results, f, indent=2)
        print(f"\nResults written to {args.output}")

    # Exit with error code if targets not met
    all_pass = all(summary["targets_met"].values())
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
