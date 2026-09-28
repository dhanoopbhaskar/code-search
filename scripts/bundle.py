#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path


def _find_python() -> Path:
    candidates = [
        Path(".venv/bin/python3"),
        Path(".venv/bin/python"),
        Path(".venv/Scripts/python.exe"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    python = shutil.which("python3") or shutil.which("python")
    if python:
        return Path(python)
    print("Error: Python not found", file=sys.stderr)
    sys.exit(1)


def _get_version(pyproject: Path) -> str:
    text = pyproject.read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        print("Error: cannot parse version from pyproject.toml", file=sys.stderr)
        sys.exit(1)
    return m.group(1)


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    print(f"    Running: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=cwd)


def _download_deps(python: Path, repo_root: Path) -> int:
    deps_dir = repo_root / "build" / "bundle" / "deps"
    deps_dir.mkdir(parents=True, exist_ok=True)

    version = subprocess.check_output(
        [
            str(python),
            "-c",
            "import sys; print(f'{sys.version_info.major}{sys.version_info.minor}')",
        ],
        text=True,
    ).strip()

    pip_cmd = [
        str(python),
        "-m",
        "pip",
        "download",
        "-d",
        str(deps_dir),
        ".",
        "--only-binary=:all:",
        "--platform",
        "manylinux2014_x86_64",
        "--python-version",
        version,
    ]

    subprocess.check_call(pip_cmd, cwd=repo_root)
    count = len(list(deps_dir.glob("*.whl")))

    return count


def _download_model(python: Path, repo_root: Path, model_name: str) -> bool:
    """Bundle a Model2Vec model into the bundle staging area.

    Prefers an existing local copy at ``<repo_root>/models/{model_name}`` so
    bundles can be built fully offline (air-gap). Otherwise attempts to load
    from HuggingFace; if the exact name is not found there, falls back to
    deriving a 32-dim model from 'minishlab/potion-code-16M'.
    """
    print(f"    Bundling model '{model_name}'...")
    model_dir = repo_root / "build" / "bundle" / "models" / model_name
    model_dir.mkdir(parents=True, exist_ok=True)

    local_model = repo_root / "models" / model_name
    if local_model.is_dir():
        for item in local_model.iterdir():
            dest = model_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        size = sum(f.stat().st_size for f in model_dir.rglob("*") if f.is_file())
        print(f"    Model bundled from local copy ({size / 1024:.0f}K)")
        return True

    script = (
        "import sys\n"
        "from model2vec import StaticModel\n"
        f"name = '{model_name}'\n"
        "try:\n"
        "    model = StaticModel.from_pretrained(name)\n"
        "except Exception:\n"
        "    # Fallback: derive 32-dim model from minishlab/potion-code-16M\n"
        "    print(f'    {name} not found on HF; deriving from minishlab/potion-code-16M...')\n"
        "    model = StaticModel.from_pretrained('minishlab/potion-code-16M', dimensionality=32)\n"
        f"model.save_pretrained('{model_dir}')\n"
        "print('Model downloaded and saved.')"
    )
    try:
        subprocess.check_call([str(python), "-c", script], cwd=repo_root)
        size = sum(f.stat().st_size for f in model_dir.rglob("*") if f.is_file())
        print(f"    Model saved ({size / 1024:.0f}K)")
        return True
    except Exception as exc:
        print(f"    Warning: model download failed: {exc}", file=sys.stderr)
        if model_dir.exists():
            shutil.rmtree(model_dir, ignore_errors=True)
        return False


def build_bundle(args: argparse.Namespace) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    os.chdir(str(repo_root))

    version = _get_version(repo_root / "pyproject.toml")
    dist_dir = repo_root / "dist"
    staging = repo_root / "build" / "bundle"

    print(f"==> Building code-search v{version} bundle...")
    print(f"    Deps: {args.deps}")

    python = _find_python()
    print(f"    Python: {python}")

    _run([str(python), "-m", "build", "--wheel", "--sdist"], cwd=repo_root)
    print("    Wheel built.")

    staging.mkdir(parents=True, exist_ok=True)

    for w in dist_dir.glob("*.whl"):
        shutil.copy2(w, staging)

    installer = repo_root / "scripts" / "install-from-bundle.py"
    if installer.exists():
        shutil.copy2(installer, staging)

    readme = repo_root / "README.md"
    if readme.exists():
        shutil.copy2(readme, staging)

    count = _download_deps(python, repo_root) if args.deps else 0
    if args.deps:
        print(f"    Downloaded {count} dependency wheel(s).")

    if not args.no_model:
        model_name = args.model or "potion-code-16m-32d"
        if not _download_model(python, repo_root, model_name):
            print(
                f"    Warning: model '{model_name}' could not be bundled; "
                "deployments will fall back to BM25-only search.",
                file=sys.stderr,
            )

    print("    Creating tarball...")
    dist_dir.mkdir(parents=True, exist_ok=True)
    output = dist_dir / f"code-search-{version}-bundle.tar.gz"

    with tarfile.open(str(output), "w:gz") as tar:
        tar.add(str(staging), arcname="bundle")

    size = output.stat().st_size
    shutil.rmtree(staging)

    print()
    print(f"Bundle created: {output} ({size / 1024:.0f}K)")
    print()
    print("To deploy in another repository:")
    print(f"  tar xzf code-search-{version}-bundle.tar.gz")
    print("  cd bundle")
    print("  python install-from-bundle.py")
    if args.deps:
        print("  (Deps included -- install works fully offline via --no-index)")
    if not args.no_model:
        print("  (Model included -- embedding available offline)")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build code-search portable bundle")
    parser.add_argument("--deps", action="store_true", help="Include offline dependency wheels")
    parser.add_argument(
        "--model",
        nargs="?",
        const="potion-code-16m-32d",
        default="potion-code-16m-32d",
        help="Embedding model to bundle (default: potion-code-16m-32d)",
    )
    parser.add_argument(
        "--no-model",
        action="store_true",
        help="Skip bundling the embedding model (not recommended for air-gap)",
    )
    args = parser.parse_args()
    build_bundle(args)


if __name__ == "__main__":
    main()
