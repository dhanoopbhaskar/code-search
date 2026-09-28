from pathlib import Path

import pytest

from src.engine.search import rrf_fusion, tokenize


class _MockBM25Search:
    def __init__(self, results: list[tuple[int, float]]) -> None:
        self._results = results

    def search(self, _query: str = "", **_kwargs: object) -> list[tuple[int, float]]:
        return self._results

    def count(self, _query: str = "", **_kwargs: object) -> int:
        return len(self._results)


class _MockVectorSearch:
    def __init__(self, results: list[tuple[int, float]]) -> None:
        self._results = results

    def search(self, _query: str = "", **_kwargs: object) -> list[tuple[int, float]]:
        return self._results


def _build_gate_db(tmp_path: Path) -> object:
    """Controlled corpus for the query-quality gate.

    ``token`` is deliberately common (5/8 chunks -> low IDF) while ``pageable``
    is rare (1/8 chunks -> high IDF), and ``tok_a`` carries the boilerplate
    sub-word ``this`` so a nonsense query shares a lexical hit with real code.
    """
    from src.engine.config import Settings
    from src.engine.graph import GraphDatabase

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "gate.db", settings)
    db.initialize()
    rows = [
        (
            "mod.tok_a",
            "tok_a.py",
            "def validate_token(this): return this.token",
            "def validate token this return",
        ),
        ("mod.tok_b", "tok_b.py", "def check_token(t): return t", "def check token return"),
        ("mod.tok_c", "tok_c.py", "def issue_token(): pass", "def issue token pass"),
        ("mod.tok_d", "tok_d.py", "def revoke_token(): pass", "def revoke token pass"),
        ("mod.tok_e", "tok_e.py", "def refresh_token(): pass", "def refresh token pass"),
        ("mod.pag", "pag.py", "class Pageable: pass", "class pageable pass"),
        ("mod.art", "art.py", "def list_articles(): pass", "def list articles pass"),
        ("mod.util", "util.py", "def helper(): pass", "def helper pass"),
    ]
    with db.write_transaction() as conn:
        for fqn, path, content, subwords in rows:
            conn.execute(
                "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
                "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
                "VALUES (?, ?, 1, 2, ?, 'python', 1, 'ast', 'function', ?);",
                (fqn, path, content, subwords),
            )
    return db


def _gate_search(tmp_path: Path):
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path)
    db = _build_gate_db(tmp_path)
    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(tmp_path / "vectors.bin", tmp_path / "vectors.meta.json")
    vector_index.load()
    hs = HybridSearch(db, vector_index, embedding_gen, settings)
    hs._vector_search = _MockVectorSearch([])
    return hs


def _build_rare_token_db(tmp_path: Path) -> object:
    """Controlled corpus where ``token`` is rare (2/8 chunks), so on small
    corpora it reads as informative (mirroring the fixture's df=2/11). A
    gibberish multi-token query sharing only that single token must still be
    rejected by concept-signal coverage."""
    from src.engine.config import Settings
    from src.engine.graph import GraphDatabase

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "rare.db", settings)
    db.initialize()
    rows = [
        ("mod.tok_a", "tok_a.py", "def validate_token(t): return t", "def validate token return"),
        ("mod.tok_b", "tok_b.py", "def check_token(t): return t", "def check token return"),
        ("mod.pag", "pag.py", "class Pageable: pass", "class pageable pass"),
        ("mod.art", "art.py", "def list_articles(): pass", "def list articles pass"),
        ("mod.usr", "usr.py", "def list_users(): pass", "def list users pass"),
        ("mod.ord", "ord.py", "def list_orders(): pass", "def list orders pass"),
        ("mod.pay", "pay.py", "def list_payments(): pass", "def list payments pass"),
        ("mod.util", "util.py", "def helper(): pass", "def helper pass"),
    ]
    with db.write_transaction() as conn:
        for fqn, path, content, subwords in rows:
            conn.execute(
                "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
                "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
                "VALUES (?, ?, 1, 2, ?, 'python', 1, 'ast', 'function', ?);",
                (fqn, path, content, subwords),
            )
    return db


def _rare_gate_search(tmp_path: Path):
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path)
    db = _build_rare_token_db(tmp_path)
    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(tmp_path / "rare_vectors.bin", tmp_path / "rare_vectors.meta.json")
    vector_index.load()
    hs = HybridSearch(db, vector_index, embedding_gen, settings)
    hs._vector_search = _MockVectorSearch([])
    return hs


def test_gate_rejects_nonsense_query(tmp_path: Path) -> None:
    hs = _gate_search(tmp_path)
    results = hs.search("does this file exist findAnyMethodThatDoesNotExist", limit=10)["results"]
    assert len(results) == 0, "Nonsense query must return zero results"


def test_gate_accepts_pagination_query(tmp_path: Path) -> None:
    hs = _gate_search(tmp_path)
    # pagination is not an exact corpus token on this DB (coverage 0), so the
    # The vector leg must carry it: the Pageable chunk (id 6) clears the floor.
    hs._vector_search = _MockVectorSearch([(6, 0.9)])
    results = hs.search("pagination", limit=10)["results"]
    assert len(results) >= 1, "pagination must return at least one relevant result"
    assert any("pageable" in (r.get("content") or "").lower() for r in results)


def test_gate_rejects_gibberish_sharing_common_token(tmp_path: Path) -> None:
    hs = _gate_search(tmp_path)
    results = hs.search("wqrble token", limit=10)["results"]
    assert len(results) == 0, "Gibberish query sharing only a common token must be rejected"


def test_gate_informative_tokens(tmp_path: Path) -> None:
    from src.engine.config import Settings
    from src.engine.search import BM25Search

    settings = Settings(context_dir=tmp_path)
    db = _build_gate_db(tmp_path)
    bm = BM25Search(db, settings)
    assert "pagination" in bm.informative_tokens("pagination")
    assert "token" not in bm.informative_tokens("wqrble token")
    assert bm.informative_tokens("does this file exist findAnyMethodThatDoesNotExist") == []


def test_gate_rejects_single_rare_shared_token(tmp_path: Path) -> None:
    """With the rescue floor contract, pure-gibberish queries (zero token overlap)
    return no_match, but borderline queries with at least one meaningful token
    are allowed to return rescue results."""
    hs = _rare_gate_search(tmp_path)
    # Pure gibberish (no token overlap) should be rejected entirely
    results = hs.search("wqrble florble", limit=10)["results"]
    assert len(results) == 0, "Pure gibberish must return zero results"
    # Borderline queries with one real token now return rescue results
    results = hs.search("wqrble token", limit=10)["results"]
    assert len(results) >= 1, "Borderline query with one real token should return rescue results"
    results = hs.search("florble token waffle", limit=10)["results"]
    assert len(results) >= 1, "Borderline query with one real token should return rescue results"
    # Multi-signal concept query should pass the main gate
    results = hs.search("token valid", limit=10)["results"]
    assert len(results) >= 1, "Multi-signal concept query 'token valid' must pass"


def _trust_gate_search(
    tmp_path: Path,
    coverage: float,
    *,
    no_model: bool = False,
    relevance_gate: bool = True,
):
    """A ``HybridSearch`` whose query-analysis carries a chosen coverage.

    Lets the gate tests control the exact-token coverage signal directly
    while keeping the real BM25/corpus layer underneath.
    """
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.language import QueryAnalysis
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path, relevance_gate=relevance_gate)
    db = _build_gate_db(tmp_path)
    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(tmp_path / "trust_vectors.bin", tmp_path / "trust_vectors.meta.json")
    vector_index.load()
    hs = HybridSearch(db, vector_index, embedding_gen, settings, no_model=no_model)
    hs._vector_search = _MockVectorSearch([])
    hs._analysis = QueryAnalysis(
        query="q",
        expanded_text="q",
        exact_tokens=["time"],
        coverage=coverage,
    )
    return hs


def test_trust_gate_rejects_low_coverage_low_vector(tmp_path: Path) -> None:
    """E1-style query — coverage 0.25 < floor AND top raw vector
    cosine 0.227 < floor -> gate rejects."""
    hs = _trust_gate_search(tmp_path, coverage=0.25)
    accepted, _ = hs._query_quality_gate(
        "websocket real time notifications",
        lexical_hit_count=1,
        informative=["time", "websocket"],
        raw_vector_results=[(6, 0.227)],
    )
    assert accepted is False


def test_trust_gate_accepts_high_coverage(tmp_path: Path) -> None:
    """S3-style query — coverage 1.0 clears the floor, accepted
    regardless of the vector signal."""
    hs = _trust_gate_search(tmp_path, coverage=1.0)
    accepted, _ = hs._query_quality_gate(
        "check if the article title or slug is already taken before saving",
        lexical_hit_count=3,
        informative=["article", "title", "slug", "saving"],
        raw_vector_results=[(6, 0.1)],
    )
    assert accepted is True


def test_trust_gate_accepts_typo_via_vector_leg(tmp_path: Path) -> None:
    """Typo F1 ``jwt tokne genration`` has coverage 0.0 (typos are
    never exact corpus tokens) but the top raw vector cosine (0.658 >= floor)
    clears the vector leg, so the AND gate admits it — the F1 control."""
    hs = _trust_gate_search(tmp_path, coverage=0.0)
    accepted, _ = hs._query_quality_gate(
        "jwt tokne genration",
        lexical_hit_count=1,
        informative=["jwt", "tokne"],
        raw_vector_results=[(6, 0.658)],
    )
    assert accepted is True


def test_trust_gate_rejects_absent_acronym_low_vector(tmp_path: Path) -> None:
    """A genuinely-absent acronym (coverage 0.0) with only a weak
    vector hit (0.3 < floor) stays rejected — no confident false positive."""
    hs = _trust_gate_search(tmp_path, coverage=0.0)
    accepted, _ = hs._query_quality_gate(
        "commentresponse websocket",
        lexical_hit_count=1,
        informative=["commentresponse", "websocket"],
        raw_vector_results=[(6, 0.3)],
    )
    assert accepted is False


def test_trust_gate_no_model_applies_coverage_gate(tmp_path: Path) -> None:
    """The ``--no-model`` lexical-only path has no vector arm, so a
    low-coverage query is rejected by the coverage gate alone."""
    hs = _trust_gate_search(tmp_path, coverage=0.25, no_model=True)
    accepted, _ = hs._query_quality_gate(
        "websocket real time notifications",
        lexical_hit_count=1,
        informative=["time", "websocket"],
        raw_vector_results=[],
    )
    assert accepted is False


def test_trust_gate_disabled_bypasses_coverage(tmp_path: Path) -> None:
    """``relevance_gate=False`` preserves the unconditional bypass —
    the coverage/vector floors never reject."""
    hs = _trust_gate_search(tmp_path, coverage=0.25, relevance_gate=False)
    accepted, _ = hs._query_quality_gate(
        "websocket real time notifications",
        lexical_hit_count=1,
        informative=["time", "websocket"],
        raw_vector_results=[(6, 0.227)],
    )
    assert accepted is True


