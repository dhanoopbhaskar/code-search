"""Benchmarks: incremental-update scaling and batch-embedding throughput.

Both suites run offline (``air_gap_enforcement``): they exercise only
the local Model2Vec model, local SQLite, and the flat-file vector store.
"""

import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from src.engine.config import Settings
from src.engine.redactor import air_gap_enforcement


def _build_repo(repo: Path, num_files: int) -> None:
    (repo / "src").mkdir(parents=True, exist_ok=True)
    for i in range(num_files):
        body = "\n".join(f"    x{j} = {i} + {j}" for j in range(8))
        (repo / "src" / f"mod_{i:04d}.py").write_text(f"def func_{i}():\n{body}\n    return {i}\n")


def _make_orchestrator(repo: Path) -> dict[str, Any]:
    from src.context import ContextManager
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.graph import GraphDatabase, IndexMetadataStore
    from src.engine.indexer import IndexOrchestrator
    from src.engine.parser import ASTParser
    from src.engine.symbols import SymbolExtractor, SymbolStore

    context_dir = repo / ".context"
    settings = Settings(context_dir=context_dir)
    ctx = ContextManager(settings)
    ctx.ensure()
    paths = ctx.paths

    db = GraphDatabase(paths["graph"], settings)
    db.initialize()
    meta = IndexMetadataStore(db)
    parser = ASTParser()
    symbol_extractor = SymbolExtractor(parser)
    symbol_store = SymbolStore(db, settings)
    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(
        paths.get("vectors_bin", context_dir / "vectors.bin"),
        paths.get("vectors_meta", context_dir / "vectors.meta.json"),
    )
    vector_index.load()

    orchestrator = IndexOrchestrator(
        db=db,
        metadata_store=meta,
        parser=parser,
        symbol_extractor=symbol_extractor,
        symbol_store=symbol_store,
        embedding_generator=embedding_gen,
        vector_index=vector_index,
        context_dir=context_dir,
        settings=settings,
    )
    return {
        "orchestrator": orchestrator,
        "embedding_gen": embedding_gen,
    }


@pytest.mark.benchmark
@pytest.mark.slow
def test_incremental_update_scales_with_change_volume(tmp_path: Path) -> None:
    """Update time grows with K and is corpus-size independent.

    A 64-file incremental update must cost measurably more than a 1-file
    update (a per-run corpus-wide pass would drown the K signal), and a fixed
    K=8 update must not blow up when the corpus doubles in size.

    Each update is sampled several times and the fastest round is kept: a
    single wall-clock sample carries residual full-suite load (page-cache
    eviction, connection-pool and worker-process settling) that can inflate
    the short K=1 baseline enough to mask the K signal.
    """
    if not _model_available():
        pytest.skip("embedding model unavailable")
    with air_gap_enforcement():
        n = 300
        repo = tmp_path / "scaling_repo"
        _build_repo(repo, n)
        comps = _make_orchestrator(repo)
        orch = comps["orchestrator"]
        orch.index_codebase(root_path=repo, force=True, verbose=False)

        round_no = [0]

        def update(k: int, rounds: int = 3) -> float:
            best = float("inf")
            for _ in range(rounds):
                round_no[0] += 1
                for i in range(k):
                    path = repo / "src" / f"mod_{i:04d}.py"
                    path.write_text(f"def func_{i}():\n    x = {round_no[0]}\n    return {i}\n")
                start = time.monotonic()
                orch.index_codebase(root_path=repo, incremental=True, verbose=False)
                best = min(best, time.monotonic() - start)
            return best

        update(1, rounds=1)  # warm-up round so one-off costs settle
        t_k1 = update(1)
        t_k64 = update(64)
        assert t_k64 > 2.0 * t_k1, (
            f"64-file update ({t_k64:.4f}s) not > 2x the 1-file update ({t_k1:.4f}s) — "
            "a corpus-wide per-run pass is dominating the measured path"
        )

        t_k8_base = update(8)
        for i in range(n):
            path = repo / "src" / f"extra_{i:04d}.py"
            path.write_text(f"def extra_{i}():\n    return {i}\n")
        orch.index_codebase(root_path=repo, force=True, verbose=False)
        t_k8_doubled = update(8)
        assert t_k8_doubled < max(2.5 * t_k8_base, 0.05), (
            f"doubling the corpus inflated the K=8 update: {t_k8_base:.4f}s -> {t_k8_doubled:.4f}s"
        )


@pytest.mark.benchmark
@pytest.mark.slow
def test_embed_throttle_batch_throughput(tmp_path: Path) -> None:
    """One batched encode is at least as fast per doc.

    Per-document throughput of a single ``encode_batch`` call must be >= the
    per-document throughput of N separate ``encode`` calls, and the vectors
    must match within float tolerance. Runs entirely on the local model.
    """
    from src.engine.embeddings import EmbeddingGenerator

    if not _model_available():
        pytest.skip("embedding model unavailable")
    with air_gap_enforcement():
        generator = EmbeddingGenerator(Settings(context_dir=tmp_path))
        texts = [f"def func_{i}(x): return x + {i}" for i in range(200)]

        start = time.monotonic()
        for text in texts:
            generator.encode(text)
        per_doc = (time.monotonic() - start) / len(texts)

        start = time.monotonic()
        batched = generator.encode_batch(texts)
        batch_doc = (time.monotonic() - start) / len(texts)

        assert all(v is not None for v in batched)
        assert batch_doc <= per_doc, (
            f"batch per-doc ({batch_doc:.6f}s) slower than per-doc ({per_doc:.6f}s)"
        )

        singles = [generator.encode(text) for text in texts]
        for batch_vec, single_vec in zip(batched, singles, strict=True):
            if single_vec is not None:
                assert batch_vec is not None
                np.testing.assert_allclose(batch_vec, single_vec, atol=1e-5)


def _model_available() -> bool:
    from src.engine.embeddings import EmbeddingGenerator

    return EmbeddingGenerator().is_available()
