from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--repo-path",
        default=None,
        help="Path to a git repository to run acceptance tests against. "
        "If not set, a temporary sample repo is created.",
    )


def _fix_index_status(context_dir: Path) -> bool:
    """Reset stale lock file and index_status after an interrupted run.

    Returns True if the index was fixed, False if the database is locked
    and a fresh index should be performed.
    """
    lock_file = context_dir / "index.lock"
    if lock_file.exists():
        lock_file.unlink()
    db_path = context_dir / "graph.db"
    if db_path.exists():
        import sqlite3

        try:
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "INSERT OR REPLACE INTO index_metadata (key, value) "
                "VALUES ('index_status', 'ready')"
            )
            conn.commit()
            conn.close()
            return True
        except sqlite3.OperationalError:
            return False
    return True


def _ensure_installed() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", str(_PROJECT_ROOT)],
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to install code-search: {result.stderr}")


def _run_cs(
    args: list[str],
    timeout: int = 60,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run code-search CLI from the project root (so 'src' is importable).

    The CLI uses ``--path`` to locate the repo and ``--context-dir`` to
    point to its ``.context/`` directory. Both must be passed explicitly
    when the repo is not the current working directory.
    """
    env = {**os.environ, "NO_COLOR": "1"}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "src.cli.main", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=_PROJECT_ROOT,
        env=env,
    )


def _setup_sample_repo(base: Path) -> Path:
    """Create a multi-language sample repo for acceptance testing."""
    repo = base / "acceptance_repo"
    repo.mkdir(parents=True)

    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "resources").mkdir(exist_ok=True)

    (repo / "src" / "main.py").write_text(
        '"""Main application module."""\n'
        "\nimport hashlib\n"
        "import json\n"
        "from typing import Optional\n\n"
        "API_KEY = 'sk-1234567890abcdef'\n"
        "SECRET = 'super-secret-password'\n\n\n"
        "def authenticate(token: str) -> dict:\n"
        '    """Validate auth token and return user info."""\n'
        "    if token.startswith('eyJ'):\n"
        "        return json.loads(token)\n"
        "    return {}\n\n\n"
        "class UserService:\n"
        '    """Manages user accounts and authentication."""\n\n'
        "    def __init__(self, db_url: str = 'postgres://user:pass@localhost/db') -> None:\n"
        "        self.db_url = db_url\n\n"
        "    def login(self, username: str, password: str) -> Optional[str]:\n"
        "        return f'token-for-{username}'\n\n"
        "    def create_user(self, username: str, email: str) -> bool:\n"
        "        return True\n"
    )

    (repo / "src" / "utils.py").write_text(
        '"""Utility functions."""\n\n'
        "def hash_password(password: str) -> str:\n"
        '    """Hash a password for secure storage."""\n'
        "    import hashlib\n"
        "    return hashlib.sha256(password.encode()).hexdigest()\n\n\n"
        "def validate_email(email: str) -> bool:\n"
        '    """Check if an email address is valid."""\n'
        "    return '@' in email\n"
    )

    (repo / "src" / "models.py").write_text(
        '"""Data models."""\n\n'
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\n"
        "class User:\n"
        '    """A user account."""\n'
        "    username: str\n"
        "    email: str\n"
        "    active: bool = True\n\n"
        "    def deactivate(self) -> None:\n"
        '        """Mark user as inactive."""\n'
        "        self.active = False\n"
    )

    (repo / "src" / "app.js").write_text(
        "/**\n"
        " * Main application entry point.\n"
        " * @param {string[]} args - command line arguments\n"
        " */\n"
        "function main(args) {\n"
        "    console.log('Starting app...');\n"
        "    return 0;\n"
        "}\n\n"
        "/**\n"
        " * Calculate the sum of two numbers.\n"
        " */\n"
        "function add(a, b) {\n"
        "    return a + b;\n"
        "}\n"
    )

    (repo / "src" / "Main.java").write_text(
        "/**\n"
        " * Main entry point for the Java application.\n"
        " */\n"
        "public class Main {\n"
        "    public static void main(String[] args) {\n"
        '        System.out.println("Hello");\n'
        "    }\n\n"
        "    /**\n"
        "     * Add two integers.\n"
        "     */\n"
        "    public static int add(int a, int b) {\n"
        "        return a + b;\n"
        "    }\n"
        "}\n"
    )

    (repo / "tests" / "test_main.py").write_text(
        "from src.main import authenticate, UserService\n\n\n"
        "def test_authenticate() -> None:\n"
        "    result = authenticate('test-token')\n"
        "    assert isinstance(result, dict)\n\n\n"
        "def test_login() -> None:\n"
        "    service = UserService()\n"
        "    token = service.login('admin', 'secret123')\n"
        "    assert token is not None\n"
    )

    (repo / "resources" / "config.xml").write_text(
        '<?xml version="1.0"?>\n'
        "<configuration>\n"
        "    <database>\n"
        "        <url>jdbc:postgresql://localhost:5432/app</url>\n"
        "        <username>admin</username>\n"
        "        <password>db-secret-123</password>\n"
        "    </database>\n"
        "</configuration>\n"
    )

    (repo / "resources" / "database.sql").write_text(
        "CREATE TABLE users (\n"
        "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        "    username TEXT NOT NULL UNIQUE,\n"
        "    email TEXT NOT NULL,\n"
        "    created_at DATETIME DEFAULT CURRENT_TIMESTAMP\n"
        ");\n"
    )

    (repo / "resources" / "app.properties").write_text(
        "app.name=CodeSearch\n"
        "app.version=1.0.0\n"
        "db.password=property-secret-value\n"
        "api.token=prop-token-abcdef\n"
    )

    (repo / "Dockerfile").write_text(
        "FROM python:3.11\nCOPY . /app\nWORKDIR /app\nRUN pip install -r requirements.txt\n"
    )

    return repo


@pytest.fixture(scope="session")
def installed(pytestconfig: pytest.Config) -> None:
    _ensure_installed()


@pytest.fixture(scope="session")
def repo_path(
    request: pytest.FixtureRequest,
    pytestconfig: pytest.Config,
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    user_path = pytestconfig.getoption("--repo-path")
    if user_path:
        return Path(user_path).resolve()
    return _setup_sample_repo(tmp_path_factory.mktemp("acceptance"))


_DEV_EXCLUDE = (
    ".venv,.venv_test,.venvs,venv,venvs,env,.env,"
    "__pycache__,.mypy_cache,.pytest_cache,.ruff_cache,.tox,.nox,"
    "node_modules,bower_components,"
    ".git,.svn,.hg,"
    "dist,build,wheelhouse,*.egg-info,.eggs,"
    "htmlcov,coverage,.benchmarks,.context,"
    "models"
)


@pytest.fixture(scope="session")
def indexed(
    request: pytest.FixtureRequest,
    pytestconfig: pytest.Config,
    repo_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Any]:
    keep = pytestconfig.getoption("--keep-index")
    context_dir = repo_path / ".context"

    if (
        keep
        and context_dir.exists()
        and (context_dir / "graph.db").exists()
        and _fix_index_status(context_dir)
    ):
        return {"repo_path": repo_path, "context_dir": context_dir, "cached": True}

    lock_file = context_dir / "index.lock"
    if lock_file.exists():
        lock_file.unlink()

    if context_dir.exists():
        shutil.rmtree(context_dir)

    idx_result = _run_cs(
        [
            "index",
            "--path",
            str(repo_path),
            "--force",
            "--include-tests",
            "--exclude",
            _DEV_EXCLUDE,
        ],
        timeout=900,
        extra_env={"CODE_SEARCH_CONTEXT_DIR": str(context_dir)},
    )
    assert idx_result.returncode == 0, (
        f"Index failed (rc={idx_result.returncode}):\n"
        f"STDOUT:\n{idx_result.stdout}\nSTDERR:\n{idx_result.stderr}"
    )

    assert context_dir.exists()
    assert (context_dir / "graph.db").exists()
    assert (context_dir / "audit.db").exists()

    return {"repo_path": repo_path, "context_dir": context_dir, "cached": False}
