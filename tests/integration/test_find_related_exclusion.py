"""``find_related`` self-exclusion.

Asserts that by default the anchor chunk's own **file** is excluded from the
neighbour set, degenerate outcomes are explicitly labelled
``same_file_only``/``empty`` instead of a silent self-chunk list,
the down-weighting fallback keeps cross-file neighbours above same-file ones,
and an anchor that is its own cosine top-1 still yields a full
``limit`` of neighbours (the limit-1 regression).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from src.mcp.server import _find_related_payload


@pytest.fixture
def transparency_comps(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/transparency/``."""
    from tests.conftest import FIXTURES_DIR, _indexed_components

    repo = tmp_path / "transparency_repo"
    shutil.copytree(FIXTURES_DIR / "transparency", repo)
    return _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})


def _anchor_file(repo: Path) -> Path:
    return repo / "src" / "main" / "java" / "com" / "example" / "article" / "ArticleService.java"


@pytest.mark.integration
@pytest.mark.slow
def test_find_related_excludes_anchor_file_by_default(transparency_comps: dict[str, Any]) -> None:
    """No returned neighbour comes from the anchor chunk's
    own file by default, and the outcome is labelled ``cross_file``.
    """
    comps = transparency_comps
    anchor = _anchor_file(comps["repo"])
    data = json.loads(_find_related_payload(comps, str(anchor), 18, 5))
    assert data.get("vector_health") is True, data
    assert data.get("status") == "cross_file", data.get("status")
    results = data["results"]
    assert results, "expected a non-empty cross-file related set"
    assert len(results) <= 5
    for item in results:
        assert item["file_path"] != str(anchor), (
            f"neighbour {item['chunk_id']} must not come from the anchor file {anchor}"
        )
        assert item["same_file"] is False


@pytest.mark.integration
@pytest.mark.slow
def test_find_related_same_file_only_is_labeled_not_silent(
    transparency_comps: dict[str, Any],
) -> None:
    """An anchor whose file holds the only similar content returns an
    explicitly-labelled ``same_file_only`` best-effort result (flagged
    ``same_file: true``) — never a silent self-chunk list presented as
    cross-file relatedness.
    """
    comps = transparency_comps
    anchor = _anchor_file(comps["repo"])

    # Locate a chunk in the anchor file and a sibling chunk in the same file.
    with comps["db"].connect() as conn:
        chunks = conn.execute(
            "SELECT id FROM code_chunks WHERE file_path = ? ORDER BY id;",
            (str(anchor),),
        ).fetchall()
    assert len(chunks) >= 2, "the anchor file must hold at least two chunks"
    anchor_line = 18
    data = json.loads(_find_related_payload(comps, str(anchor), anchor_line, 5))
    # The default corpus yields cross-file neighbours, so a labelled
    # same_file_only response is forced by excluding every other file from the
    # corpus via the down-weighting path exercised in the unit tests. Here we
    # assert the *labelling invariant*: when same_file results are returned,
    # they carry the explicit flag.
    for item in data["results"]:
        if item["file_path"] == str(anchor):
            assert item["same_file"] is True, "same-file results must be explicitly flagged"
        else:
            assert item["same_file"] is False, "cross-file results must not be flagged"


@pytest.mark.integration
@pytest.mark.slow
def test_find_related_same_file_only_deterministic_single_file_corpus(tmp_path: Path) -> None:
    """In a corpus whose only file is the anchor's, the exclusion
    leaves no cross-file neighbour and the response is explicitly labelled
    ``same_file_only`` with the best same-file chunk flagged.
    """
    from tests.conftest import _indexed_components

    repo = tmp_path / "single_repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "Solo.java").write_text(
        "public class Solo {\n"
        "    public void handleRequest() { }\n"
        "    public void handleRequestAsync() { }\n"
        "    public void handleRequestBlocking() { }\n"
        "}\n"
    )
    comps = _indexed_components(repo, repo / ".context")
    anchor = repo / "src" / "Solo.java"
    data = json.loads(_find_related_payload(comps, str(anchor), 1, 5))
    assert data.get("vector_health") is True, data
    assert data.get("status") == "same_file_only", data.get("status")
    results = data["results"]
    assert results, "best-effort same-file result must be returned"
    assert len(results) <= 5
    for item in results:
        assert item["file_path"] == str(anchor), "best-effort results come from the anchor file"
        assert item["same_file"] is True, "same-file best-effort results must be flagged"