def test_decompose_query_preserves_camel_case_boundaries() -> None:
    from src.engine.search import decompose_query

    words = decompose_query("findAnyMethodThatDoesNotExist")
    assert "find" in words
    assert "method" in words
    assert "exist" in words
    assert "findanymethodthatdoesnotexist" not in words


def test_gate_can_be_disabled(tmp_path: Path) -> None:
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path, relevance_gate=False)
    db = _build_gate_db(tmp_path)
    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(tmp_path / "vectors.bin", tmp_path / "vectors.meta.json")
    vector_index.load()
    hs = HybridSearch(db, vector_index, embedding_gen, settings)
    hs._vector_search = _MockVectorSearch([])
    results = hs.search("does this file exist findAnyMethodThatDoesNotExist", limit=10)["results"]
    assert len(results) >= 1, "With the gate disabled the query behaves as before"


def test_tokenize_simple() -> None:
    tokens = tokenize("validate JWT token")
    assert "validate" in tokens
    assert "jwt" in tokens
    assert "token" in tokens


def test_tokenize_stopwords_removed() -> None:
    tokens = tokenize("the and of for in code", filter_stopwords=True)
    assert "the" not in tokens
    assert "and" not in tokens
    assert "of" not in tokens
    assert "code" in tokens


def test_tokenize_single_char_filtered() -> None:
    tokens = tokenize("a b c variable", filter_stopwords=True)
    assert "a" not in tokens
    assert "variable" in tokens


def test_tokenize_camel_case() -> None:
    tokens = tokenize("validateToken")
    assert "validatetoken" in tokens


def test_decompose_query_splits_identifiers() -> None:
    from src.engine.search import decompose_query

    words = decompose_query("token valid")
    assert "token" in words
    assert "valid" in words


def test_decompose_query_subwords_match_identifier() -> None:
    from src.engine.search import decompose_query, identify_subwords

    words = set(decompose_query("token valid"))
    assert words.issubset(identify_subwords("isTokenValid"))


def test_build_fts_query_prefix_expansion() -> None:
    from src.engine.search import build_fts_query

    query = build_fts_query(["pagination"], exact_terms=set())
    assert "pag*" in query


def test_build_fts_query_exact_term_no_expansion() -> None:
    from src.engine.search import build_fts_query

    query = build_fts_query(["token"], exact_terms={"token"})
    assert "token" in query
    assert "tok*" not in query


def test_build_fts_query_matches_pageable_subwords() -> None:
    from src.engine.search import build_fts_query, decompose_query, identify_subwords

    corpus_tokens = set(identify_subwords("Pageable")) | set(identify_subwords("PageRequest"))
    query = build_fts_query(decompose_query("pagination"), exact_terms=corpus_tokens)
    assert "pag*" in query
    assert any(t in corpus_tokens for t in ("pageable", "pagerequest"))


def test_tokenize_with_symbols() -> None:
    tokens = tokenize("user.name = get_user()")
    assert "user" in tokens
    assert "name" in tokens
    assert "get_user" in tokens


def test_rrf_fusion_empty() -> None:
    result = rrf_fusion([], [], k=60)
    assert result == {}


def test_rrf_fusion_single_source() -> None:
    bm25 = [(1, 10.0), (2, 5.0)]
    vector: list = []
    result = rrf_fusion(bm25, vector, k=60)
    assert 1 in result
    assert 2 in result
    assert result[1] > result[2]


def test_rrf_fusion_combines_scores() -> None:
    bm25 = [(1, 10.0)]
    vector = [(1, 0.9)]
    result = rrf_fusion(bm25, vector, k=60)
    assert 1 in result
    assert 0.0 <= result[1] <= 1.0


def test_rrf_fusion_different_results() -> None:
    bm25 = [(1, 10.0), (2, 5.0)]
    vector = [(3, 0.9), (4, 0.8)]
    result = rrf_fusion(bm25, vector, k=60)
    assert 1 in result
    assert 2 in result
    assert 3 in result
    assert 4 in result
    assert result[1] > result[2]
    assert result[3] > result[4]


def test_rrf_fusion_configurable_k() -> None:
    bm25 = [(1, 10.0)]
    vector = [(2, 0.9)]
    result_k10 = rrf_fusion(bm25, vector, k=10)
    result_k100 = rrf_fusion(bm25, vector, k=100)
    assert 1 in result_k10
    assert 2 in result_k10
    assert 1 in result_k100
    assert 2 in result_k100


def test_tokenize_single_char_with_filter() -> None:
    tokens = tokenize("f x variable", filter_stopwords=False)
    assert "f" in tokens
    assert "x" in tokens
    assert "variable" in tokens


def test_tokenize_single_char_with_filter_off() -> None:
    tokens = tokenize("a b c", filter_stopwords=False)
    assert "a" in tokens
    assert "b" in tokens
    assert "c" in tokens


def test_tokenize_stopword_with_filter_on() -> None:
    tokens = tokenize("the variable code", filter_stopwords=True)
    assert "the" not in tokens
    assert "variable" in tokens
    assert "code" in tokens


def test_tokenize_stopword_with_filter_off() -> None:
    tokens = tokenize("the variable code", filter_stopwords=False)
    assert "the" in tokens
    assert "variable" in tokens
    assert "code" in tokens


def test_single_char_token_search() -> None:
    tokens = tokenize("f", filter_stopwords=False)
    assert "f" in tokens


def test_stopword_token_search() -> None:
    tokens = tokenize("the", filter_stopwords=False)
    assert "the" in tokens


def test_test_files_included_by_default() -> None:
    from src.engine.config import _is_test_file

    assert _is_test_file("tests/test_auth.py") is True


def test_bm25_weight_configuration(tmp_path: Path) -> None:
    from src.engine.config import Settings

    settings = Settings(
        bm25_content_weight=2.0,
        bm25_fqn_weight=0.5,
        bm25_path_weight=0.1,
    )
    assert settings.bm25_content_weight == 2.0
    assert settings.bm25_fqn_weight == 0.5
    assert settings.bm25_path_weight == 0.1


def test_bm25_search_with_fts5(tmp_path: Path) -> None:
    from src.engine.config import Settings
    from src.engine.graph import GraphDatabase
    from src.engine.search import BM25Search

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "test.db", settings)
    db.initialize()
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
            "content, language) VALUES (?, ?, ?, ?, ?, ?);",
            ("mod.foo", "a.py", 1, 2, "def foo(): return 42", "python"),
        )
        conn.execute(
            "INSERT INTO chunks_fts (rowid, content) VALUES (1, 'def foo(): return 42');",
        )
    bm25 = BM25Search(db, settings)
    results = bm25.search("foo", top_k=5)
    assert isinstance(results, list)


def test_relevance_threshold_filters_low_scores(tmp_path: Path) -> None:
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.graph import GraphDatabase
    from src.engine.search import HybridSearch

    settings = Settings(
        context_dir=tmp_path,
        relevance_threshold=0.5,
        relevance_gate=False,
    )
    db = GraphDatabase(tmp_path / "test.db", settings)
    db.initialize()
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
            "content, language) VALUES (?, ?, ?, ?, ?, ?);",
            ("mod.high", "a.py", 1, 2, "high score chunk", "python"),
        )
        conn.execute(
            "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
            "content, language) VALUES (?, ?, ?, ?, ?, ?);",
            ("mod.low", "b.py", 1, 2, "low score chunk", "python"),
        )
        conn.execute(
            "INSERT INTO chunks_fts (rowid, content) VALUES (1, 'high score chunk');",
        )
        conn.execute(
            "INSERT INTO chunks_fts (rowid, content) VALUES (2, 'low score chunk');",
        )

    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(
        tmp_path / "vectors.bin",
        tmp_path / "vectors.meta.json",
    )
    vector_index.load()
    hs = HybridSearch(db, vector_index, embedding_gen, settings)
    hs._bm25 = _MockBM25Search([(1, 10.0)])
    hs._vector_search = _MockVectorSearch([])
    results = hs.search("test", limit=10)["results"]
    for r in results:
        assert r["score"] >= 0.5, f"Result with score {r['score']} below threshold"
    assert len(results) == 1
    assert results[0]["chunk_id"] == 1


def test_relevance_threshold_zero_returns_all(tmp_path: Path) -> None:
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.graph import GraphDatabase
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path, relevance_threshold=0.0, relevance_gate=False)
    db = GraphDatabase(tmp_path / "test.db", settings)
    db.initialize()
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
            "content, language) VALUES (?, ?, ?, ?, ?, ?);",
            ("mod.a", "a.py", 1, 2, "chunk a", "python"),
        )
        conn.execute(
            "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
            "content, language) VALUES (?, ?, ?, ?, ?, ?);",
            ("mod.b", "b.py", 1, 2, "chunk b", "python"),
        )
        conn.execute("INSERT INTO chunks_fts (rowid, content) VALUES (1, 'chunk a');")
        conn.execute("INSERT INTO chunks_fts (rowid, content) VALUES (2, 'chunk b');")

    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(
        tmp_path / "vectors.bin",
        tmp_path / "vectors.meta.json",
    )
    vector_index.load()
    hs = HybridSearch(db, vector_index, embedding_gen, settings)
    hs._bm25 = _MockBM25Search([(1, 5.0), (2, 1.0)])
    hs._vector_search = _MockVectorSearch([])
    results = hs.search("test", limit=10)["results"]
    assert len(results) == 2


def test_relevance_threshold_clamping(tmp_path: Path) -> None:
    from src.engine.config import Settings

    settings = Settings(
        context_dir=tmp_path,
        relevance_threshold=1.5,
    )
    assert settings.relevance_threshold == 1.0

    settings2 = Settings(
        context_dir=tmp_path,
        relevance_threshold=-0.5,
    )
    assert settings2.relevance_threshold == 0.0


def test_below_threshold_field_present(tmp_path: Path) -> None:
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.graph import GraphDatabase
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path, relevance_threshold=0.3, relevance_gate=False)
    db = GraphDatabase(tmp_path / "test.db", settings)
    db.initialize()
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
            "content, language) VALUES (?, ?, ?, ?, ?, ?);",
            ("mod.a", "a.py", 1, 2, "chunk a", "python"),
        )
        conn.execute("INSERT INTO chunks_fts (rowid, content) VALUES (1, 'chunk a');")

    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(
        tmp_path / "vectors.bin",
        tmp_path / "vectors.meta.json",
    )
    vector_index.load()
    hs = HybridSearch(db, vector_index, embedding_gen, settings)
    hs._bm25 = _MockBM25Search([(1, 10.0)])
    hs._vector_search = _MockVectorSearch([])
    results = hs.search("test", limit=10)["results"]
    assert len(results) == 1
    assert "below_threshold" in results[0]
    assert "relevance_threshold_applied" in results[0]
    assert results[0]["relevance_threshold_applied"] is True


