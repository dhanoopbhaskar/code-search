"""Multi-hop graph-query evaluation harness.

Indexes the hermetic ``multihop`` fixture (or a supplied repository), runs the
labelled questions through :class:`GraphQueryService`, and reports chain recall
at depths 2 and 3, seed recall, compact-output size, latency, edge-resolution
ratios, and resolved import counts.

Run standalone with::

    python tests/evaluation/multihop_eval.py
    python tests/evaluation/multihop_eval.py --repo /path/to/repo
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.conftest import FIXTURES_DIR, _indexed_components
from tests.evaluation.multihop_ground_truth import MULTIHOP_CASES, chain_is_present

DEFAULT_FIXTURE = "multihop"


def _short(name: str) -> str:
    """Return the trailing symbol name of an FQN."""
    return name.rsplit("::", 1)[-1]


def evaluate(comps: dict[str, Any]) -> dict[str, Any]:
    """Run the labelled multi-hop set over an indexed component registry."""
    from code_search.engine.graph import ModuleEdgeStore
    from code_search.engine.graph_query import GraphQueryService, edge_resolution_stats

    service = GraphQueryService(
        comps["db"],
        comps["symbol_store"],
        comps["edge_store"],
        comps["search"],
        comps.get("settings"),
    )
    depths = (2, 3)
    hits = dict.fromkeys(depths, 0)
    seed_hits = 0
    total_bytes = 0
    total_ms = 0.0
    per_case: list[dict[str, Any]] = []
    for case in MULTIHOP_CASES:
        seed_hit = False
        for depth in depths:
            start = time.monotonic()
            answer = service.query(case.question, depth=depth, max_nodes=120)
            elapsed = (time.monotonic() - start) * 1000
            fqns = [node.fqn for node in answer.nodes]
            matched = chain_is_present(case.chain, fqns)
            if matched:
                hits[depth] += 1
            if depth == 2:
                total_bytes = max(total_bytes, len(json.dumps(answer.as_dict())))
                total_ms += elapsed
                seed_hit = any(
                    _short(seed.fqn).startswith(case.seed_hint)
                    or case.seed_hint.endswith(_short(seed.fqn))
                    for seed in answer.seeds
                )
            per_case.append(
                {
                    "question": case.question,
                    "depth": depth,
                    "matched": matched,
                    "nodes": len(answer.nodes),
                    "seeds": [seed.fqn for seed in answer.seeds],
                }
            )
        if seed_hit:
            seed_hits += 1
    module_store = ModuleEdgeStore(comps["db"])
    with comps["db"].connect() as conn:
        rationale_count = int(
            conn.execute("SELECT COUNT(*) AS cnt FROM symbol_rationale;").fetchone()["cnt"]
        )
    return {
        "cases": len(MULTIHOP_CASES),
        "chain_recall_depth2": hits[2] / len(MULTIHOP_CASES),
        "chain_recall_depth3": hits[3] / len(MULTIHOP_CASES),
        "seed_recall": seed_hits / len(MULTIHOP_CASES),
        "max_answer_bytes": total_bytes,
        "mean_query_ms": round(total_ms / len(MULTIHOP_CASES), 1),
        "edge_resolution": edge_resolution_stats(comps["db"]),
        "imports": module_store.resolution_stats("IMPORTS"),
        "rationale_count": rationale_count,
        "per_case": per_case,
    }


def main(argv: list[str] | None = None) -> int:
    """Index the fixture (or ``--repo``) and print the evaluation metrics."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="Repository to index instead of the fixture")
    args = parser.parse_args(argv)

    temp_dir = Path(tempfile.mkdtemp(prefix="code-search-multihop-"))
    try:
        if args.repo:
            repo = Path(args.repo).resolve()
        else:
            repo = temp_dir / DEFAULT_FIXTURE
            shutil.copytree(FIXTURES_DIR / DEFAULT_FIXTURE, repo)
        comps = _indexed_components(repo, temp_dir / ".context")
        metrics = evaluate(comps)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
