# sase task runner

venv_dir := ".venv"
venv_bin := venv_dir / "bin"

default:
    @just --list

# Bootstrap .venv if it doesn't exist
_setup:
    @[ -x {{ venv_bin }}/python ] || (uv venv {{ venv_dir }} && uv pip install -e ".[dev]")

# Print a box header for a top-level command (private helper)
_header NAME:
    @printf "\n"
    @printf "┌───────────────────────────────────────────────────────┐\n"
    @printf "│                RUNNING: just %-25s│\n" "{{ NAME }}"
    @printf "└───────────────────────────────────────────────────────┘\n"

# Install in editable mode with dev dependencies
install: _setup
    uv pip install -e ".[dev]"

# Run linters (ruff + mypy)
lint: _setup (_header "lint")
    @printf "\n---------- Running ruff linter on Python files... ----------\n"
    {{ venv_bin }}/ruff check src/ tests/
    @printf "\n---------- Running mypy type checker... ----------\n"
    {{ venv_bin }}/mypy

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

# Run tests with coverage
test *args: _setup (_header "test")
    @printf "\n---------- Running pytest with coverage... ----------\n"
    {{ venv_bin }}/pytest {{ args }}

# Run tests across all Python versions
test-tox: _setup
    {{ venv_bin }}/tox

# Run tests for a specific Python version (e.g., just test-py 312)
test-py VER: _setup
    {{ venv_bin }}/tox -e py{{ VER }}

# Run all checks (format check + lint + test)
check: fmt-check lint test

# Format code, run linteers, and run tests.
all: fmt lint pylimit pyvision test

# Find unused Python function/class definitions
pyvision: _setup (_header "pyvision")
    {{ venv_bin }}/python tools/pyvision-260217 src/sase

# Check Python file line counts
pylimit: (_header "pylimit")
    tools/pylimit-260217 src 1000 850 700
    tools/pylimit-260217 tests 1000 850 700

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