def test_vector_degraded_false_when_layer_healthy_but_no_vector_overlap(tmp_path: Path) -> None:
    """A healthy vector layer must not report degradation just because a
    query's vector leg returned no above-threshold matches.
    """
    import numpy as np

    from src.engine.config import Settings
    from src.engine.embeddings import EMBEDDING_DIM, EmbeddingGenerator, VectorIndex
    from src.engine.graph import GraphDatabase, IndexMetadataStore
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path, relevance_threshold=0.0, relevance_gate=False)
    db = GraphDatabase(tmp_path / "test.db", settings)
    db.initialize()
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
            "content, language) VALUES (?, ?, ?, ?, ?, ?);",
            ("mod.a", "a.py", 1, 2, "chunk a", "python"),
        )
        conn.execute("INSERT INTO chunks_fts (rowid, content) VALUES (1, 'chunk a');")

    meta = IndexMetadataStore(db)
    meta.set("vector_model_available", "true")
    meta.set("vector_model_loaded", "true")

    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(
        tmp_path / "vectors.bin",
        tmp_path / "vectors.meta.json",
    )
    vector_index.load()
    vector_index.add(
        1, np.ones(EMBEDDING_DIM, dtype=np.float32), {"file_path": "a.py", "fqn": "mod.a"}
    )

    hs = HybridSearch(db, vector_index, embedding_gen, settings)
    hs._bm25 = _MockBM25Search([(1, 10.0)])
    hs._vector_search = _MockVectorSearch([])
    results = hs.search("test", limit=10)["results"]
    assert len(results) == 1
    assert results[0]["vector_degraded"] is False


def test_vector_degraded_true_when_index_unpopulated(tmp_path: Path) -> None:
    """An unpopulated vector index is genuinely unavailable, so the
    BM25-only fallback must still report degradation.
    """
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.graph import GraphDatabase, IndexMetadataStore
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path, relevance_threshold=0.0, relevance_gate=False)
    db = GraphDatabase(tmp_path / "test.db", settings)
    db.initialize()
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
            "content, language) VALUES (?, ?, ?, ?, ?, ?);",
            ("mod.a", "a.py", 1, 2, "chunk a", "python"),
        )
        conn.execute("INSERT INTO chunks_fts (rowid, content) VALUES (1, 'chunk a');")

    meta = IndexMetadataStore(db)
    meta.set("vector_model_available", "true")
    meta.set("vector_model_loaded", "true")

    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(
        tmp_path / "vectors.bin",
        tmp_path / "vectors.meta.json",
    )
    vector_index.load()

    hs = HybridSearch(db, vector_index, embedding_gen, settings)
    hs._bm25 = _MockBM25Search([(1, 10.0)])
    hs._vector_search = _MockVectorSearch([])
    results = hs.search("test", limit=10)["results"]
    assert len(results) == 1
    assert results[0]["vector_degraded"] is True


@pytest.mark.benchmark
def test_bm25_fts5_memory_constant(tmp_path: Path) -> None:
    import tracemalloc

    from src.engine.config import Settings
    from src.engine.graph import GraphDatabase
    from src.engine.search import BM25Search

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "test.db", settings)
    db.initialize()

    with db.write_transaction() as conn:
        conn.executemany(
            "INSERT INTO code_chunks "
            "(fqn, file_path, line_start, line_end, content, language, is_definition) "
            "VALUES (?, ?, ?, ?, ?, ?, ?);",
            [
                (
                    f"mod.f{i}",
                    f"f{i}.py",
                    1,
                    2,
                    f"def func_{i}(): return {i}",
                    "python",
                    1,
                )
                for i in range(500)
            ],
        )
        conn.executemany(
            "INSERT INTO chunks_fts (rowid, content) VALUES (?, ?);",
            [(i + 1, f"def func_{i}(): return {i}") for i in range(500)],
        )

    bm25 = BM25Search(db, settings)
    tracemalloc.start()
    before, _peak = tracemalloc.get_traced_memory()
    for _ in range(10):
        bm25.search("func", top_k=10)
    after, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    memory_growth = after - before
    assert memory_growth < 50_000, (
        f"FTS5 BM25 should not load corpus into memory, "
        f"but grew {memory_growth} bytes (limit: 50KB)"
    )


def test_apply_file_coherence_dedups_one_result_per_file(tmp_path: Path) -> None:
    """File-first grouping keeps only the best chunk per file."""
    from src.engine.config import Settings
    from src.engine.graph import GraphDatabase
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "dedup.db", settings)
    db.initialize()

    # Three chunks from the same file, one from another file.
    rows = [
        (
            "migration.sql::0",
            "db/migration/V1__init_schema.sql",
            1,
            5,
            "CREATE TABLE articles (id INTEGER PRIMARY KEY);",
        ),
        (
            "migration.sql::1",
            "db/migration/V1__init_schema.sql",
            7,
            12,
            "CREATE INDEX idx_articles ON articles(id);",
        ),
        (
            "migration.sql::2",
            "db/migration/V1__init_schema.sql",
            14,
            20,
            "INSERT INTO articles VALUES (1);",
        ),
        ("mod.other", "other.py", 1, 3, "def helper(): pass"),
    ]
    with db.write_transaction() as conn:
        for fqn, path, ls, le, content in rows:
            conn.execute(
                "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
                "content, language, is_definition, chunk_type, chunk_node_type) "
                "VALUES (?, ?, ?, ?, ?, 'sql', 0, 'raw_text', 'raw_text');",
                (fqn, path, ls, le, content),
            )

    hs = HybridSearch(db, None, None, settings)
    results = [
        {"file_path": r[1], "line_start": r[2], "score": float(i)} for i, r in enumerate(rows)
    ]
    deduped = hs._apply_file_coherence(results)

    paths = [r["file_path"] for r in deduped]
    assert len(deduped) == 2, f"Expected one result per file, got {paths}"
    assert len(set(paths)) == len(paths), f"file_path must be unique: {paths}"

    migration = [r for r in deduped if "V1__init_schema.sql" in r["file_path"]]
    assert len(migration) == 1
    assert migration[0]["file_matches"] == 3
    # best chunk retained: highest raw score from the migration file
    assert migration[0]["line_start"] == 14

    # file score = max + coherence_bonus * log2(1 + n)
    assert migration[0]["score"] > 2.0


def _mixed_db(tmp_path: Path) -> object:
    """Corpus mixing code, resource (SQL), and boilerplate (field) chunks.

    Each chunk also gets a matching FTS5 row so a real BM25 search can run.
    """
    from src.engine.config import Settings
    from src.engine.graph import GraphDatabase

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "mixed.db", settings)
    db.initialize()
    rows = [
        (1, "m.token", "t.py", "def issue_token(): pass", "python", "ast", "function"),
        (2, "m.art", "a.py", "def list_articles(): pass", "python", "ast", "function"),
        (3, "m.favorite", "fav.py", "def remove_favorite(): pass", "python", "ast", "function"),
        (
            4,
            "mig.sql::0",
            "db/migration/V1__schema.sql",
            "CREATE TABLE articles (id INT);",
            "sql",
            "resource",
            "raw_text",
        ),
        (5, "m.field", "f.py", "self.id = 1", "python", "ast", "field_declaration"),
    ]
    with db.write_transaction() as conn:
        for rid, fqn, path, content, lang, ctype, ntype in rows:
            conn.execute(
                "INSERT INTO code_chunks (id, fqn, file_path, line_start, line_end, "
                "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
                "VALUES (?, ?, ?, 1, 2, ?, ?, 1, ?, ?, ?);",
                (rid, fqn, path, content, lang, ctype, ntype, " ".join(content.split())),
            )
            conn.execute(
                "INSERT INTO chunks_fts (rowid, content) VALUES (?, ?);",
                (rid, content),
            )
    return db


def _hybrid_search(tmp_path: Path, **settings_kwargs: object):
    """A HybridSearch over :func:`_mixed_db` with a mocked vector arm."""
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path, **settings_kwargs)
    db = _mixed_db(tmp_path)
    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(tmp_path / "v.bin", tmp_path / "v.meta.json")
    vector_index.load()
    hs = HybridSearch(db, vector_index, embedding_gen, settings)
    hs._vector_search = _MockVectorSearch([])
    return hs


def _search_with_mocks(
    tmp_path: Path,
    bm25_results: list[tuple[int, float]],
    *,
    vector_results: list[tuple[int, float]] | None = None,
    limit: int = 5,
) -> dict[str, object]:
    """Run a real :meth:`HybridSearch.search` over :func:`_mixed_db`.

    Gate/threshold are disabled so the plumbing tests only exercise ranking and
    envelope shape, not the trust signals (covered elsewhere).
    """
    hs = _hybrid_search(tmp_path, relevance_gate=False, relevance_threshold=0.0)
    hs._bm25 = _MockBM25Search(bm25_results)
    hs._vector_search = _MockVectorSearch(vector_results or [])
    return hs.search("issue_token", limit=limit)


def test_chunk_rank_class_code() -> None:
    from src.engine.search import chunk_rank_class

    assert chunk_rank_class("ast", "function") == "code"
    assert chunk_rank_class(None, None) == "code"


def test_chunk_rank_class_resource() -> None:
    from src.engine.search import chunk_rank_class

    assert chunk_rank_class("resource", "raw_text") == "resource"


def test_chunk_rank_class_boilerplate() -> None:
    from src.engine.search import chunk_rank_class

    assert chunk_rank_class("ast", "field_declaration") == "boilerplate"


def test_class_weights_deboost_resource_and_boilerplate(tmp_path: Path) -> None:
    from src.engine.config import Settings
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path)
    hs = HybridSearch(_mixed_db(tmp_path), None, None, settings)
    weights = hs._class_weights(resource_intent=False)
    assert weights["code"] == 1.0
    assert weights["resource"] == settings.resource_deboost
    assert weights["boilerplate"] == settings.boilerplate_deboost
    assert weights["resource"] < weights["boilerplate"] < 1.0


def test_class_weights_resource_intent_lifts_resource(tmp_path: Path) -> None:
    from src.engine.config import Settings
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path)
    hs = HybridSearch(_mixed_db(tmp_path), None, None, settings)
    weights = hs._class_weights(resource_intent=True)
    assert weights["resource"] == 1.0


def test_class_weights_enforce_min_lift_separation(tmp_path: Path) -> None:
    from src.engine.config import Settings
    from src.engine.search import HybridSearch

    settings = Settings(
        context_dir=tmp_path,
        resource_deboost=0.98,
        min_lift=0.05,
    )
    hs = HybridSearch(_mixed_db(tmp_path), None, None, settings)
    weights = hs._class_weights(resource_intent=False)
    # A de-boost weight too close to 1.0 must be capped DOWN to keep the
    # guaranteed separation from the code class (which stays at 1.0).
    assert weights["resource"] == 1.0 - 0.05
    assert 1.0 - weights["resource"] >= settings.min_lift


def test_resource_intent_detected(tmp_path: Path) -> None:
    from src.engine.config import Settings
    from src.engine.search import HybridSearch

    hs = HybridSearch(_mixed_db(tmp_path), None, None, Settings(context_dir=tmp_path))
    assert hs._resource_intent("how are migrations ordered") is True
    assert hs._resource_intent("does this project handle sql") is True
    assert hs._resource_intent("create slug from article") is False


def test_exact_precheck_annotation() -> None:
    from src.engine.search import exact_precheck

    p = exact_precheck("@Transactional readOnly = true")
    assert p is not None
    assert p["annotations"] == ["Transactional"]


