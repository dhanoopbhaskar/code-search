"""Integration tests for search accuracy at the serving/engine level.

Pins the observable contracts:

- A rebuilt index surfaces the visible "index changed — restart required"
  envelope instead of a silent empty/stale result.
- Root-level ``*.sh`` classifies as ``infra`` and a literal dependency string
  still ranks its lockfile/config file.
- The login-validation paraphrase surfaces the ``@Valid`` DTO / annotation
  chunk.
- Exhaustive counts report true occurrences with per-line metadata matching
  the grep oracle on multi-occurrence lines.
- Abstract config-scent queries rank the config resource above build-metadata
  noise.
- A code-scoped config-shaped query appends a visible config hint; a genuinely
  code-only query stays hint-free.
- The documented interface states the code-scope limitation, docs rank-only
  relevance, and the docs revisit trigger.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tests.conftest import _indexed_components


def _write(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _feature020_repo(tmp_path: Path) -> Path:
    """A synthetic corpus reproducing the search-accuracy failure signatures."""
    repo = tmp_path / "feature020_repo"
    _write(repo, "wait-for-it.sh", '#!/bin/sh\nwhile ! nc -z "$1" "$2"; do sleep 1; done\n')
    _write(
        repo,
        "package-lock.json",
        '{\n  "name": "svc",\n  "lockfileVersion": 3,\n  "packages": {\n'
        '    "": {"dependencies": {"mysql": {"resolved": "jdbc:mysql://db:3306/articles"}}}\n'
        "  }\n}\n",
    )
    _write(
        repo,
        "pom.xml",
        "<project>\n  <artifactId>svc</artifactId>\n"
        "  <dependencies>\n    <dependency><groupId>org.springframework</groupId>"
        "<artifactId>spring-boot-starter-web</artifactId></dependency>\n  </dependencies>\n"
        "</project>\n",
    )
    _write(
        repo,
        "feed.py",
        "def get_feed_for_user(user_id: int) -> list[str]:\n"
        '    """Return the feed articles for a user."""\n'
        "    return ['article-' + str(user_id)]\n",
    )
    _write(
        repo,
        "src/main/java/com/example/auth/UserAuthenticate.java",
        "package com.example.auth;\n\n"
        "import javax.validation.Valid;\n"
        "import javax.validation.constraints.NotBlank;\n\n"
        "public class UserAuthenticate {\n"
        "    @Valid\n"
        "    @NotBlank\n"
        "    private String username;\n\n"
        "    @NotBlank\n"
        "    private String password;\n\n"
        "    public String getUsername() { return username; }\n"
        "    public String getPassword() { return password; }\n"
        "}\n",
    )
    _write(
        repo,
        "src/main/java/com/example/auth/CheckSecurity.java",
        "package com.example.auth;\n\n"
        "import java.lang.annotation.ElementType;\n"
        "import java.lang.annotation.Retention;\n"
        "import java.lang.annotation.RetentionPolicy;\n"
        "import java.lang.annotation.Target;\n\n"
        "@Target(ElementType.METHOD)\n"
        "@Retention(RetentionPolicy.RUNTIME)\n"
        "public @interface CheckSecurity {\n"
        "}\n",
    )
    _write(
        repo,
        "src/main/java/com/example/auth/AuthorizationConfig.java",
        "package com.example.auth;\n\n"
        "import org.springframework.context.annotation.Bean;\n"
        "import org.springframework.context.annotation.Configuration;\n"
        "import org.springframework.security.config.annotation.web.builders.HttpSecurity;\n"
        "import org.springframework.security.config.annotation.web.configuration"
        ".EnableWebSecurity;\n\n"
        "@Configuration\n"
        "@EnableWebSecurity\n"
        "public class AuthorizationConfig {\n"
        "    @Bean\n"
        "    public HttpSecurity security(HttpSecurity http) throws Exception {\n"
        "        return http.authorizeHttpRequests(auth -> auth.anyRequest().permitAll());\n"
        "    }\n"
        "}\n",
    )
    _write(
        repo,
        "src/main/java/com/example/auth/AuthController.java",
        "package com.example.auth;\n\n"
        "import org.springframework.web.bind.annotation.PostMapping;\n"
        "import org.springframework.web.bind.annotation.RequestBody;\n"
        "import org.springframework.web.bind.annotation.RestController;\n\n"
        "@RestController\n"
        "public class AuthController {\n"
        "    @CheckSecurity\n"
        '    @PostMapping("/login")\n'
        "    public String login(@RequestBody UserAuthenticate authenticate) {\n"
        '        return "token";\n'
        "    }\n"
        "}\n",
    )
    _write(
        repo,
        "src/main/java/com/example/article/ArticleService.java",
        "package com.example.article;\n\n"
        "public class ArticleService {\n"
        "    public Article save(Article article) {\n"
        "        return article;\n"
        "    }\n"
        "}\n",
    )
    _write(
        repo,
        "src/main/resources/application.properties",
        "server.port=8080\nspring.datasource.url=jdbc:mysql://localhost:3306/articles\n",
    )
    _write(
        repo,
        "src/main/resources/db/migration/V1__create_articles_table.sql",
        "CREATE TABLE articles (\n"
        "    id BIGINT PRIMARY KEY,\n"
        "    title VARCHAR(255) NOT NULL\n"
        ");\n",
    )
    _write(
        repo,
        "src/main/java/com/example/util/Slugifier.java",
        "package com.example.util;\n\n"
        "public class Slugifier {\n"
        "    public String slugify(String title) { return slugify(title); }\n"
        "}\n",
    )
    return repo


def _indexed_feature(tmp_path: Path) -> dict[str, Any]:
    repo = _feature020_repo(tmp_path)
    return _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})


def _reranked(search: Any, query: str, limit: int = 10) -> list[dict[str, Any]]:
    from src.engine.reranking import Reranker

    envelope = search.search(query, limit=limit, content="all")
    reranker = Reranker(search._db, settings=search._settings)  # type: ignore[arg-type]
    return reranker.rerank(envelope["results"], query_terms=None, query=query)


# --- Tooling-file deprioritization --------------------------------------------


def test_file_role_root_shell_script_is_infra() -> None:
    """A root-level ``*.sh`` file classifies ``infra``."""
    from src.engine.classification import FileRole, file_role

    assert file_role("wait-for-it.sh") == FileRole.INFRA
    assert file_role("scripts/deploy.sh") == FileRole.INFRA


def test_feed_query_not_polluted_by_shell_script(tmp_path: Path) -> None:
    """``wait-for-it.sh`` is not top-1 for the feed query."""
    comps = _indexed_feature(tmp_path)
    results = comps["search"].search("feed for a user", limit=10)["results"]
    assert results, "expected results for the feed query"
    top = Path(results[0]["file_path"]).name
    assert top == "feed.py", f"shell script outranks on-topic code: {top}"
    names = [Path(r["file_path"]).name for r in results]
    assert "feed.py" in names[:3], f"on-topic code missing from top ranks: {names[:3]}"


def test_literal_dependency_string_ranks_lockfile(tmp_path: Path) -> None:
    """A literal ``jdbc:mysql`` query still ranks the matching lockfile/config
    content (strong evidence is respected)."""
    comps = _indexed_feature(tmp_path)
    envelope = comps["search"].search("jdbc:mysql", limit=10, content="all")
    assert envelope["mode"] == "ranked"
    names = [Path(r["file_path"]).name for r in envelope["results"]]
    assert "package-lock.json" in names or "application.properties" in names, (
        f"literal evidence suppressed: {names}"
    )


# --- Permission/validation paraphrase -----------------------------------------


def test_login_validation_paraphrase_surfaces_dto(tmp_path: Path) -> None:
    """The "validate the request body on login" paraphrase surfaces the
    ``@Valid`` DTO (``UserAuthenticate``) in the top 10."""
    comps = _indexed_feature(tmp_path)
    ranked = _reranked(comps["search"], "validate the request body on login", limit=10)
    names = {Path(r["file_path"]).name for r in ranked[:10]}
    assert "UserAuthenticate.java" in names, f"login-validation DTO missed: {names}"


def test_permission_paraphrase_surfaces_annotation_definition(tmp_path: Path) -> None:
    """A permission-restriction paraphrase surfaces the authorization-definition
    chunk (``CheckSecurity``/``AuthorizationConfig``)."""
    comps = _indexed_feature(tmp_path)
    ranked = _reranked(comps["search"], "restrict which users can modify a resource", limit=10)
    names = {Path(r["file_path"]).name for r in ranked[:10]}
    assert names & {"CheckSecurity.java", "AuthorizationConfig.java"}, (
        f"permission paraphrase missed the authorization definitions: {names}"
    )


# --- Occurrence-accurate exhaustive counting ----------------------------------


def test_exhaustive_counts_occurrences_on_multi_occurrence_line(tmp_path: Path) -> None:
    """A two-occurrence line counts as two and the response carries per-line
    occurrence metadata."""
    comps = _indexed_feature(tmp_path)
    envelope = comps["search"].search(
        '"slugify"', limit=200, mode="exhaustive", content="all", matching="literal"
    )
    assert envelope["mode"] == "exhaustive"
    total = int(envelope["total_count"])
    assert total == 2, f"multi-occurrence line undercounted: {total}"
    assert envelope.get("occurrence_count") == total
    assert sum(envelope.get("occurrences_per_line", [])) == total
    assert len(envelope.get("occurrences_per_line", [])) == len(
        envelope.get("occurrence_line_numbers", [])
    )
    two = [c for c in envelope.get("occurrences_per_line", []) if c >= 2]
    assert two, "expected a per-line entry >= 2 for the multi-occurrence line"


def test_exhaustive_single_occurrence_lines_unaffected(tmp_path: Path) -> None:
    """Single-occurrence-per-line literals keep the prior line count (no
    regression)."""
    comps = _indexed_feature(tmp_path)
    envelope = comps["search"].search(
        '"CREATE TABLE"', limit=200, mode="exhaustive", content="all", matching="literal"
    )
    assert int(envelope["total_count"]) == 1
    assert envelope.get("occurrence_count") == 1


# --- Type-aware config/DDL ranking --------------------------------------------


def test_config_scent_ranks_properties_above_build_noise(tmp_path: Path) -> None:
    """An abstract config query ranks the properties resource above
    ``pom.xml``/``package-lock.json`` build noise."""
    comps = _indexed_feature(tmp_path)
    envelope = comps["search"].search("server port configuration", limit=10)
    top10 = [Path(r["file_path"]).name for r in envelope["results"]]
    props_rank = next((i for i, n in enumerate(top10) if n == "application.properties"), None)
    assert props_rank is not None, f"config answer missing from top 10: {top10}"
    for noise in ("pom.xml", "package-lock.json"):
        noise_rank = next((i for i, n in enumerate(top10) if n == noise), None)
        if noise_rank is not None:
            assert props_rank < noise_rank, f"{noise} outranks the config answer ({top10})"


# --- Code-scoped config hint --------------------------------------------------


def test_code_scoped_config_intent_appends_hint(tmp_path: Path) -> None:
    """A code-scoped config-shaped query appends a visible config hint to the
    response envelope."""
    from src.engine.index_service import IndexChangeDetector
    from src.engine.response_service import build_response

    comps = _indexed_feature(tmp_path)
    detector = IndexChangeDetector.from_metadata_store(comps["metadata"])
    envelope = comps["search"].search("where is the mysql url", limit=10, content="code")
    built = build_response(
        envelope["results"],
        "where is the mysql url",
        detector,
        content_scope="code",
        metadata_store=comps["metadata"],
    )
    assert built["envelope"] is not None, "config hint missing on code scope"
    assert "config" in built["envelope"].lower() and "--content config" in built["envelope"]


def test_code_scoped_code_query_no_hint(tmp_path: Path) -> None:
    """A genuinely code-only query gets no config hint."""
    from src.engine.index_service import IndexChangeDetector
    from src.engine.response_service import build_response

    comps = _indexed_feature(tmp_path)
    detector = IndexChangeDetector.from_metadata_store(comps["metadata"])
    built = build_response(
        [],
        "how is the article saved",
        detector,
        content_scope="code",
        metadata_store=comps["metadata"],
    )
    assert built["envelope"] is None, f"false-positive config hint: {built['envelope']}"


# --- Index-change envelope ----------------------------------------------------


def test_index_change_detected_after_rebuild(tmp_path: Path) -> None:
    """A rebuilt index surfaces the visible "index changed — restart required"
    envelope instead of a silent empty/stale result."""
    from src.engine.index_service import IndexChangeDetector
    from src.engine.response_service import build_response

    comps = _indexed_feature(tmp_path)
    detector = IndexChangeDetector.from_metadata_store(comps["metadata"])

    built_before = build_response(
        [], "feed for a user", detector, content_scope="all", metadata_store=comps["metadata"]
    )
    assert built_before["index_changed"] is False
    assert built_before["envelope"] is None

    # Simulate an out-of-band rebuild: the indexer writes a fresh timestamp.
    comps["metadata"].set(
        "last_indexed_at",
        datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    built_after = build_response(
        [], "feed for a user", detector, content_scope="all", metadata_store=comps["metadata"]
    )
    assert built_after["index_changed"] is True
    assert built_after["envelope"] == "index changed — restart required", built_after["envelope"]
    assert built_after["silent_empty"] is False


def test_session_started_after_index_has_no_spurious_change(tmp_path: Path) -> None:
    """A session started on a current index reports no change."""
    from src.engine.index_service import IndexChangeDetector
    from src.engine.response_service import build_response

    comps = _indexed_feature(tmp_path)
    detector = IndexChangeDetector.from_metadata_store(comps["metadata"])
    built = build_response(
        [], "feed for a user", detector, content_scope="all", metadata_store=comps["metadata"]
    )
    assert built["index_changed"] is False
    assert built["envelope"] is None
