"""Integration tests: out-of-domain queries return a meaningful empty result.

Runs against the real ``HybridSearch.search`` path over the synthetic
``trust_defects`` fixture. Pins the coverage + vector-floor gate behavior.
"""

from __future__ import annotations

from typing import Any


class TestOutOfDomainGate:
    def test_e1_websocket_returns_empty(self, indexed_trust_defects: dict[str, Any]) -> None:
        """E1 ``websocket real time notifications`` is an absent concept on the
        fixture — must return ``[]``, never a confident false positive."""
        results = indexed_trust_defects["search"].search(
            "websocket real time notifications", limit=10
        )["results"]
        assert results == []

    def test_e2_stopwords_still_empty(self, indexed_trust_defects: dict[str, Any]) -> None:
        """E2 stopword-only query stays rejected (a prior-win control)."""
        results = indexed_trust_defects["search"].search("the and of with", limit=10)["results"]
        assert results == []

    def test_s3_in_domain_still_returns_results(
        self, indexed_trust_defects: dict[str, Any]
    ) -> None:
        """S3 in-domain query must still surface the relevant file (the ≥81%
        ≥1-relevant baseline is preserved — the gate only rejects genuinely
        out-of-domain queries)."""
        results = indexed_trust_defects["search"].search(
            "check if the article title or slug is already taken before saving",
            limit=10,
        )["results"]
        assert len(results) >= 1
        assert any("ArticleService" in r["file_path"] for r in results)

    def test_f1_typo_still_accepted(self, indexed_trust_defects: dict[str, Any]) -> None:
        """F1 typo ``jwt tokne genration`` must still resolve to TokenService
        (a prior-win control): typos have low exact coverage but clear the
        vector floor via the JWT vocabulary in ``TokenService``."""
        results = indexed_trust_defects["search"].search("jwt tokne genration", limit=10)["results"]
        assert len(results) >= 1
        assert any("TokenService" in r["file_path"] for r in results)

    def test_l1_exact_identifier_still_first(self, indexed_trust_defects: dict[str, Any]) -> None:
        """L1 ``TokenService`` keeps ranking the exact file #1 (fixture control
        — enrichment must not regress the exact-identifier query)."""
        results = indexed_trust_defects["search"].search("TokenService", limit=5)["results"]
        assert len(results) >= 1
        assert "TokenService" in results[0]["file_path"]

    def test_validate_jwt_token_control(self, indexed_trust_defects: dict[str, Any]) -> None:
        """The enriched JWT vocabulary in ``TokenService`` must not create a
        confident false positive for an absent concept, while a JWT-adjacent
        query still finds TokenService."""
        results = indexed_trust_defects["search"].search("validate JWT token", limit=5)["results"]
        assert len(results) >= 1
        assert any("TokenService" in r["file_path"] for r in results)