def test_exact_precheck_quoted_literal() -> None:
    from src.engine.search import exact_precheck

    p = exact_precheck('setToken "abc123"')
    assert p is not None
    assert "abc123" in p["quotes"]


def test_exact_precheck_identifier() -> None:
    from src.engine.search import exact_precheck

    p = exact_precheck("setToken")
    assert p is not None
    assert p["identifier"] == "setToken"


def test_exact_precheck_plain_word_is_none() -> None:
    from src.engine.search import exact_precheck

    assert exact_precheck("pagination") is None


def test_exact_precheck_prose_does_not_misfire() -> None:
    from src.engine.search import exact_precheck

    # Prose merely mentioning a symbol among other words has no exact form.
    assert exact_precheck("the setToken method returns") is None


def test_query_exact_ids_returns_set(tmp_path: Path) -> None:
    from src.engine.config import Settings
    from src.engine.search import HybridSearch

    hs = HybridSearch(_mixed_db(tmp_path), None, None, Settings(context_dir=tmp_path))
    p = {"annotations": ["Transactional"], "quotes": [], "identifier": "token"}
    ids = hs._query_exact_ids(p)
    assert isinstance(ids, set)


def test_score_sources_present_on_results(tmp_path: Path) -> None:
    """Every result carries a full score_sources breakdown."""
    env = _search_with_mocks(tmp_path, [(1, 10.0), (2, 5.0)])
    results = env["results"]
    assert results, "mock BM25 hits must surface results"
    for r in results:
        ss = r["score_sources"]
        assert {"bm25", "vector", "fused", "weights", "reranked"} <= set(ss)
        assert set(ss["weights"]) == {"code", "boilerplate", "resource"}


def test_lexical_only_reports_zero_vector(tmp_path: Path) -> None:
    """A lexical-only hit (vector arm empty) reports vector 0.0 in score_sources."""
    env = _search_with_mocks(tmp_path, [(1, 10.0)], vector_results=[])
    assert env["results"]
    for r in env["results"]:
        assert r["score_sources"]["vector"] == 0.0


def test_score_breakdown_disabled_omits_score_sources(tmp_path: Path) -> None:
    """CODE_SEARCH_SCORE_BREAKDOWN=off omits the breakdown key."""
    hs = _hybrid_search(
        tmp_path,
        relevance_gate=False,
        relevance_threshold=0.0,
        score_breakdown=False,
    )
    hs._bm25 = _MockBM25Search([(1, 10.0)])
    envelope = hs.search("issue_token", limit=5)
    results = envelope["results"]
    assert results
    for r in results:
        assert "score_sources" not in r


def test_total_matches_uncapped_accurate(tmp_path: Path) -> None:
    """Pre-clamp total_matches is accurate for a capped query."""
    env = _search_with_mocks(
        tmp_path,
        [(1, 10.0), (2, 9.0), (3, 8.0), (4, 7.0)],
        limit=1,
    )
    assert env["total_matches"] == 4
    assert env["truncated"] is True
    assert len(env["results"]) == 1


def test_truncated_false_when_under_limit(tmp_path: Path) -> None:
    """A query under the display limit reports truncated False."""
    env = _search_with_mocks(tmp_path, [(1, 10.0)], limit=10)
    assert env["truncated"] is False
    assert env["total_matches"] >= len(env["results"])


class _TrackingVectorSearch:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def search(self, _query: str = "", **_kwargs: object) -> list:
        self._calls.append("vector")
        return []


def test_pattern_query_skips_vector_arm(tmp_path: Path) -> None:
    """Annotation queries defer the vector arm and never touch it."""
    calls: list[str] = []
    hs = _hybrid_search(tmp_path, relevance_gate=False)
    hs._vector_search = _TrackingVectorSearch(calls)
    hs.search("@Transactional readOnly = true", limit=5)
    assert calls == [], "vector arm must be skipped for annotation queries"


def test_no_model_never_runs_vector(tmp_path: Path) -> None:
    """--no-model skips the vector arm entirely."""
    from src.engine.config import Settings
    from src.engine.search import HybridSearch

    calls: list[str] = []
    settings = Settings(context_dir=tmp_path, relevance_gate=False)
    hs = HybridSearch(_mixed_db(tmp_path), None, None, settings, no_model=True)
    hs._vector_search = _TrackingVectorSearch(calls)
    hs.search("issue_token", limit=5)
    assert calls == [], "no-model must skip vector arm"


def test_quoted_literal_skips_vector_arm(tmp_path: Path) -> None:
    """Quoted-literal queries defer the vector arm as well."""
    calls: list[str] = []
    hs = _hybrid_search(tmp_path, relevance_gate=False)
    hs._vector_search = _TrackingVectorSearch(calls)
    hs.search('token "abc123"', limit=5)
    assert calls == []


def _stem_rescue_db(tmp_path: Path) -> object:
    """Controlled corpus for the file-stem rescue.

    ``state.ts`` defines ``StateManager`` (the symbol resolves exactly) and a
    second ``state-store.ts`` chunk row shares the symbol's FQN so the rescue
    must surface both files deterministically. ``checkout.py``
    defines the real ``Order`` symbol while ``order.py`` only defines
    ``OrderService`` — the name-sharing non-defining file must never be
    rescued.
    """
    from src.engine.config import Settings
    from src.engine.graph import GraphDatabase

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "stem.db", settings)
    db.initialize()
    chunks = [
        (
            1,
            "src/state.ts::StateManager",
            "src/state.ts",
            "class StateManager { capture() {} }",
            "typescript",
            1,
            "ast",
            "class_declaration",
        ),
        (
            2,
            "src/state-store.ts::StateManager",
            "src/state-store.ts",
            "class StateManager { push() {} }",
            "typescript",
            1,
            "ast",
            "class_declaration",
        ),
        (
            3,
            "src/checkout.py::Order",
            "src/checkout.py",
            "class Order: pass",
            "python",
            1,
            "ast",
            "class_definition",
        ),
        (
            4,
            "src/order.py::OrderService",
            "src/order.py",
            "class OrderService: pass",
            "python",
            1,
            "ast",
            "class_definition",
        ),
    ]
    symbols = [
        (1, "src/state.ts::StateManager", "StateManager", "class", "src/state.ts", "typescript"),
        (2, "src/checkout.py::Order", "Order", "class", "src/checkout.py", "python"),
        (3, "src/order.py::OrderService", "OrderService", "class", "src/order.py", "python"),
    ]
    with db.write_transaction() as conn:
        for cid, fqn, path, content, lang, isdef, ctype, ntype in chunks:
            conn.execute(
                "INSERT INTO code_chunks (id, fqn, file_path, line_start, line_end, "
                "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
                "VALUES (?, ?, ?, 1, 2, ?, ?, ?, ?, ?, ?);",
                (cid, fqn, path, content, lang, isdef, ctype, ntype, " ".join(content.split())),
            )
            conn.execute("INSERT INTO chunks_fts (rowid, content) VALUES (?, ?);", (cid, content))
        for sid, fqn, name, kind, path, lang in symbols:
            conn.execute(
                "INSERT INTO symbols (id, fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, 1, 2, 0, 4, ?);",
                (sid, fqn, name, kind, path, lang),
            )
    return db


def _stem_rescue_search(tmp_path: Path):
    """A HybridSearch over :func:`_stem_rescue_db` with zero lexical/vector hits.

    No chunk matches the query by content, so the only way a definition
    surfaces is through the file-stem rescue.
    """
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path, relevance_gate=False, relevance_threshold=0.0)
    db = _stem_rescue_db(tmp_path)
    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(tmp_path / "sv.bin", tmp_path / "sv.meta.json")
    vector_index.load()
    hs = HybridSearch(db, vector_index, embedding_gen, settings)
    hs._bm25 = _MockBM25Search([])
    hs._vector_search = _MockVectorSearch([])
    return hs


def test_us1_stem_rescue_surfaces_definition_with_tier(tmp_path: Path) -> None:
    """A bare symbol query surfaces its state.ts definition with stem_match."""
    hs = _stem_rescue_search(tmp_path)
    results = hs.search("StateManager", limit=5)["results"]
    assert results, "rescue must inject the definition even with zero lexical hits"
    state = [r for r in results if "state.ts" in r["file_path"]]
    assert state, "state.ts definition must surface"
    assert (state[0].get("score_sources") or {}).get("rescue") == {
        "tier": "stem_match",
        "boost": 1.5,
    }


def test_us1_stem_rescue_stem_related_tier(tmp_path: Path) -> None:
    """A state-*.ts file whose stem starts with the symbol stem is stem_related."""
    hs = _stem_rescue_search(tmp_path)
    results = hs.search("StateManager", limit=5)["results"]
    store = [r for r in results if "state-store.ts" in r["file_path"]]
    assert store, "state-store.ts must surface via the stem_related tier"
    assert (store[0].get("score_sources") or {}).get("rescue") == {
        "tier": "stem_related",
        "boost": 1.0,
    }


def test_us1_stem_rescue_case_insensitive_stem(tmp_path: Path) -> None:
    """File-stem matching is case-insensitive: STATE.ts rescues StateManager."""
    hs = _stem_rescue_search(tmp_path)
    hs._db = _stem_rescue_db_case_variant(tmp_path)
    results = hs.search("StateManager", limit=5)["results"]
    state = [r for r in results if "STATE.ts" in r["file_path"]]
    assert state, "uppercase file stem must still rescue the definition"


def test_us1_stem_rescue_does_not_fire_on_name_sharing_non_definition(
    tmp_path: Path,
) -> None:
    """order.py shares the ``order`` name but defines no ``Order``."""
    hs = _stem_rescue_search(tmp_path)
    results = hs.search("Order", limit=5)["results"]
    order = [r for r in results if "order.py" in r["file_path"]]
    assert order == [], "name-sharing non-defining file must not be rescued"


def test_us1_stem_rescue_multi_file_deterministic(tmp_path: Path) -> None:
    """Both matching state files surface, deterministically ordered."""
    hs = _stem_rescue_search(tmp_path)
    first = hs.search("StateManager", limit=5)["results"]
    second = hs.search("StateManager", limit=5)["results"]
    paths = [r["file_path"] for r in first]
    assert [r["file_path"] for r in second] == paths, "ordering must be deterministic"
    assert any("state.ts" in p for p in paths)
    assert any("state-store.ts" in p for p in paths)


def _stem_rescue_db_case_variant(tmp_path: Path) -> object:
    """Like :func:`_stem_rescue_db` but the defining file stem is upper-case."""
    from src.engine.config import Settings
    from src.engine.graph import GraphDatabase

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "stem_case.db", settings)
    db.initialize()
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO code_chunks (id, fqn, file_path, line_start, line_end, "
            "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
            "VALUES (?, ?, ?, 1, 2, ?, ?, 1, ?, ?, ?);",
            (
                1,
                "src/STATE.ts::StateManager",
                "src/STATE.ts",
                "class StateManager { capture() {} }",
                "typescript",
                "ast",
                "class_declaration",
                "class StateManager capture",
            ),
        )
        conn.execute(
            "INSERT INTO chunks_fts (rowid, content) VALUES (1, ?);", ("class StateManager",)
        )
        conn.execute(
            "INSERT INTO symbols (id, fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, 1, 2, 0, 4, ?);",
            (
                1,
                "src/STATE.ts::StateManager",
                "StateManager",
                "class",
                "src/STATE.ts",
                "typescript",
            ),
        )
    return db


