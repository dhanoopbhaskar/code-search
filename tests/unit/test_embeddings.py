import os
from pathlib import Path

import numpy as np
import pytest

from src.engine.embeddings import EMBEDDING_BYTES, EMBEDDING_DIM, EmbeddingGenerator, VectorIndex


@pytest.fixture
def generator() -> EmbeddingGenerator:
    return EmbeddingGenerator()


def test_encode_returns_none_without_model(generator: EmbeddingGenerator) -> None:
    result = generator.encode("test text")
    assert result is None or isinstance(result, np.ndarray)


def test_embedding_to_bytes_roundtrip(generator: EmbeddingGenerator) -> None:
    vec = np.ones(EMBEDDING_DIM, dtype=np.float32)
    data = generator.embedding_to_bytes(vec)
    assert len(data) == EMBEDDING_BYTES
    restored = generator.bytes_to_embedding(data)
    np.testing.assert_array_almost_equal(vec, restored)


def test_embedding_bytes_length() -> None:
    vec = np.random.randn(EMBEDDING_DIM).astype(np.float32)
    data = vec.tobytes()
    assert len(data) == EMBEDDING_BYTES


def test_embedding_normalized(generator: EmbeddingGenerator) -> None:
    vec = np.array([3.0, 4.0] + [0.0] * (EMBEDDING_DIM - 2), dtype=np.float32)
    data = generator.embedding_to_bytes(vec)
    restored = generator.bytes_to_embedding(data)
    norm = np.linalg.norm(restored)
    assert norm > 0


def test_bytes_to_embedding_wrong_size(generator: EmbeddingGenerator) -> None:
    data = b"x" * 64
    vec = generator.bytes_to_embedding(data)
    assert len(vec) == EMBEDDING_DIM


def test_vector_index_empty_search() -> None:
    from pathlib import Path

    idx = VectorIndex(Path("/tmp/test_vectors.bin"), Path("/tmp/test_meta.json"))
    q = np.ones(EMBEDDING_DIM, dtype=np.float32)
    results = idx.search(q, top_k=5)
    assert results == []


def test_vector_index_search_ranked_by_similarity(tmp_path: Path) -> None:
    bin_path = tmp_path / "vectors.bin"
    meta_path = tmp_path / "vectors.meta.json"
    idx = VectorIndex(bin_path, meta_path)
    emb_query = np.array([1.0, 0.0] + [0.0] * (EMBEDDING_DIM - 2), dtype=np.float32)
    emb_close = np.array([0.9, 0.1] + [0.0] * (EMBEDDING_DIM - 2), dtype=np.float32)
    emb_far = np.array([0.1, 0.9] + [0.0] * (EMBEDDING_DIM - 2), dtype=np.float32)
    idx.add(1, emb_close, {"file_path": "close.py", "fqn": "close"})
    idx.add(2, emb_far, {"file_path": "far.py", "fqn": "far"})
    results = idx.search(emb_query, top_k=2)
    assert len(results) == 2
    assert results[0][0] == 1
    assert results[0][1] > results[1][1]


def test_vector_index_add_requires_nonempty_file_path(tmp_path: Path) -> None:
    bin_path = tmp_path / "vectors.bin"
    meta_path = tmp_path / "vectors.meta.json"
    idx = VectorIndex(bin_path, meta_path)
    emb = np.ones(EMBEDDING_DIM, dtype=np.float32)
    with pytest.raises(ValueError):
        idx.add(1, emb, {"file_path": "", "fqn": ""})
    with pytest.raises(ValueError):
        idx.add(1, emb, {})


def test_vector_index_save_persists_nonempty_file_path_and_fqn(tmp_path: Path) -> None:
    import json

    bin_path = tmp_path / "vectors.bin"
    meta_path = tmp_path / "vectors.meta.json"
    idx1 = VectorIndex(bin_path, meta_path)
    emb = np.ones(EMBEDDING_DIM, dtype=np.float32)
    idx1.add(1, emb, {"file_path": "a.py", "fqn": "mod.a"})
    idx1.save()

    entries = [json.loads(line) for line in meta_path.read_text().splitlines() if line.strip()]
    assert entries
    for entry in entries:
        assert (entry.get("file_path") or "").strip()
        assert (entry.get("fqn") or "").strip()


