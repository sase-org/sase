# sase task runner

venv_dir := ".venv"
venv_bin := venv_dir / "bin"

default:
    @just --list

# Bootstrap .venv if it doesn't exist
_setup:
    @[ -x {{ venv_bin }}/python ] || uv venv {{ venv_dir }}
    @{{ venv_bin }}/mypy --version > /dev/null 2>&1 || uv pip install --reinstall-package mypy -e ".[dev]"

# Print a box header for a top-level command (private helper)
_header NAME:
    @printf "\n"
    @printf "┌───────────────────────────────────────────────────────┐\n"
    @printf "│                RUNNING: just %-25s│\n" "{{ NAME }}"
    @printf "└───────────────────────────────────────────────────────┘\n"

# Install in editable mode with dev dependencies
install: _setup
    uv pip install -e ".[dev]"

# Run linters (ruff + mypy + pyscripts + pyvision + keep-sorted)
lint: _setup (_header "lint") lint-keep-sorted
    @printf "\n---------- Running ruff linter on Python files... ----------\n"
    @just _lint-ruff
    @printf "\n---------- Running mypy type checker... ----------\n"
    @just _lint-mypy
    @printf "\n---------- Validating scripts/tools directory structure... ----------\n"
    @just _lint-pyscripts
    @printf "\n---------- Checking for unused Python definitions... ----------\n"
    @just _lint-pyvision

# Run ruff linter on Python files (private, extracted for per-stage wrapping)
_lint-ruff: _setup
    {{ venv_bin }}/ruff check src/ tests/

# Run mypy type checker (private, extracted for per-stage wrapping)
_lint-mypy: _setup
    {{ venv_bin }}/mypy

# Validate scripts/tools directory structure (private, extracted for per-stage wrapping)
_lint-pyscripts: _setup
    {{ venv_bin }}/python tools/pyscripts-260314

# Check for unused Python definitions (private, extracted for per-stage wrapping)
_lint-pyvision: _setup
    BD_COMMAND=tools/sase_bead {{ venv_bin }}/python tools/pyvision-260225 src/sase

# Auto-fix all code (format + keep-sorted)
fix: (_header "fix") fmt-py fmt-md fix-keep-sorted

# Auto-format all code
fmt: (_header "fmt") fmt-py fmt-md

# Auto-format Python code
fmt-py: _setup
    @printf "\n---------- Formatting Python with ruff... ----------\n"
    {{ venv_bin }}/ruff format src/ tests/
    @printf "\n---------- Fixing Python with ruff... ----------\n"
    {{ venv_bin }}/ruff check --fix src/ tests/

# Auto-format Markdown files
fmt-md:
    @printf "\n---------- Formatting Markdown with prettier... ----------\n"
    prettier --write --prose-wrap=always --print-width=120 "**/*.md"

# Auto-fix keep-sorted blocks in YAML files
fix-keep-sorted:
    @printf "\n---------- Fixing keep-sorted blocks in YAML files... ----------\n"
    git ls-files '*.yml' '*.yaml' | xargs keep-sorted

# Lint keep-sorted blocks in YAML files (CI mode)
lint-keep-sorted:
    @printf "\n---------- Checking keep-sorted blocks in YAML files... ----------\n"
    git ls-files '*.yml' '*.yaml' | xargs keep-sorted --mode lint

# Check all formatting (CI mode)
fmt-check: (_header "fmt-check") fmt-py-check fmt-md-check

# Check Python formatting (CI mode)
fmt-py-check: _setup
    @printf "\n---------- Checking Python formatting with ruff... ----------\n"
    {{ venv_bin }}/ruff format --check src/ tests/

# Check Markdown formatting (CI mode)
fmt-md-check:
    @printf "\n---------- Checking Markdown formatting with prettier... ----------\n"
    prettier --check --prose-wrap=always --print-width=120 "**/*.md"

# Fast parallel test run, no coverage (use test-cov to enforce coverage gate)
test *args: _setup (_header "test")
    @printf "\n---------- Running pytest (parallel, no coverage)... ----------\n"
    {{ venv_bin }}/pytest -n auto --dist=loadfile {{ args }}

# Parallel test run with coverage reports + 50% gate (used by check and CI)
test-cov *args: _setup (_header "test-cov")
    @printf "\n---------- Running pytest with coverage... ----------\n"
    {{ venv_bin }}/pytest -n auto --dist=loadfile \
        --cov=src/sase \
        --cov-branch \
        --cov-report=term-missing:skip-covered \
        --cov-report=html \
        --cov-report=xml \
        --cov-fail-under=50 \
        {{ args }}

# Run tests across all Python versions
test-tox: _setup
    {{ venv_bin }}/tox

# Run tests for a specific Python version (e.g., just test-py 312)
test-py VER: _setup
    {{ venv_bin }}/tox -e py{{ VER }}

# Run all checks (format check + lint + test) with context-efficient output for agents
check: _setup
    @tools/run_silent "fmt (python)"       just fmt-py-check
    @tools/run_silent "fmt (markdown)"     just fmt-md-check
    @tools/run_silent "lint (keep-sorted)" just lint-keep-sorted
    @tools/run_silent "lint (ruff)"        just _lint-ruff
    @tools/run_silent "lint (mypy)"        just _lint-mypy
    @tools/run_silent "lint (pyscripts)"   just _lint-pyscripts
    @tools/run_silent "lint (pyvision)"    just _lint-pyvision
    @tools/run_silent "test"               just test-cov

# Fix code, run linters, and run tests.
all: fix lint pylimit test

# Find unused Python function/class definitions
pyvision *args: _setup (_header "pyvision")
    BD_COMMAND=tools/sase_bead {{ venv_bin }}/python tools/pyvision-260225 src/sase \
        {{ args }}

# Check Python file line counts
pylimit *args: (_header "pylimit")
    tools/pylimit-260221 src {{ if args == "" { "1000 850 700" } else { args } }}
    tools/pylimit-260221 tests {{ if args == "" { "1000 850 700" } else { args } }}

# Remove build artifacts
clean:
    rm -rf build/ dist/ *.egg-info src/*.egg-info .tox/ .mypy_cache/ .ruff_cache/ .pytest_cache/ htmlcov/ .coverage

# Build wheel and sdist
build: _setup
    {{ venv_bin }}/python -m build

# Build and verify package (CI mode)
build-check: build
    {{ venv_bin }}/twine check dist/*

# Activate venv in subshell
dev-shell:
    @echo "Entering dev shell... (exit to return)"
    @VIRTUAL_ENV="$(pwd)/.venv" PATH="$(pwd)/.venv/bin:$$PATH" $SHELL