def _path_boost_db(tmp_path: Path) -> object:
    """Controlled corpus for the NL path boost.

    ``services/auth_service.py`` matches the query keywords ``authentication``
    (via the ``auth`` prefix) and ``service``; the ``core/`` decoys share no
    path signal, so only the auth chunk is boosted.
    """
    from src.engine.config import Settings
    from src.engine.graph import GraphDatabase

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "path.db", settings)
    db.initialize()
    rows = [
        (
            1,
            "services/auth_service.py::AuthService",
            "services/auth_service.py",
            "def process(): pass",
            "python",
        ),
        (2, "core/user.py::UserService", "core/user.py", "def process(): pass", "python"),
        (3, "core/order.py::OrderService", "core/order.py", "def process(): pass", "python"),
        (4, "core/x.py::XHelper", "core/x.py", "def process(): pass", "python"),
    ]
    with db.write_transaction() as conn:
        for cid, fqn, path, content, lang in rows:
            conn.execute(
                "INSERT INTO code_chunks (id, fqn, file_path, line_start, line_end, "
                "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
                "VALUES (?, ?, ?, 1, 2, ?, ?, 1, 'ast', 'function', ?);",
                (cid, fqn, path, content, lang, " ".join(content.split())),
            )
            conn.execute("INSERT INTO chunks_fts (rowid, content) VALUES (?, ?);", (cid, content))
    return db


def _path_boost_search(tmp_path: Path, bm25_results: list[tuple[int, float]]):
    """A HybridSearch over :func:`_path_boost_db` with a mocked vector arm."""
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.search import HybridSearch

    settings = Settings(
        context_dir=tmp_path, relevance_gate=False, relevance_threshold=0.0, filter_stopwords=True
    )
    db = _path_boost_db(tmp_path)
    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(tmp_path / "pv.bin", tmp_path / "pv.meta.json")
    vector_index.load()
    hs = HybridSearch(db, vector_index, embedding_gen, settings)
    hs._bm25 = _MockBM25Search(bm25_results)
    hs._vector_search = _MockVectorSearch([])
    return hs


def test_us4_nl_path_boost_boosts_matching_file(tmp_path: Path) -> None:
    """The ``auth_service`` chunk outranks equal-content decoys because its
    file path matches the NL keywords."""
    hs = _path_boost_search(tmp_path, [(2, 10.0), (3, 9.0), (1, 8.0)])
    results = hs.search("authentication service", limit=5)["results"]
    assert results, "path-boosted chunk must surface"
    assert results[0]["file_path"].endswith("auth_service.py"), (
        "auth path match must lift the chunk above the decoys"
    )
    boost = results[0]["score_sources"]["path_boost"]
    assert isinstance(boost, float) and boost > 0.0
    for r in results[1:]:
        assert r["score_sources"]["path_boost"] is None


def test_us4_nl_path_boost_zero_when_no_keyword(tmp_path: Path) -> None:
    """No path-matching keyword means a zero boost on every chunk, so
    scores are identical to a query run without the pass."""
    hs = _path_boost_search(tmp_path, [(1, 10.0), (2, 9.0), (3, 8.0)])
    results = hs.search("process", limit=5)["results"]
    assert results
    for r in results:
        assert r["score_sources"]["path_boost"] is None


def test_us4_nl_path_boost_skipped_for_symbol_intent(tmp_path: Path) -> None:
    """Path boosting applies to NL queries only: a symbol-intent query must not boost by
    path even when the file stem would prefix-match the symbol stem."""
    hs = _stem_rescue_search(tmp_path)
    results = hs.search("StateManager", limit=5)["results"]
    assert results
    for r in results:
        assert r["score_sources"]["path_boost"] is None


def test_us4_nl_path_boost_short_stem_no_boost(tmp_path: Path) -> None:
    """A file stem shorter than ``CODE_SEARCH_STEM_MIN_PREFIX`` cannot
    prefix-match a keyword, so it gets no boost."""
    hs = _path_boost_search(tmp_path, [(4, 10.0), (1, 9.0), (2, 8.0), (3, 7.0)])
    results = hs.search("authentication service", limit=5)["results"]
    by_path = {r["file_path"]: r for r in results}
    assert "core/x.py" in by_path
    assert by_path["core/x.py"]["score_sources"]["path_boost"] is None
    assert by_path["services/auth_service.py"]["score_sources"]["path_boost"] > 0.0


def _path_gate_db(tmp_path: Path) -> object:
    """Corpus for the stem_min_prefix gating tests (both match sides).

    ``core/auth.py`` (stem ``auth``) prefix-matches the keyword
    ``authentication`` under a long-enough term; ``core/a.py`` (stem ``a``)
    would prefix-match too but its one-char term must stay gated.
    ``nl_boost_keywords_min`` defaults to 2.
    """
    from src.engine.config import Settings
    from src.engine.graph import GraphDatabase

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "pgate.db", settings)
    db.initialize()
    rows = [
        (1, "core/auth.py::AuthRouter", "core/auth.py", "def run(): pass", "python"),
        (2, "core/a.py::AHelper", "core/a.py", "def run(): pass", "python"),
        (3, "other/lib.py::Lib", "other/lib.py", "def run(): pass", "python"),
    ]
    with db.write_transaction() as conn:
        for cid, fqn, path, content, lang in rows:
            conn.execute(
                "INSERT INTO code_chunks (id, fqn, file_path, line_start, line_end, "
                "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
                "VALUES (?, ?, ?, 1, 2, ?, ?, 1, 'ast', 'function', ?);",
                (cid, fqn, path, content, lang, " ".join(content.split())),
            )
            conn.execute("INSERT INTO chunks_fts (rowid, content) VALUES (?, ?);", (cid, content))
    return db


def _path_gate_search(tmp_path: Path, bm25_results: list[tuple[int, float]]):
    """A HybridSearch over :func:`_path_gate_db` with a mocked vector arm.

    ``nl_boost_keywords_min`` is set to 1 so the pass still runs on
    single-keyword queries, isolating the two ``stem_min_prefix`` length gates
    from the keyword-count skip.
    """
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.search import HybridSearch

    settings = Settings(
        context_dir=tmp_path,
        relevance_gate=False,
        relevance_threshold=0.0,
        filter_stopwords=True,
        nl_boost_keywords_min=1,
    )
    db = _path_gate_db(tmp_path)
    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(tmp_path / "pg.bin", tmp_path / "pg.meta.json")
    vector_index.load()
    hs = HybridSearch(db, vector_index, embedding_gen, settings)
    hs._bm25 = _MockBM25Search(bm25_results)
    hs._vector_search = _MockVectorSearch([])
    return hs


def test_us4_nl_path_boost_gates_keyword_side_on_min_prefix(tmp_path: Path) -> None:
    """A query keyword shorter than ``stem_min_prefix`` never enters the
    eligible keyword set, so it cannot fire the boost even when a path term
    prefix-matches it (both sides gated)."""
    hs = _path_gate_search(tmp_path, [(1, 10.0), (2, 9.0), (3, 8.0)])
    results = hs.search("au", limit=5)["results"]
    assert results
    for r in results:
        assert r["score_sources"]["path_boost"] is None, (
            f"keyword 'au' ({hs._settings.stem_min_prefix} min) must not fire: {r['file_path']}"
        )


def test_us4_nl_path_boost_gates_path_term_side_on_min_prefix(tmp_path: Path) -> None:
    """A matched path term shorter than ``stem_min_prefix`` never fires the
    boost: ``core/a.py`` (stem ``a``) prefix-matches the keyword but its
    one-char term stays gated, while ``core/auth.py`` still fires."""
    hs = _path_gate_search(tmp_path, [(1, 10.0), (2, 9.0), (3, 8.0)])
    results = hs.search("authentication", limit=5)["results"]
    assert results
    for r in results:
        if r["file_path"].endswith("auth.py"):
            assert r["score_sources"]["path_boost"] > 0.0, (
                "a long term ('auth') prefix-matching the keyword must still fire"
            )
        else:
            assert r["score_sources"]["path_boost"] is None, (
                f"path term shorter than the minimum must not fire: {r['file_path']}"
            )


def test_us4_nl_path_boost_skipped_below_keywords_min(tmp_path: Path) -> None:
    """With fewer eligible keywords than ``nl_boost_keywords_min`` the path
    boost is skipped entirely, leaving scores identical to an unboosted run."""
    hs = _path_boost_search(tmp_path, [(1, 10.0), (2, 9.0), (3, 8.0)])
    results = hs.search("service", limit=5)["results"]
    assert results
    for r in results:
        assert r["score_sources"]["path_boost"] is None


def _embedded_db(tmp_path: Path) -> object:
    """Controlled corpus for the embedded-symbol pass.

    ``PaymentGateway`` is defined only in ``payment_gateway.py``; the decoy
    ``payment.py`` chunk is a plain BM25 hit with no symbol embedded in prose.
    """
    from src.engine.config import Settings
    from src.engine.graph import GraphDatabase

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "embedded.db", settings)
    db.initialize()
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO code_chunks (id, fqn, file_path, line_start, line_end, "
            "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
            "VALUES (?, ?, ?, 1, 2, ?, ?, 1, 'ast', 'class_definition', ?);",
            (
                1,
                "src/payment_gateway.py::PaymentGateway",
                "src/payment_gateway.py",
                "class PaymentGateway: pass",
                "python",
                "class PaymentGateway pass",
            ),
        )
        conn.execute(
            "INSERT INTO code_chunks (id, fqn, file_path, line_start, line_end, "
            "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
            "VALUES (?, ?, ?, 1, 2, ?, ?, 1, 'ast', 'function_definition', ?);",
            (
                2,
                "src/payment.py::PaymentProcessor",
                "src/payment.py",
                "def charge(): pass",
                "python",
                "def charge pass",
            ),
        )
        conn.execute(
            "INSERT INTO chunks_fts (rowid, content) VALUES (1, ?);", ("class PaymentGateway",)
        )
        conn.execute("INSERT INTO chunks_fts (rowid, content) VALUES (2, ?);", ("def charge",))
        conn.execute(
            "INSERT INTO symbols (id, fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, 1, 2, 0, 4, ?);",
            (
                1,
                "src/payment_gateway.py::PaymentGateway",
                "PaymentGateway",
                "class",
                "src/payment_gateway.py",
                "python",
            ),
        )
    return db


def _embedded_search(tmp_path: Path):
    """A HybridSearch over :func:`_embedded_db` with a mocked vector arm."""
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path, relevance_gate=False, relevance_threshold=0.0)
    db = _embedded_db(tmp_path)
    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(tmp_path / "eb.bin", tmp_path / "eb.meta.json")
    vector_index.load()
    hs = HybridSearch(db, vector_index, embedding_gen, settings)
    hs._bm25 = _MockBM25Search([(2, 5.0)])
    hs._vector_search = _MockVectorSearch([])
    return hs