def test_argpartition_matches_argsort_top_k(tmp_path: Path) -> None:
    rng = np.random.default_rng(2026)
    for n in (5, 100, 1000):
        bin_path = tmp_path / f"vectors_{n}.bin"
        meta_path = tmp_path / f"vectors_{n}.meta.json"
        idx = VectorIndex(bin_path, meta_path)
        for cid in range(n):
            vec = rng.uniform(-1.0, 1.0, EMBEDDING_DIM).astype(np.float32)
            idx.add(cid, vec, {"file_path": f"f{cid}.py"})
        query = rng.uniform(-1.0, 1.0, EMBEDDING_DIM).astype(np.float32)
        q_norm = np.linalg.norm(query)
        q = query / q_norm if q_norm > 0 else query
        dots = idx._vectors @ q
        for k in (1, 3, 10):
            if k > n:
                continue
            expected = [idx._metadata[i]["chunk_id"] for i in np.argsort(dots)[-k:][::-1]]
            results = idx.search(query, top_k=k)
            assert [cid for cid, _ in results] == expected


def test_vector_index_add_and_search(tmp_path: Path) -> None:
    bin_path = tmp_path / "vectors.bin"
    meta_path = tmp_path / "vectors.meta.json"
    idx = VectorIndex(bin_path, meta_path)
    emb1 = np.ones(EMBEDDING_DIM, dtype=np.float32)
    emb2 = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    idx.add(1, emb1, {"file_path": "a.py", "fqn": "a"})
    idx.add(2, emb2, {"file_path": "b.py", "fqn": "b"})
    results = idx.search(emb1, top_k=2)
    assert len(results) >= 1
    assert results[0][0] == 1
    assert results[0][1] > 0


def test_vector_index_save_and_load(tmp_path: Path) -> None:
    bin_path = tmp_path / "vectors.bin"
    meta_path = tmp_path / "vectors.meta.json"
    idx1 = VectorIndex(bin_path, meta_path)
    emb = np.ones(EMBEDDING_DIM, dtype=np.float32)
    idx1.add(42, emb, {"file_path": "test.py", "fqn": "test"})
    idx1.save()
    idx2 = VectorIndex(bin_path, meta_path)
    idx2.load()
    assert idx2.size == 1
    results = idx2.search(emb, top_k=1)
    assert len(results) == 1
    assert results[0][0] == 42


def test_vector_index_remove(tmp_path: Path) -> None:
    bin_path = tmp_path / "vectors.bin"
    meta_path = tmp_path / "vectors.meta.json"
    idx = VectorIndex(bin_path, meta_path)
    idx.add(1, np.ones(EMBEDDING_DIM, dtype=np.float32), {"file_path": "a.py"})
    idx.add(2, np.ones(EMBEDDING_DIM, dtype=np.float32), {"file_path": "b.py"})
    assert idx.size == 2
    assert idx.remove(1) is True
    assert idx.size == 1
    assert idx.remove(999) is False
    assert idx.size == 1


def test_batch_remove_keeps_rows_but_masks_them(tmp_path: Path) -> None:
    bin_path = tmp_path / "vectors.bin"
    meta_path = tmp_path / "vectors.meta.json"
    idx = VectorIndex(bin_path, meta_path)
    vectors: dict[int, np.ndarray] = {}
    for cid in range(10):
        vec = np.full(EMBEDDING_DIM, float(cid + 1), dtype=np.float32)
        vectors[cid] = vec
        idx.add(cid, vec, {"file_path": f"f{cid}.py", "fqn": f"sym{cid}"})
    assert idx.remove_many([2, 5, 7]) == 3
    # stale rows are masked, never copied or physically removed
    assert idx.size == 7
    alive_ids = {m["chunk_id"] for m, alive in zip(idx._metadata, idx._alive, strict=True) if alive}
    assert alive_ids == {0, 1, 3, 4, 6, 8, 9}
    for cid in range(10):
        np.testing.assert_array_equal(idx._vectors[cid], vectors[cid])