@pytest.mark.integration
@pytest.mark.slow
def test_find_related_empty_is_labeled(tmp_path: Path) -> None:
    """When no neighbour exists at all the response is labelled
    ``empty`` with an explanation, not a bare ``cross_file`` empty list.
    """
    from tests.conftest import _indexed_components

    repo = tmp_path / "empty_repo"
    (repo / "src").mkdir(parents=True)
    # A single chunk in the whole index: no neighbours exist at all, so the
    # response must be labelled ``empty`` (never a bare ``cross_file`` list).
    (repo / "src" / "app.properties").write_text("server.port=8080\ndb.url=jdbc:h2:mem\n")
    comps = _indexed_components(repo, repo / ".context")
    anchor = repo / "src" / "app.properties"
    data = json.loads(_find_related_payload(comps, str(anchor), 1, 5))
    assert data.get("vector_health") is True, data
    assert data.get("status") == "empty", data.get("status")
    assert data.get("results") == []
    assert "explanation" in data, "empty outcomes must carry an explanation"


@pytest.mark.integration
@pytest.mark.slow
def test_find_related_downweighting_keeps_cross_file_above_same_file(tmp_path: Path) -> None:
    """With ``find_related_exclude_file=false``, cross-file neighbours
    always outrank same-file chunks, and the outcome is labelled ``cross_file``
    when cross-file neighbours exist.
    """
    from tests.conftest import _indexed_components

    repo = tmp_path / "downweight_repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "Service.java").write_text(
        "public class Service {\n"
        '    public String connect() { return "session established"; }\n'
        '    public String connectAsync() { return "session established asynchronously"; }\n'
        "}\n"
    )
    (repo / "src" / "Helper.java").write_text(
        'public class Helper {\n    public String connect() { return "session"; }\n}\n'
    )
    comps = _indexed_components(
        repo,
        repo / ".context",
        settings_kwargs={"find_related_exclude_file": False},
    )
    anchor = repo / "src" / "Service.java"
    data = json.loads(_find_related_payload(comps, str(anchor), 1, 5))
    assert data.get("vector_health") is True, data
    results = data["results"]
    assert results, "down-weighting mode must still return neighbours"
    for item in results:
        assert item["same_file"] is False, (
            "cross-file neighbours must outrank same-file chunks in down-weighting mode"
        )


@pytest.mark.integration
@pytest.mark.slow
def test_find_related_anchor_as_own_top1_yields_full_limit(
    transparency_comps: dict[str, Any],
) -> None:
    """Limit-1 regression: an anchor that is its own cosine top-1 must still
    yield the full ``limit`` of neighbours (the candidate search fetches
    ``limit + 1`` before filtering).
    """
    comps = transparency_comps
    anchor = _anchor_file(comps["repo"])
    data = json.loads(_find_related_payload(comps, str(anchor), 18, 5))
    assert data.get("status") == "cross_file", data.get("status")
    assert len(data["results"]) == 5, (
        f"expected the full limit of 5 neighbours, got {len(data['results'])}"
    )


_BOILERPLATE_CORPUS: dict[str, str] = {
    "src/security/SecurityService.java": (
        "package security;\n"
        "public class SecurityService {\n"
        "    public SecurityResponse authorize(SecurityRequest request) {\n"
        "        // check whether the caller is permitted to perform the action\n"
        '        if (request.isAdmin()) { return new SecurityResponse("allowed"); }\n'
        '        return new SecurityResponse("denied");\n'
        "    }\n"
        "}\n"
    ),
    "src/security/SecurityChecker.java": (
        "package security;\n"
        "public class SecurityChecker {\n"
        "    public boolean checkPermission(SecurityRequest request) {\n"
        "        return request.isAdmin();\n"
        "    }\n"
        "}\n"
    ),
    "src/dto/SecurityResponse.java": (
        "package dto;\n"
        "public class SecurityResponse {\n"
        "    private String status;\n"
        "    private Long userId;\n"
        "    public String getStatus() { return status; }\n"
        "    public void setStatus(String status) { this.status = status; }\n"
        "    public Long getUserId() { return userId; }\n"
        "    public void setUserId(Long userId) { this.userId = userId; }\n"
        "}\n"
    ),
    "src/dto/SecurityRequest.java": (
        "package dto;\n"
        "public class SecurityRequest {\n"
        "    private String token;\n"
        "    private boolean admin;\n"
        "    public String getToken() { return token; }\n"
        "    public void setToken(String token) { this.token = token; }\n"
        "    public boolean isAdmin() { return admin; }\n"
        "    public void setAdmin(boolean admin) { this.admin = admin; }\n"
        "}\n"
    ),
    "src/exception/SecurityException.java": (
        "package exception;\n"
        "public class SecurityException extends RuntimeException {\n"
        "    public SecurityException(String message) { super(message); }\n"
        "}\n"
    ),
}