def test_us5_embedded_symbols_extracts_only_definition_symbols(tmp_path: Path) -> None:
    """Only identifier-shaped tokens that resolve exactly are picked."""
    from src.engine.config import Settings
    from src.engine.language import embedded_symbols
    from src.engine.symbols import SymbolStore

    store = SymbolStore(_embedded_db(tmp_path), Settings(context_dir=tmp_path))
    assert embedded_symbols("the PaymentGateway integration is ready", store) == ["PaymentGateway"]
    assert embedded_symbols("the payment gateway integration", store) == []
    assert embedded_symbols("the PaymentGatewayX integration", store) == []


def test_us5_embedded_pass_pulls_definition_into_pool(tmp_path: Path) -> None:
    """A definition named only in prose surfaces even with zero lexical hits
    on its own content."""
    hs = _embedded_search(tmp_path)
    results = hs.search("the PaymentGateway integration", limit=5)["results"]
    gateway = [r for r in results if r["file_path"].endswith("payment_gateway.py")]
    assert gateway, "the prose-named definition must be pulled into the pool"
    evidence = gateway[0]["score_sources"]["embedded_symbol"]
    assert isinstance(evidence, dict)
    assert evidence["symbol"] == "PaymentGateway"
    assert evidence["boost"] > 0.0
    assert any(r["file_path"].endswith("payment.py") for r in results), (
        "the plain BM25 hit must also survive"
    )


def test_us5_embedded_pass_boost_value(tmp_path: Path) -> None:
    """The embedded boost is ``embedded_symbol_boost * pool_max``."""
    from src.engine.config import Settings
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path)
    hs = HybridSearch(_embedded_db(tmp_path), None, None, settings)
    fused = {99: 0.2}
    pool_max_before = max(fused.values())
    embedded, rescue = hs._embedded_symbol_pass("the PaymentGateway integration", fused)
    assert fused[99] == 0.2, "unrelated chunks are untouched"
    assert 1 in embedded
    assert embedded[1]["symbol"] == "PaymentGateway"
    assert embedded[1]["boost"] == pytest.approx(settings.embedded_symbol_boost * pool_max_before)
    assert fused[1] > 0.0
    assert 1 in rescue, "each embedded symbol also runs the US1 stem rescue"


def test_us5_embedded_pass_skipped_for_symbol_intent(tmp_path: Path) -> None:
    """A bare-identifier query takes the stem-rescue path and never runs the embedded
    pass, so no embedded_symbol evidence appears."""
    hs = _embedded_search(tmp_path)
    results = hs.search("PaymentGateway", limit=5)["results"]
    assert results
    for r in results:
        assert r["score_sources"]["embedded_symbol"] is None


def _path_class_db(tmp_path: Path) -> object:
    """Controlled corpus for the path-class classification."""
    from src.engine.config import Settings
    from src.engine.graph import GraphDatabase

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "class.db", settings)
    db.initialize()
    rows = [
        (
            1,
            "types/foo.d.ts::Foo",
            "types/foo.d.ts",
            "declare class Foo { bar(): void }",
            "typescript",
            1,
            "ast",
            "class_declaration",
        ),
        (
            2,
            "src/foo.ts::Foo",
            "src/foo.ts",
            "export class Foo { bar() {} }",
            "typescript",
            1,
            "ast",
            "class_declaration",
        ),
        (
            3,
            "pkg/__init__.py",
            "pkg/__init__.py",
            "from .mod import Foo",
            "python",
            0,
            "ast",
            "module",
        ),
    ]
    with db.write_transaction() as conn:
        for cid, fqn, path, content, lang, isdef, ctype, ntype in rows:
            conn.execute(
                "INSERT INTO code_chunks (id, fqn, file_path, line_start, line_end, "
                "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
                "VALUES (?, ?, ?, 1, 2, ?, ?, ?, ?, ?, ?);",
                (cid, fqn, path, content, lang, isdef, ctype, ntype, " ".join(content.split())),
            )
            conn.execute("INSERT INTO chunks_fts (rowid, content) VALUES (?, ?);", (cid, content))
    return db


def test_us3_alpha_default_symbol_intent(tmp_path: Path) -> None:
    """A symbol-intent query defaults alpha to ``alpha_symbol`` (0.3)."""
    hs = _stem_rescue_search(tmp_path)
    results = hs.search("StateManager", limit=5)["results"]
    assert results, "symbol query must surface the rescued definition"
    for r in results:
        assert r["score_sources"]["alpha"] == pytest.approx(hs._settings.alpha_symbol)


def test_us3_alpha_default_nl(tmp_path: Path) -> None:
    """A natural-language query keeps the balanced ``alpha_nl`` (0.5)."""
    hs = _hybrid_search(tmp_path, relevance_gate=False, relevance_threshold=0.0)
    hs._bm25 = _MockBM25Search([(1, 10.0), (2, 9.0)])
    hs._vector_search = _MockVectorSearch([])
    results = hs.search("how is token validation handled", limit=5)["results"]
    assert results, "NL query must surface results"
    for r in results:
        assert r["score_sources"]["alpha"] == pytest.approx(hs._settings.alpha_nl)


def test_mixed_intent_definition_stays_in_results_deterministic(tmp_path: Path) -> None:
    """A symbol embedded in prose (class name + natural phrase) is a mixed
    query: the embedded-symbol pass must keep the definition in the results
    (coherence) and the ordering must be identical across repeated runs."""
    hs = _embedded_search(tmp_path)
    query = "how does the PaymentGateway charge payments"
    first = hs.search(query, limit=5)["results"]
    second = hs.search(query, limit=5)["results"]
    assert first, "mixed-intent query must surface results"
    assert [r["chunk_id"] for r in first] == [r["chunk_id"] for r in second], (
        "ordering must be identical across repeated runs"
    )
    gateway = [r for r in first if r["file_path"].endswith("payment_gateway.py")]
    assert gateway, "the prose-named definition must stay in the results"
    for r in gateway:
        assert r["score_sources"]["embedded_symbol"] is not None


def test_us1_conceptual_query_deterministic_scores_and_order(tmp_path: Path) -> None:
    """Identical query + identical index state produce identical
    result ordering and scores across repeated runs (``-k deterministic``).

    The query rides the live vector arm (real model + populated index) fused
    with BM25 — determinism must hold through the full hybrid path.
    """
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.graph import GraphDatabase
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path, relevance_threshold=0.0, relevance_gate=False)
    db = GraphDatabase(tmp_path / "test.db", settings)
    db.initialize()
    with db.write_transaction() as conn:
        for i, content in enumerate(("token expiry guard", "login session window"), start=1):
            conn.execute(
                "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
                "content, language) VALUES (?, ?, ?, ?, ?, ?);",
                (f"mod.c{i}", f"c{i}.py", 1, 2, content, "python"),
            )
            conn.execute("INSERT INTO chunks_fts (rowid, content) VALUES (?, ?);", (i, content))

    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(tmp_path / "vectors.bin", tmp_path / "vectors.meta.json")
    vector_index.load()
    for i, content in enumerate(("token expiry guard", "login session window"), start=1):
        vec = embedding_gen.encode(content)
        assert vec is not None, "model must embed the synthetic chunk"
        vector_index.add(i, vec, {"file_path": f"c{i}.py", "fqn": f"mod.c{i}"})

    hs = HybridSearch(db, vector_index, embedding_gen, settings)
    query = "token expiry login session"
    first = hs.search(query, limit=10)["results"]
    second = hs.search(query, limit=10)["results"]
    assert first and second, "conceptual query must surface results"
    assert [r["chunk_id"] for r in first] == [r["chunk_id"] for r in second], (
        "ordering must be identical across repeated runs"
    )
    for a, b in zip(first, second, strict=True):
        assert a["score"] == pytest.approx(b["score"]), (
            f"score must be stable across repeated runs, got {a['score']} vs {b['score']}"
        )
        assert a["vector_score"] == pytest.approx(b["vector_score"])
        assert a["bm25_score"] == pytest.approx(b["bm25_score"])


def test_us3_alpha_explicit_clamped(tmp_path: Path) -> None:
    """Values outside ``[0, 1]`` clamp to the nearest bound."""
    hs = _stem_rescue_search(tmp_path)
    hi = hs.search("StateManager", limit=5, alpha=1.7)["results"]
    lo = hs.search("StateManager", limit=5, alpha=-0.4)["results"]
    assert hi and lo
    for r in hi:
        assert r["score_sources"]["alpha"] == pytest.approx(1.0)
    for r in lo:
        assert r["score_sources"]["alpha"] == pytest.approx(0.0)


def test_us3_resolve_alpha_override_wins_over_intent(tmp_path: Path) -> None:
    """An explicit alpha wins over intent and is clamped to ``[0, 1]``."""
    hs = _stem_rescue_search(tmp_path)
    assert hs._resolve_alpha(0.8) == pytest.approx(0.8)
    assert hs._resolve_alpha(1.9) == pytest.approx(1.0)
    assert hs._resolve_alpha(-0.2) == pytest.approx(0.0)


def test_us6_dts_classifier() -> None:
    from src.engine.config import _is_dts_file

    assert _is_dts_file("src/types/foo.d.ts") is True
    assert _is_dts_file("src/foo.ts") is False
    assert _is_dts_file("foo.d.ts") is True


def test_us6_barrel_classifier(tmp_path: Path) -> None:
    from src.engine.classification import PathClass

    db = _path_class_db(tmp_path)
    assert PathClass.is_barrel(db, "pkg/__init__.py") is True, (
        "a pure re-export __init__.py is a barrel"
    )
    assert PathClass.is_barrel(db, "src/foo.ts") is False
    assert PathClass.is_barrel(db, "types/foo.d.ts") is False


def test_us6_path_class_assigned_in_results(tmp_path: Path) -> None:
    """Results carry a path_class: dts/barrel demoted, plain code canonical."""
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path, relevance_gate=False, relevance_threshold=0.0)
    db = _path_class_db(tmp_path)
    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(tmp_path / "pc.bin", tmp_path / "pc.meta.json")
    vector_index.load()
    hs = HybridSearch(db, vector_index, embedding_gen, settings)
    hs._bm25 = _MockBM25Search([(1, 10.0), (2, 9.0), (3, 8.0)])
    hs._vector_search = _MockVectorSearch([])
    results = hs.search("Foo bar", limit=5)["results"]
    by_path = {r["file_path"]: r for r in results}
    assert by_path["types/foo.d.ts"]["path_class"] == "dts"
    assert by_path["src/foo.ts"]["path_class"] == "canonical"
    assert by_path["pkg/__init__.py"]["path_class"] == "barrel"
    assert by_path["types/foo.d.ts"]["score_sources"]["path_class"] == "dts"


