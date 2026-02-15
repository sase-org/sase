# sase task runner

default:
    @just --list

# Install in editable mode with dev dependencies
install:
    uv pip install -e ".[dev]"

# Run linters (ruff + mypy)
lint:
    ruff check src/ tests/
    mypy

# Auto-format code
fmt:
    ruff format src/ tests/
    ruff check --fix src/ tests/

# Check formatting (CI mode)
fmt-check:
    ruff format --check src/ tests/

# Run tests with coverage
test:
    pytest --cov=sase --cov-report=term-missing --cov-branch

# Run tests across all Python versions
test-tox:
    tox

# Run tests for a specific Python version (e.g., just test-py 312)
test-py VER:
    tox -e py{{VER}}

# Run all checks (format check + lint + test)
check: fmt-check lint test

# Remove build artifacts
clean:
    rm -rf build/ dist/ *.egg-info src/*.egg-info .tox/ .mypy_cache/ .ruff_cache/ .pytest_cache/ htmlcov/ .coverage

# Build wheel and sdist
build:
    python -m build

# Activate venv in subshell
dev-shell:
    @echo "Entering dev shell... (exit to return)"
    @VIRTUAL_ENV="$(pwd)/.venv" PATH="$(pwd)/.venv/bin:$$PATH" $$SHELL
