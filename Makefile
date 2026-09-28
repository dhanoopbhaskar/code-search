.PHONY: all build install editable bundle bundle-deps clean distclean download-deps help check lint format typecheck test

PACKAGE_NAME := code-search
DIST_DIR := dist
BUILD_DIR := build

# Auto-detect Python (prefer venv, then system)
_PY := $(shell command -v .venv/bin/python3 2>/dev/null || command -v .venv/bin/python 2>/dev/null || command -v .venv/Scripts/python.exe 2>/dev/null || command -v python3 2>/dev/null || command -v python 2>/dev/null)

all: build

help:
	@echo 'Targets:'
	@echo '  make build           - Build wheel + sdist'
	@echo '  make install         - Install into active venv from wheel'
	@echo '  make editable        - Editable install (pip install -e .)'
	@echo '  make bundle          - Build + create portable tarball'
	@echo '  make bundle-deps     - Build + create tarball with offline deps'
	@echo '  make download-deps   - Download dependency wheels to wheelhouse/'
	@echo '  make check           - Run all quality checks (lint, format, typecheck, test)'
	@echo '  make lint            - Run ruff lint check'
	@echo '  make format          - Run ruff format check'
	@echo '  make typecheck       - Run mypy type check'
	@echo '  make test            - Run pytest'
	@echo '  make clean           - Remove build artifacts'
	@echo '  make distclean       - Remove build, dist, and wheelhouse'
	@echo ''
	@echo 'Bundle output:  $(DIST_DIR)/$(PACKAGE_NAME)-*-bundle.tar.gz'

check:
	scripts/check.sh

lint:
	scripts/check.sh --lint

format:
	scripts/check.sh --format

typecheck:
	scripts/check.sh --typecheck

test:
	scripts/check.sh --test

build:
	$(_PY) -m build --wheel --sdist
	@echo 'Wheel built: $(DIST_DIR)/*.whl'

editable:
	pip install -e ".[dev]"

install: build
	pip install $(DIST_DIR)/*.whl

bundle:
	$(_PY) scripts/bundle.py

bundle-deps:
	$(_PY) scripts/bundle.py --deps

download-deps:
	$(_PY) -c "import subprocess, sys; from pathlib import Path; p = subprocess.run([sys.executable, '-m', 'pip', 'download', '--only-binary=:all:', '--platform', 'manylinux2014_x86_64', '--python-version', '311', '-d', 'wheelhouse', '.'], capture_output=True); exec('if p.returncode != 0 or not list(Path(\"wheelhouse\").glob(\"*.whl\")): subprocess.run([sys.executable, \"-m\", \"pip\", \"download\", \"-d\", \"wheelhouse\", \".\"])'); count = len(list(Path('wheelhouse').glob('*.whl'))); print(f'Dependency wheels downloaded: {count}')"

clean:
	rm -rf $(BUILD_DIR)
	rm -rf *.egg-info
	rm -rf src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	find . -type f -name '*.pyo' -delete

distclean: clean
	rm -rf $(DIST_DIR)
	rm -rf wheelhouse
	rm -rf .tox .nox
	rm -rf htmlcov coverage