def _alpha_rank_db(tmp_path: Path) -> object:
    """Corpus for the adaptive-alpha precision test.

    ``TokenValidator`` is defined in ``src/security/validators.py``, a file
    whose stem shares no prefix with the symbol stem, so the file-stem
    rescue stays silent and ranking is decided by the alpha blend alone. The
    ``SessionValidator`` chunk is the incidental semantic neighbour: the mocked
    vector arm ranks it above the exact definition.
    """
    from src.engine.config import Settings
    from src.engine.graph import GraphDatabase

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "alpha.db", settings)
    db.initialize()
    chunks = [
        (
            1,
            "src/security/validators.py::TokenValidator",
            "src/security/validators.py",
            "class TokenValidator: def validate(self): return True",
            "python",
        ),
        (
            2,
            "src/security/session.py::SessionValidator",
            "src/security/session.py",
            "def validate_user_session(): pass",
            "python",
        ),
    ]
    with db.write_transaction() as conn:
        for cid, fqn, path, content, lang in chunks:
            conn.execute(
                "INSERT INTO code_chunks (id, fqn, file_path, line_start, line_end, "
                "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
                "VALUES (?, ?, ?, 1, 2, ?, ?, 1, 'ast', 'class_definition', ?);",
                (cid, fqn, path, content, lang, " ".join(content.split())),
            )
            conn.execute("INSERT INTO chunks_fts (rowid, content) VALUES (?, ?);", (cid, content))
        conn.execute(
            "INSERT INTO symbols (id, fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, 1, 2, 0, 4, ?);",
            (
                1,
                "src/security/validators.py::TokenValidator",
                "TokenValidator",
                "class",
                "src/security/validators.py",
                "python",
            ),
        )
    return db


def _alpha_rank_search(tmp_path: Path):
    """A HybridSearch over :func:`_alpha_rank_db` whose mocked vector arm ranks
    the semantic neighbour (chunk 2) above the exact definition (chunk 1)."""
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.search import HybridSearch

    settings = Settings(
        context_dir=tmp_path,
        relevance_gate=False,
        relevance_threshold=0.0,
        exact_precheck_tags="off",
    )
    db = _alpha_rank_db(tmp_path)
    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(tmp_path / "ar.bin", tmp_path / "ar.meta.json")
    vector_index.load()
    hs = HybridSearch(db, vector_index, embedding_gen, settings)
    hs._bm25 = _MockBM25Search([(1, 10.0), (2, 9.0)])
    hs._vector_search = _MockVectorSearch([(2, 0.98), (1, 0.45)])
    return hs


def test_us3_symbol_intent_outranks_incidental_neighbor(tmp_path: Path) -> None:
    """The vector arm ranks the semantic neighbour above the
    exact definition, yet the adaptive-alpha symbol intent (alpha = alpha_symbol)
    re-ranks the exact definition to #1."""
    hs = _alpha_rank_search(tmp_path)
    results = hs.search("TokenValidator", limit=5)["results"]
    assert results, "symbol query must surface results"
    by_id = {r["chunk_id"]: r for r in results}
    assert 1 in by_id and 2 in by_id, "both the definition and the neighbour must surface"
    assert by_id[2]["vector_score"] > by_id[1]["vector_score"], (
        "premise: the vector arm ranks the neighbour above the exact definition"
    )
    assert results[0]["chunk_id"] == 1, (
        f"exact definition must rank #1 under symbol intent, got {[r['chunk_id'] for r in results]}"
    )
    assert results[0]["file_path"].endswith("validators.py")
    for r in results:
        assert r["score_sources"]["alpha"] == pytest.approx(hs._settings.alpha_symbol)


def _crowd_db(tmp_path: Path) -> object:
    """Corpus for the generic-keyword crowding guard.

    ``core/architecture.py`` is the genuinely relevant result: it is the
    strongest content match and its path shares no keyword with the query.
    ``service_*.py`` are unrelated files that all match the generic keyword
    ``service`` through their file stem — exactly the crowding case the guard
    must contain.
    """
    from src.engine.config import Settings
    from src.engine.graph import GraphDatabase

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "crowd.db", settings)
    db.initialize()
    rows = [
        (
            1,
            "core/architecture.py::Planner",
            "core/architecture.py",
            "def design_architecture(): pass",
            "python",
        ),
        (2, "service_a.py::ServiceA", "service_a.py", "def run_a(): pass", "python"),
        (3, "service_b.py::ServiceB", "service_b.py", "def run_b(): pass", "python"),
        (4, "service_c.py::ServiceC", "service_c.py", "def run_c(): pass", "python"),
    ]
    with db.write_transaction() as conn:
        for cid, fqn, path, content, lang in rows:
            conn.execute(
                "INSERT INTO code_chunks (id, fqn, file_path, line_start, line_end, "
                "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
                "VALUES (?, ?, ?, 1, 2, ?, ?, 1, 'ast', 'function', ?);",
                (cid, fqn, path, content, lang, " ".join(content.split())),
            )
            conn.execute("INSERT INTO chunks_fts (rowid, content) VALUES (?, ?);", (cid, content))
    return db


def _crowd_search(tmp_path: Path):
    """A HybridSearch over :func:`_crowd_db` with mocked lexical/vector arms.

    The genuinely relevant ``architecture`` chunk is the strongest content
    match; the ``service_*`` files are weak content matches whose only signal
    is their generic shared stem.
    """
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.search import HybridSearch

    settings = Settings(
        context_dir=tmp_path,
        relevance_gate=False,
        relevance_threshold=0.0,
        filter_stopwords=True,
    )
    db = _crowd_db(tmp_path)
    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(tmp_path / "cw.bin", tmp_path / "cw.meta.json")
    vector_index.load()
    hs = HybridSearch(db, vector_index, embedding_gen, settings)
    hs._bm25 = _MockBM25Search([(1, 10.0), (2, 2.0), (3, 2.0), (4, 2.0)])
    hs._vector_search = _MockVectorSearch([])
    return hs


def test_us4_generic_keyword_crowding_guard(tmp_path: Path) -> None:
    """A generic keyword shared by many unrelated files must not lift
    those files above genuinely more relevant results. The ``pool_max`` cap on
    the additive boost (scaled by the fraction of query keywords matched) keeps
    every path-boosted file at or below the top relevant score."""
    hs = _crowd_search(tmp_path)
    results = hs.search("how is the service layer structured", limit=5)["results"]
    assert results, "query must surface results"
    assert results[0]["file_path"].endswith("architecture.py"), (
        "path-boosted generic-keyword files must not crowd out the relevant "
        f"result: {[r['file_path'] for r in results]}"
    )
    top_score = results[0]["score"]
    for r in results[1:]:
        if r["score_sources"]["path_boost"] is not None:
            assert r["score"] <= top_score, (
                f"path-boosted {r['file_path']} must stay at or below the top "
                f"relevant score ({top_score}), got {r['score']}"
            )


def test_us5_embedded_symbols_ignore_capitalized_common_words(tmp_path: Path) -> None:
    """Capitalized common words that are not actual
    symbols never fire the embedded-symbol pass — recognition requires an exact
    ``SymbolStore`` resolution."""
    from src.engine.config import Settings
    from src.engine.language import embedded_symbols
    from src.engine.symbols import SymbolStore

    store = SymbolStore(_embedded_db(tmp_path), Settings(context_dir=tmp_path))
    assert embedded_symbols("The PaymentGateway implementation is ready", store) == [
        "PaymentGateway"
    ]
    assert embedded_symbols("This PaymentGateway handles retries", store) == ["PaymentGateway"]
    assert embedded_symbols("The payment gateway integration is ready", store) == []
    assert embedded_symbols("The This These", store) == []
    assert embedded_symbols("THIS IS THE WAY", store) == []


def test_us5_embedded_pass_ignores_capitalized_common_words_in_search(tmp_path: Path) -> None:
    """The full search pass boosts only the exact symbol: ``The`` never appears
    in the embedded-symbol evidence even though it is capitalized."""
    hs = _embedded_search(tmp_path)
    results = hs.search("The PaymentGateway integration is ready", limit=5)["results"]
    gateway = [r for r in results if r["file_path"].endswith("payment_gateway.py")]
    assert gateway, "the prose-named definition must surface"
    evidence = gateway[0]["score_sources"]["embedded_symbol"]
    assert evidence["symbol"] == "PaymentGateway", "only the exact symbol may fire"


def test_definition_lookup_sql_and_pool_max_helper_once() -> None:
    """The shared definition lookup lives in exactly one place: the SQL
    skeleton and the ``_pool_max`` fallback it relies on appear exactly once
    each in search.py, so future passes reuse the helper instead of forking
    the query or the boost cap."""
    source = (Path(__file__).resolve().parents[2] / "src" / "engine" / "search.py").read_text()
    skeleton = "SELECT id, file_path FROM code_chunks"
    assert source.count(skeleton) == 1, "the definition-lookup SQL must appear once"
    assert (
        source.count("WHERE is_definition = 1 AND (fqn = ? OR fqn LIKE ? OR fqn LIKE ?);") == 1
    ), "the definition-chunk predicate must appear once"
    assert source.count("def _pool_max") == 1, "the shared pool-max helper must appear once"


def _project_results(results: list[dict[str, object]]) -> list[tuple[object, ...]]:
    def key_fields(result: dict[str, object]) -> tuple[object, ...]:
        return (
            result["file_path"],
            result.get("line_start", result.get("line_no", 0)),
            result.get("fqn", result.get("name")),
            result.get("score"),
            result.get("confidence_band", result.get("confidence")),
        )

    return [key_fields(r) for r in results]


@pytest.mark.integration
def test_ranked_search_is_deterministic(indexed_robustness: dict[str, object]) -> None:
    hs = indexed_robustness["search"]
    first = hs.search("comment moderation policy")["results"]
    second = hs.search("comment moderation policy")["results"]
    assert _project_results(first) == _project_results(second)


@pytest.mark.integration
def test_exhaustive_mode_is_deterministic(indexed_robustness: dict[str, object]) -> None:
    hs = indexed_robustness["search"]
    first = hs.search("PasswordEncoder", mode="exhaustive")["results"]
    second = hs.search("PasswordEncoder", mode="exhaustive")["results"]
    assert len(first) == 7  # whole-file rg oracle, not chunk subset
    assert _project_results(first) == _project_results(second)


@pytest.mark.integration
def test_enumerate_mode_is_deterministic(indexed_robustness: dict[str, object]) -> None:
    hs = indexed_robustness["search"]
    first = hs.search("list all controllers", mode="enumerate")
    second = hs.search("list all controllers", mode="enumerate")
    assert first["total_count"] == second["total_count"] == 8
    assert _project_results(first["results"]) == _project_results(second["results"])


@pytest.mark.integration
def test_completeness_labels_are_deterministic(indexed_robustness: dict[str, object]) -> None:
    hs = indexed_robustness["search"]
    queries = [
        ("hasRole", "ranked"),
        ("PasswordEncoder", "exhaustive"),
        ("list all controllers", "enumerate"),
    ]
    for query, mode in queries:
        first = hs.search(query, mode=mode)
        second = hs.search(query, mode=mode)
        assert first["mode"] == second["mode"]
        assert first.get("confidence") == second.get("confidence")
        assert first.get("explanation") == second.get("explanation")
        if mode == "ranked":
            assert "complete" not in first, "ranked envelopes must omit complete (FR-009)"
            assert first["best_effort"] is True
            assert first["total_matches"] == second["total_matches"]
        else:
            assert first["complete"] == second["complete"]
            assert first["total_count"] == second["total_count"]