def test_batch_remove_arbitrary_order_and_noops(tmp_path: Path) -> None:
    bin_path = tmp_path / "vectors.bin"
    meta_path = tmp_path / "vectors.meta.json"
    idx = VectorIndex(bin_path, meta_path)
    for cid in range(20):
        idx.add(
            cid,
            np.full(EMBEDDING_DIM, float(cid), dtype=np.float32),
            {"file_path": f"f{cid}.py"},
        )
    before_vectors = idx._vectors.copy()
    before_metadata = list(idx._metadata)
    assert idx.remove_many([]) == 0
    assert idx.remove_many([999, -1]) == 0
    assert idx.size == 20
    np.testing.assert_array_equal(idx._vectors, before_vectors)
    assert idx._metadata == before_metadata
    assert idx.remove_many([13, 1, 19, 7, 1]) == 4
    assert idx.size == 16
    removed = {13, 1, 19, 7}
    for meta, alive in zip(idx._metadata, idx._alive, strict=True):
        assert (meta["chunk_id"] in removed) is not alive
    for cid in range(20):
        np.testing.assert_array_equal(
            idx._vectors[cid], np.full(EMBEDDING_DIM, float(cid), dtype=np.float32)
        )


def test_remove_many_masks_search_and_size(tmp_path: Path) -> None:
    bin_path = tmp_path / "vectors.bin"
    meta_path = tmp_path / "vectors.meta.json"
    idx = VectorIndex(bin_path, meta_path)
    vectors: dict[int, np.ndarray] = {}
    for cid in range(10):
        vec = np.full(EMBEDDING_DIM, float(cid + 1), dtype=np.float32)
        vectors[cid] = vec
        idx.add(cid, vec, {"file_path": f"f{cid}.py"})
    rows_before = idx._vectors.copy()
    assert idx.remove_many([2, 5, 7]) == 3
    np.testing.assert_array_equal(idx._vectors, rows_before)
    assert idx.remove_many([2, 999, -1]) == 0
    np.testing.assert_array_equal(idx._vectors, rows_before)
    results = idx.search(vectors[0], top_k=10)
    returned_ids = {cid for cid, _ in results}
    assert returned_ids == {0, 1, 3, 4, 6, 8, 9}


def test_remove_many_append_after_removal_keeps_identity(tmp_path: Path) -> None:
    bin_path = tmp_path / "vectors.bin"
    meta_path = tmp_path / "vectors.meta.json"
    idx = VectorIndex(bin_path, meta_path)
    for cid in range(5):
        idx.add(
            cid, np.full(EMBEDDING_DIM, float(cid), dtype=np.float32), {"file_path": f"f{cid}.py"}
        )
    assert idx.remove_many([2]) == 1
    new_index = idx.add(99, np.full(EMBEDDING_DIM, 9.0, dtype=np.float32), {"file_path": "f99.py"})
    assert new_index == 5
    assert idx.size == 5
    alive_ids = {m["chunk_id"] for m, alive in zip(idx._metadata, idx._alive, strict=True) if alive}
    assert alive_ids == {0, 1, 3, 4, 99}


def test_save_load_preserves_tombstones(tmp_path: Path) -> None:
    bin_path = tmp_path / "vectors.bin"
    meta_path = tmp_path / "vectors.meta.json"
    idx1 = VectorIndex(bin_path, meta_path)
    for cid in range(5):
        vec = np.full(EMBEDDING_DIM, float(cid), dtype=np.float32)
        idx1.add(cid, vec, {"file_path": f"f{cid}.py"})
    assert idx1.remove_many([1, 3]) == 2
    idx1.save()

    idx2 = VectorIndex(bin_path, meta_path)
    idx2.load()
    assert idx2.size == 3
    ids2 = {cid for cid, _ in idx2.search(np.zeros(EMBEDDING_DIM, dtype=np.float32), top_k=5)}
    assert ids2 == {0, 2, 4}

    idx2.add(99, np.full(EMBEDDING_DIM, 5.0, dtype=np.float32), {"file_path": "f99.py"})
    idx2.save()

    idx3 = VectorIndex(bin_path, meta_path)
    idx3.load()
    assert idx3.size == 4
    ids3 = {cid for cid, _ in idx3.search(np.zeros(EMBEDDING_DIM, dtype=np.float32), top_k=10)}
    assert ids3 == {0, 2, 4, 99}


