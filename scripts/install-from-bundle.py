#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _pip_cmd(venv: Path) -> list[str]:
    pip = venv / "Scripts" / "pip.exe" if _is_windows() else venv / "bin" / "pip"
    if not pip.exists():
        pip = venv / "bin" / "pip3"
    return [str(pip)]


def _python_cmd(venv: Path) -> list[str]:
    python = venv / "Scripts" / "python.exe" if _is_windows() else venv / "bin" / "python3"
    if not python.exists():
        python = venv / "bin" / "python"
    return [str(python)]


def _find_wheel(bundle: Path) -> Path:
    wheels = list(bundle.glob("code_search-*.whl")) + list(bundle.glob("code-search-*.whl"))
    if not wheels:
        print(f"Error: no .whl file found in {bundle}", file=sys.stderr)
        sys.exit(1)
    return wheels[0]


def _offline_args(deps: Path | None) -> list[str]:
    if deps and deps.is_dir() and any(deps.iterdir()):
        return ["--no-index", "--find-links", str(deps)]
    return []


def _pip_install_cmd(wheel: Path, deps: Path | None, force: bool = False) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        *(["--force-reinstall"] if force else []),
        *_offline_args(deps),
        str(wheel),
    ]


def install_global(wheel: Path, deps: Path | None, force: bool = False) -> None:
    pipx = shutil.which("pipx")
    if pipx:
        pip_args = ["--pip-args", " ".join(_offline_args(deps))] if _offline_args(deps) else []
        if force:
            pip_args = ["--force", *pip_args]
        subprocess.check_call([pipx, "install", str(wheel), *pip_args])
        return

    cmd = _pip_install_cmd(wheel, deps, force)
    try:
        subprocess.check_call(cmd)
        return
    except subprocess.CalledProcessError:
        if os.geteuid() == 0:
            raise

    result = subprocess.run([*cmd, "--user"], text=True, capture_output=True)
    if result.returncode == 0:
        print()
        print("  Note: the 'code-search' command is installed to ~/.local/bin;")
        print("        add it to PATH if not already present.")
        return

    output = result.stdout + result.stderr
    if "externally-managed-environment" not in output:
        print(output, end="")
        raise subprocess.CalledProcessError(result.returncode, result.args)

    print("    System Python is externally managed (PEP 668) and --user is blocked.")
    print("    Retrying with --break-system-packages (overrides the PEP 668 guard).")
    print("    Warning: this overrides OS-managed package protection; consider pipx or")
    print("    a venv for isolation.")
    subprocess.check_call([*cmd, "--break-system-packages"])
    print()
    print("  Note: on systems where the system site-packages are not writable, pip")
    print("        installs into the user site (~/.local) and the 'code-search' command")
    print("        lands in ~/.local/bin; add it to PATH if not already present.")


def install_venv(wheel: Path, venv_dir: Path, deps: Path | None, force: bool = False) -> None:
    if not venv_dir.exists():
        print(f"    Creating virtual environment at {venv_dir}...")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])

    print(f"    Installing into {venv_dir}...")
    pip = _pip_cmd(venv_dir)

    subprocess.check_call(
        [*pip, "install", "--upgrade", "pip", "wheel"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    force_args = ["--force-reinstall"] if force else []
    if deps and deps.is_dir() and any(deps.iterdir()):
        print("    Installing from offline deps directory...")
        subprocess.check_call(
            [*pip, "install", "--no-index", "--find-links", str(deps), *force_args, str(wheel)]
        )
    else:
        subprocess.check_call([*pip, "install", *force_args, str(wheel)])

    print()
    print("Activate the environment and verify:")
    if _is_windows():
        print(f"  {venv_dir}\\Scripts\\activate")
    else:
        print(f"  source {venv_dir}/bin/activate")
    print("  code-search --help")


def _user_base() -> Path:
    """Return the per-user base directory used by ``pip install --user``.

    Cross-platform: ``~/.local`` on Linux/macOS, ``%APPDATA%\\Python`` on
    Windows. Must match what ``_find_local_model_path`` in embeddings.py uses.
    """
    base = sysconfig.get_config_var("userbase")
    if base:
        return Path(base)
    return Path.home() / ".local"


def _pipx_venv_dir() -> Path | None:
    """Return the pipx venv that a global install will use, if pipx is present."""
    pipx = shutil.which("pipx")
    if not pipx:
        return None
    pipx_home = None
    with contextlib.suppress(Exception):
        pipx_home = subprocess.check_output(
            [pipx, "environment", "--value", "PIPX_HOME"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    if not pipx_home:
        pipx_home = str(_user_base() / "share" / "pipx")
    venvs = Path(pipx_home) / "venvs"
    for name in ("code-search", "code_search"):
        candidate = venvs / name
        if candidate.is_dir():
            return candidate
    return venvs / "code-search"


def _install_model(bundle: Path, install_dir: Path) -> None:
    """Install bundled models to a stable, prefix-anchored location.

    Models are copied to ``<install_dir>/share/code-search/models/<name>``.
    ``_find_local_model_path`` in embeddings.py checks ``sys.prefix/share``
    and the pip ``--user`` base at runtime, so the model stays discoverable
    regardless of which repository ``code-search`` is run in.
    """
    models_dir = bundle / "models"
    if not models_dir.is_dir():
        return
    dest_root = install_dir / "share" / "code-search" / "models"
    for model_name in [d.name for d in models_dir.iterdir() if d.is_dir()]:
        src = models_dir / model_name
        dest = dest_root / model_name
        if dest.exists():
            print(f"    Model '{model_name}' already installed at {dest}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)
        size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
        print(f"    Model '{model_name}' installed at {dest} ({size / 1024:.0f}K)")


def _model_install_dir(args: argparse.Namespace) -> Path:
    """Return the prefix-relative base that should own the bundled model."""
    if args.install_global:
        pipx_venv = _pipx_venv_dir()
        if pipx_venv is not None:
            return pipx_venv
        prefix = Path(sys.prefix)
        if os.access(prefix, os.W_OK):
            return prefix
        return _user_base()
    return Path(args.venv)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install code-search from a bundle")
    parser.add_argument(
        "--global",
        dest="install_global",
        action="store_true",
        help="Install into the system Python (or pipx) instead of creating a venv",
    )
    parser.add_argument(
        "--venv", default=os.environ.get("VENV_DIR", ".venv"), help="Venv path (default: .venv)"
    )
    parser.add_argument(
        "--force", action="store_true", help="Force reinstall even if version is unchanged"
    )
    parser.add_argument(
        "--no-model", action="store_true", help="Skip installing the bundled model"
    )
    args = parser.parse_args()

    bundle = Path(__file__).resolve().parent
    wheel = _find_wheel(bundle)
    deps: Path | None = bundle / "deps" if (bundle / "deps").is_dir() else None

    print(f"Installing code-search from: {wheel.name}")

    if args.install_global:
        install_global(wheel, deps, force=args.force)
    else:
        install_venv(wheel, Path(args.venv), deps, force=args.force)

    if not args.no_model:
        _install_model(bundle, _model_install_dir(args))

    print("Done.")


if __name__ == "__main__":
    main()