def _exhaustive_db(tmp_path: Path) -> object:
    """Controlled corpus for exhaustive-mode line counting.

    One file whose content holds 12 distinct matching lines plus a second
    file with no matches, so the scan has something to count past the cap.
    The files exist on disk because exhaustive mode scans the indexed files
    from local disk.
    """
    from src.engine.config import Settings
    from src.engine.graph import GraphDatabase

    gen_py = tmp_path / "gen.py"
    gen_py.write_text("\n".join(f"token {i} abc" for i in range(12)) + "\n")
    helper_py = tmp_path / "helper.py"
    helper_py.write_text("def helper(): pass\n")

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "exhaustive.db", settings)
    db.initialize()
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
            "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
            "VALUES (?, ?, 1, 12, ?, 'python', 1, 'ast', 'function', 'token abc');",
            ("mod.gen", str(gen_py), "\n".join(f"token {i} abc" for i in range(12))),
        )
        conn.execute(
            "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
            "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
            "VALUES (?, ?, 1, 1, ?, 'python', 0, 'ast', 'module', 'def helper(): pass');",
            ("mod.helper", str(helper_py), "def helper(): pass"),
        )
        conn.execute(
            "INSERT INTO file_checksums (file_path, checksum) VALUES (?, ''), (?, '');",
            (str(gen_py), str(helper_py)),
        )
    return db


def _exhaustive_search(tmp_path: Path, **settings_kwargs: object) -> object:
    from src.engine.config import Settings
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path, **settings_kwargs)  # type: ignore[arg-type]
    hs = HybridSearch(_exhaustive_db(tmp_path), None, None, settings, no_model=True)
    return hs


def test_exhaustive_truncation_is_honest(tmp_path: Path) -> None:
    """A hit set past the display cap reports every occurrence in
    ``total_count`` and labels itself truncated/incomplete instead of
    pretending the returned slice is the whole set."""
    hs = _exhaustive_search(tmp_path, exhaustive_max_lines=5)
    env = hs.search("token", limit=5, mode="exhaustive")
    assert env["mode"] == "exhaustive"
    assert env["total_count"] == 12
    assert len(env["results"]) == 5
    assert env["truncated"] is True
    assert env["complete"] is False


def test_exhaustive_within_cap_is_complete(tmp_path: Path) -> None:
    """When the hit set fits under the cap, complete stays True and the
    count is exact."""
    hs = _exhaustive_search(tmp_path, exhaustive_max_lines=100)
    env = hs.search("token", limit=50, mode="exhaustive")
    assert env["total_count"] == 12
    assert len(env["results"]) == 12
    assert env["truncated"] is False
    assert env["complete"] is True


def _enumeration_db(tmp_path: Path) -> object:
    """Controlled corpus for enumerate-mode semantics."""
    from src.engine.config import Settings
    from src.engine.graph import GraphDatabase

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "enumeration.db", settings)
    db.initialize()
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
            "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
            "VALUES (?, ?, 1, 5, ?, 'java', 1, 'ast', 'class_declaration', ?);",
            (
                "mod.ArticleController",
                "src/ArticleController.java",
                "class ArticleController {}",
                "article controller",
            ),
        )
        conn.execute(
            "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
            "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
            "VALUES (?, ?, 1, 30, ?, 'docker', 0, 'resource', 'raw_text', ?);",
            (
                "docker-compose.yml::1",
                "docker-compose.yml",
                "services:\n  app:\n    build: .",
                "docker compose services",
            ),
        )
        conn.execute(
            "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
            "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
            "VALUES (?, ?, 1, 5, ?, 'make', 0, 'resource', 'raw_text', ?);",
            ("Makefile::1", "Makefile", "build:\n\techo hi", "make build"),
        )
    return db


def _enumeration_search(tmp_path: Path) -> object:
    from src.engine.config import Settings
    from src.engine.search import HybridSearch

    settings = Settings(context_dir=tmp_path)
    hs = HybridSearch(_enumeration_db(tmp_path), None, None, settings, no_model=True)
    return hs


def test_enumerate_resource_kinds_by_filename(tmp_path: Path) -> None:
    """Resource kinds ('all docker-compose files') enumerate indexed
    resource chunks by filename pattern instead of FQN/node-type."""
    hs = _enumeration_search(tmp_path)
    env = hs.search("all compose files", limit=50, mode="enumerate")
    assert env["mode"] == "enumerate"
    assert env["total_count"] == 1
    assert env["complete"] is True
    assert env["results"][0]["file_path"] == "docker-compose.yml"


def test_enumerate_makefiles_by_filename(tmp_path: Path) -> None:
    """'all makefiles' returns the Makefile resource chunk."""
    hs = _enumeration_search(tmp_path)
    env = hs.search("all makefiles", limit=50, mode="enumerate")
    assert env["total_count"] == 1
    assert env["results"][0]["file_path"] == "Makefile"


def test_enumerate_reports_unparseable_files(tmp_path: Path) -> None:
    """A corpus with a structurally unparseable file returns complete
    False plus the excluded paths."""
    hs = _enumeration_search(tmp_path)
    with hs._db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO file_checksums (file_path, checksum, parse_failed) VALUES (?, ?, 1);",
            ("src/BrokenFile.java", "deadbeef"),
        )
    env = hs.search("all controllers", limit=50, mode="enumerate")
    assert env["mode"] == "enumerate"
    assert env["total_count"] == 1
    assert env["complete"] is False
    assert env["excluded"] == ["src/BrokenFile.java"]


def test_enumerate_total_count_exact_under_truncation(tmp_path: Path) -> None:
    """An enumerated set exceeding *limit* reports the exact set size in
    ``total_count`` (COUNT) while ``truncated``/``complete`` stay honest."""
    hs = _enumeration_search(tmp_path)
    with hs._db.write_transaction() as conn:
        for i in range(6):
            conn.execute(
                "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
                "content, language, is_definition, chunk_type, chunk_node_type, subwords) "
                "VALUES (?, ?, 1, 5, ?, 'java', 1, 'ast', 'class_declaration', ?);",
                (
                    f"mod.Extra{i}Controller",
                    f"src/Extra{i}Controller.java",
                    "class ExtraController {}",
                    "extra controller",
                ),
            )
    env = hs.search("all controllers", limit=5, mode="enumerate")
    assert env["mode"] == "enumerate"
    assert env["total_count"] == 7
    assert len(env["results"]) == 5
    assert env["truncated"] is True
    assert env["complete"] is False


def test_ranked_envelope_omits_complete(tmp_path: Path) -> None:
    """Ranked envelopes carry best_effort instead of complete so ranked
    results are never presented as a complete enumeration."""
    hs = _exhaustive_search(tmp_path)
    env = hs.search("token", limit=5)
    assert "complete" not in env
    assert env["best_effort"] is True
    assert env["total_matches"] >= 1


def test_enumeration_intent_auto_selects_enumerate(tmp_path: Path) -> None:
    """'list all controllers' / 'all controllers' phrasing auto-selects
    enumerate mode without an explicit ``mode`` argument."""
    hs = _enumeration_search(tmp_path)
    for query in ("list all controllers", "all controllers"):
        env = hs.search(query)
        assert env["mode"] == "enumerate", f"{query!r} should auto-select enumerate"
        assert env["total_count"] == 1


def test_enumeration_intent_rejects_mixed_phrasing(tmp_path: Path) -> None:
    """A query that merely starts with an intent word but carries extra
    search content is not hijacked into enumerate mode."""
    hs = _enumeration_search(tmp_path)
    env = hs.search("list all controllers and password encoding")
    assert env["mode"] != "enumerate"


@pytest.mark.integration
def test_enumeration_intent_on_real_fixture(indexed_robustness: dict[str, object]) -> None:
    """The 'all controllers' phrasing resolves to the complete 8-class
    set via auto-detection; a non-enumeration query stays ranked."""
    hs = indexed_robustness["search"]
    for query in ("list all controllers", "all controllers"):
        env = hs.search(query)
        assert env["mode"] == "enumerate", f"{query!r} should auto-select enumerate"
        assert env["total_count"] == 8
    ranked = hs.search("how is password encoding handled during registration")
    assert ranked["mode"] != "enumerate"


def test_gibberish_returns_no_match_envelope(tmp_path: Path) -> None:
    """A gibberish query returns the explicit no-match envelope
    — ``results: []``, ``no_match: true``, ``confidence: none``, and the
    rescue-tier explanation — never ten arbitrary chunks."""
    hs = _gate_search(tmp_path)
    env = hs.search("wqrble token", limit=10)
    assert env.get("no_match") is True, "gibberish must flag no_match"
    assert env["results"] == []
    assert env["confidence"] == "none"
    assert env["explanation"]["reason"] == "no_match"
    assert "rescued_tiers" in env["explanation"]


def test_ranked_results_carry_low_confidence_tag(tmp_path: Path) -> None:
    """Every ranked result whose confidence band is low carries
    ``low_confidence: true`` so the consumer knows to verify it."""
    hs = _gate_search(tmp_path)
    hs._vector_search = _MockVectorSearch([(6, 0.9)])
    env = hs.search("pagination", limit=10)
    assert env["results"], "expected ranked results"
    for r in env["results"]:
        assert "low_confidence" in r
        assert r["low_confidence"] == r["borderline"], (
            "low_confidence must track the borderline/low band"
        )


def test_no_match_envelope_shape_direct() -> None:
    """The no-match envelope reports ``no_match: true`` with the reason and
    the tiers tried."""
    from src.engine.config import Settings
    from src.engine.search import HybridSearch

    settings = Settings()
    hs = HybridSearch(None, None, None, settings)  # type: ignore[arg-type]
    env = hs._no_match_envelope(True, ["lexical"], "some query", "code_focused")
    assert env["no_match"] is True
    assert env["results"] == []
    assert env["explanation"]["reason"] == "no_match"
    assert env["explanation"]["rescued_tiers"] == ["lexical"]
    assert env["content"] == "code_focused"


def test_ranked_score_floor_default_matches_relevance_threshold() -> None:
    """The ranked score floor default is aligned with the existing
    relevance threshold so a score exactly at the floor is low-confidence,
    never no-match."""
    from src.engine.config import Settings

    settings = Settings()
    assert settings.ranked_score_floor == settings.relevance_threshold


def test_model_status_stamped_on_ranked_envelope(tmp_path: Path) -> None:
    """Every ranked envelope carries a measured ``model_status``
    and ``degraded_reason`` — warm/cold when the vector layer is usable,
    disabled otherwise."""
    hs = _trust_gate_search(tmp_path, coverage=0.9, no_model=True)
    env = hs.search("token valid", limit=10)
    assert env["mode"] == "ranked"
    assert env.get("model_status") == "disabled", env.get("model_status")
    assert env.get("degraded_reason") == "model_disabled", env.get("degraded_reason")


def test_model_status_warm_on_healthy_vector_layer(tmp_path: Path) -> None:
    """A request whose vector layer is healthy reports ``warm`` and a
    null degraded reason."""

    hs = _gate_search(tmp_path)
    hs._vector_search = _MockVectorSearch([(6, 0.9)])
    env = hs.search("pagination", limit=10)
    assert env["mode"] == "ranked"
    assert "model_status" in env
    assert "degraded_reason" in env