def test_save_writes_delta_only(tmp_path: Path) -> None:
    bin_path = tmp_path / "vectors.bin"
    meta_path = tmp_path / "vectors.meta.json"
    idx = VectorIndex(bin_path, meta_path)
    idx.add(1, np.full(EMBEDDING_DIM, 1.0, dtype=np.float32), {"file_path": "f1.py"})
    idx.save()
    first_size = bin_path.stat().st_size
    idx.add(2, np.full(EMBEDDING_DIM, 2.0, dtype=np.float32), {"file_path": "f2.py"})
    idx.save()
    assert bin_path.stat().st_size == first_size + EMBEDDING_BYTES
    idx2 = VectorIndex(bin_path, meta_path)
    idx2.load()
    assert idx2.size == 2


def test_vector_index_clear(tmp_path: Path) -> None:
    bin_path = tmp_path / "vectors.bin"
    meta_path = tmp_path / "vectors.meta.json"
    idx = VectorIndex(bin_path, meta_path)
    idx.add(1, np.ones(EMBEDDING_DIM, dtype=np.float32), {"file_path": "f1.py"})
    idx.clear()
    assert idx.size == 0


def test_is_available_returns_bool(generator: EmbeddingGenerator) -> None:
    available = generator.is_available()
    assert isinstance(available, bool)


def test_encode_after_init(generator: EmbeddingGenerator) -> None:
    result = generator.encode("def foo(): pass")
    assert result is None or isinstance(result, np.ndarray)


def test_encode_batch_matches_per_item_vectors(tmp_path: Path) -> None:
    from src.engine.config import Settings

    generator = EmbeddingGenerator(Settings(context_dir=tmp_path))
    texts = ["def foo(): pass", "class Bar:\n    pass", "x = 1\n", ""]
    batched = generator.encode_batch(texts)
    single = [generator.encode(t) for t in texts]
    assert len(batched) == len(texts)
    for batch_vec, single_vec in zip(batched, single, strict=True):
        if single_vec is None:
            assert batch_vec is None
        else:
            assert batch_vec is not None
            assert batch_vec.shape == single_vec.shape == (EMBEDDING_DIM,)
            np.testing.assert_allclose(batch_vec, single_vec, atol=1e-5)


def test_is_available_sets_loaded_flag(tmp_path: Path) -> None:
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator

    settings = Settings(context_dir=tmp_path, embedding_model="nonexistent-model")
    gen = EmbeddingGenerator(settings)
    available = gen.is_available()
    assert isinstance(available, bool)


def test_find_local_model_path_search_order(tmp_path: Path) -> None:
    from src.engine.embeddings import _find_local_model_path

    model_name = "test-model"
    model_dir = tmp_path / "models" / model_name
    model_dir.mkdir(parents=True)
    (model_dir / "model.safetensors").write_text("dummy")

    old_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        result = _find_local_model_path(model_name)
        assert result is not None
        assert result == model_dir
    finally:
        os.chdir(old_cwd)


def test_find_local_model_path_env_override(tmp_path: Path) -> None:
    from src.engine.embeddings import _find_local_model_path

    model_name = "override-model"
    custom_path = tmp_path / "custom" / "models" / model_name
    custom_path.mkdir(parents=True)
    (custom_path / "model.safetensors").write_text("dummy")

    old_env = os.environ.get("CODE_SEARCH_MODEL_PATH")
    try:
        os.environ["CODE_SEARCH_MODEL_PATH"] = str(custom_path)
        result = _find_local_model_path(model_name)
        assert result is not None
        assert result.resolve() == custom_path.resolve()
    finally:
        if old_env is not None:
            os.environ["CODE_SEARCH_MODEL_PATH"] = old_env
        else:
            del os.environ["CODE_SEARCH_MODEL_PATH"]


def test_find_local_model_path_returns_none(tmp_path: Path) -> None:
    from src.engine.embeddings import _find_local_model_path

    result = _find_local_model_path("nonexistent-model-name")
    assert result is None or result.is_dir()


def test_find_local_model_path_install_share_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.engine import embeddings as emb

    model_name = "share-model"
    prefix = tmp_path / "venv"
    share_dir = prefix / "share" / "code-search" / "models" / model_name
    share_dir.mkdir(parents=True)
    (share_dir / "model.safetensors").write_text("dummy")

    fake_sys = type("FakeSys", (), {"prefix": str(prefix), "argv": ["code-search"]})()
    monkeypatch.setattr(emb, "sys", fake_sys)
    monkeypatch.delenv("CODE_SEARCH_MODEL_PATH", raising=False)
    monkeypatch.delenv("CODE_SEARCH_DATA_DIR", raising=False)
    result = emb._find_local_model_path(model_name)
    assert result == share_dir


