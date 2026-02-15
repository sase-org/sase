# sase — Structured Agentic Software Engineering

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy](https://img.shields.io/badge/type_checker-mypy-blue.svg)](https://mypy-lang.org/)
[![pytest](https://img.shields.io/badge/tests-pytest-blue.svg)](https://docs.pytest.org/)
[![tox](https://img.shields.io/badge/ci-tox-yellow.svg)](https://tox.wiki/)

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended for dependency management)
- [just](https://github.com/casey/just) (task runner)

## Quick Start

```bash
# Create and activate a virtual environment
uv venv .venv
source .venv/bin/activate

# Install in editable mode with dev dependencies
just install

# Run the CLI
sase
```

## Development

```bash
just install       # Install with dev deps
just fmt           # Auto-format code
just lint          # Run ruff + mypy
just test          # Run tests with coverage
just check         # All checks (fmt-check + lint + test)
just test-tox      # Test across Python 3.12, 3.13, 3.14
just clean         # Remove build artifacts
just build         # Build wheel + sdist
```

## Project Structure

```
src/sase/
├── __init__.py          # Package root (__version__)
├── __main__.py          # python -m sase support
├── py.typed             # PEP 561 type marker
└── main/
    ├── __init__.py
    └── entry.py         # CLI entry point
tests/                   # Test suite (mirrors src/sase/)
```

## Configuration

All tool configuration lives in `pyproject.toml`:

- **Build**: hatchling
- **Linting**: ruff (replaces black, isort, flake8, pylint)
- **Type checking**: mypy (strict mode)
- **Testing**: pytest + coverage
- **Multi-version testing**: tox (see `tox.ini`)
