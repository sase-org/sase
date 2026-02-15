# sase task runner

venv_dir := ".venv"
venv_bin := venv_dir / "bin"

default:
    @just --list

# Install in editable mode with dev dependencies
install:
    uv pip install -e ".[dev]"

# Run linters (ruff + mypy)
lint:
    {{ venv_bin }}/ruff check src/ tests/
    {{ venv_bin }}/mypy

# Auto-format code
fmt:
    {{ venv_bin }}/ruff format src/ tests/
    {{ venv_bin }}/ruff check --fix src/ tests/

# Check formatting (CI mode)
fmt-check:
    {{ venv_bin }}/ruff format --check src/ tests/

# Run tests with coverage
test:
    {{ venv_bin }}/pytest --cov=sase --cov-report=term-missing --cov-branch

# Run tests across all Python versions
test-tox:
    {{ venv_bin }}/tox

# Run tests for a specific Python version (e.g., just test-py 312)
test-py VER:
    {{ venv_bin }}/tox -e py{{ VER }}

# Run all checks (format check + lint + test)
check: fmt-check lint test

# Format code, run linteers, and run tests.
all: fmt lint test

# Remove build artifacts
clean:
    rm -rf build/ dist/ *.egg-info src/*.egg-info .tox/ .mypy_cache/ .ruff_cache/ .pytest_cache/ htmlcov/ .coverage

# Build wheel and sdist
build:
    {{ venv_bin }}/python -m build

# Activate venv in subshell
dev-shell:
    @echo "Entering dev shell... (exit to return)"
    @VIRTUAL_ENV="$(pwd)/.venv" PATH="$(pwd)/.venv/bin:$$PATH" $SHELL