def test_find_local_model_path_user_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.engine import embeddings as emb

    model_name = "userbase-model"
    user_base = tmp_path / "userbase"
    model_dir = user_base / "share" / "code-search" / "models" / model_name
    model_dir.mkdir(parents=True)
    (model_dir / "model.safetensors").write_text("dummy")

    monkeypatch.setattr(emb, "_get_user_base", lambda: user_base)
    monkeypatch.delenv("CODE_SEARCH_MODEL_PATH", raising=False)
    monkeypatch.delenv("CODE_SEARCH_DATA_DIR", raising=False)
    result = emb._find_local_model_path(model_name)
    assert result == model_dir


def test_find_local_model_path_package_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.engine import embeddings as emb

    model_name = "pkg-model"
    fake_module = tmp_path / "src" / "engine" / "embeddings.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.touch()
    model_dir = tmp_path / "models" / model_name
    model_dir.mkdir(parents=True)
    (model_dir / "model.safetensors").write_text("dummy")

    monkeypatch.setattr(emb, "__file__", str(fake_module))
    monkeypatch.delenv("CODE_SEARCH_MODEL_PATH", raising=False)
    monkeypatch.delenv("CODE_SEARCH_DATA_DIR", raising=False)
    result = emb._find_local_model_path(model_name)
    assert result is not None
    assert result.resolve() == model_dir.resolve()


def test_get_binary_dir(tmp_path: Path) -> None:
    from src.engine.embeddings import _get_binary_dir

    result = _get_binary_dir()
    assert result is None or isinstance(result, Path)


class _FakeMetadataStore:
    """Minimal ``IndexMetadataStore`` stand-in for the scheme guard tests."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = dict(values)

    def get(self, key: str) -> str | None:
        return self._values.get(key)

    def get_int(self, key: str) -> int | None:
        value = self._values.get(key)
        return int(value) if value is not None else None

    def set_int(self, key: str, value: int) -> None:
        self._values[key] = str(value)


def test_representation_scheme_helpers_roundtrip() -> None:
    from src.engine.embeddings import (
        get_representation_scheme_version,
        set_representation_scheme_version,
    )

    store = _FakeMetadataStore({})
    assert get_representation_scheme_version(store) is None
    set_representation_scheme_version(store, 3)
    assert get_representation_scheme_version(store) == 3


def test_representation_compat_equal_scheme_passes() -> None:
    from src.engine.embeddings import (
        REPRESENTATION_SCHEME_VERSION,
        check_index_representation_compatibility,
    )

    store = _FakeMetadataStore(
        {"representation_scheme_version": str(REPRESENTATION_SCHEME_VERSION)}
    )
    check_index_representation_compatibility(store, has_vectors=True)


def test_representation_compat_older_scheme_raises() -> None:
    from src.engine.embeddings import check_index_representation_compatibility

    store = _FakeMetadataStore({"representation_scheme_version": "0"})
    with pytest.raises(ValueError, match="--force"):
        check_index_representation_compatibility(store, has_vectors=True)


def test_representation_compat_newer_scheme_raises() -> None:
    from src.engine.embeddings import check_index_representation_compatibility

    store = _FakeMetadataStore({"representation_scheme_version": "999"})
    with pytest.raises(ValueError, match="--force"):
        check_index_representation_compatibility(store, has_vectors=True)


def test_representation_compat_absent_marker_engine_built_raises() -> None:
    from src.engine.embeddings import check_index_representation_compatibility

    store = _FakeMetadataStore({"vector_model_name": "potion-code-16m-32d"})
    with pytest.raises(ValueError, match="--force"):
        check_index_representation_compatibility(store, has_vectors=True)


def test_representation_compat_absent_marker_synthetic_compatible() -> None:
    from src.engine.embeddings import check_index_representation_compatibility

    store = _FakeMetadataStore({})
    check_index_representation_compatibility(store, has_vectors=True)


def test_representation_compat_absent_marker_without_vectors_compatible() -> None:
    from src.engine.embeddings import check_index_representation_compatibility

    store = _FakeMetadataStore({"vector_model_name": "potion-code-16m-32d"})
    check_index_representation_compatibility(store, has_vectors=False)