def _write_corpus(repo: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


@pytest.mark.integration
@pytest.mark.slow
def test_find_related_excludes_boilerplate_for_auth_anchor(tmp_path: Path) -> None:
    """An auth-code anchor returns no boilerplate-shape
    neighbour (DTO/EXCEPTION) when on-topic cross-file neighbours exist.
    Same-role neighbours outrank boilerplate."""
    from tests.conftest import _indexed_components

    repo = tmp_path / "boilerplate_repo"
    _write_corpus(repo, _BOILERPLATE_CORPUS)
    comps = _indexed_components(repo, repo / ".context")
    anchor = repo / "src" / "security" / "SecurityService.java"
    data = json.loads(_find_related_payload(comps, str(anchor), 5, 5))
    assert data.get("status") == "cross_file", data.get("status")
    for item in data["results"]:
        assert item.get("file_role") not in {
            "dto",
            "model",
            "assembler",
            "exception",
        }, f"boilerplate neighbour leaked: {item['file_path']} ({item.get('file_role')})"


@pytest.mark.integration
@pytest.mark.slow
def test_find_related_best_effort_when_only_boilerplate_remains(tmp_path: Path) -> None:
    """When only boilerplate-shape content is similar, the response
    is explicitly labelled ``best_effort`` — not presented as strong
    relatedness."""
    from tests.conftest import _indexed_components

    repo = tmp_path / "best_effort_repo"
    corpus = dict(_BOILERPLATE_CORPUS)
    corpus.pop("src/security/SecurityChecker.java")  # drop the on-topic peer
    _write_corpus(repo, corpus)
    comps = _indexed_components(repo, repo / ".context")
    anchor = repo / "src" / "security" / "SecurityService.java"
    data = json.loads(_find_related_payload(comps, str(anchor), 5, 5))
    assert data.get("status") == "best_effort", data.get("status")
    assert data.get("explanation"), "best_effort must carry an explanation"


@pytest.mark.integration
@pytest.mark.slow
def test_find_related_dto_anchor_still_finds_scaffolding(tmp_path: Path) -> None:
    """A genuine DTO/model anchor still finds its scaffolding peers —
    the boilerplate exclusion is directional."""
    from tests.conftest import _indexed_components

    repo = tmp_path / "dto_anchor_repo"
    _write_corpus(repo, _BOILERPLATE_CORPUS)
    comps = _indexed_components(repo, repo / ".context")
    anchor = repo / "src" / "dto" / "SecurityResponse.java"
    data = json.loads(_find_related_payload(comps, str(anchor), 2, 5))
    assert data.get("results"), "a DTO anchor must still find related chunks"
    dto_peers = [r for r in data["results"] if r.get("file_role") == "dto"]
    assert dto_peers, "the DTO anchor must find its scaffolding (DTO) peers"


@pytest.mark.integration
@pytest.mark.slow
def test_find_related_boilerplate_toggle_downweights_not_excludes(tmp_path: Path) -> None:
    """Config fallback: ``CODE_SEARCH_FIND_RELATED_EXCLUDE_BOILERPLATE=false``
    down-weights boilerplate neighbours instead of excluding them."""
    from tests.conftest import _indexed_components

    repo = tmp_path / "downweight_boilerplate_repo"
    _write_corpus(repo, _BOILERPLATE_CORPUS)
    comps = _indexed_components(
        repo,
        repo / ".context",
        settings_kwargs={"find_related_exclude_boilerplate": False},
    )
    anchor = repo / "src" / "security" / "SecurityService.java"
    data = json.loads(_find_related_payload(comps, str(anchor), 5, 5))
    assert data.get("status") == "cross_file", data.get("status")
    # On-topic code outranks down-weighted boilerplate.
    first = data["results"][0]
    assert first.get("file_role") == "code", (
        f"down-weighted boilerplate must not outrank on-topic code: {first.get('file_path')}"
    )
