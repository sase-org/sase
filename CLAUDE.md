# CLAUDE.md — AI Coding Assistant Guidelines for sase

## Project Overview

**sase** (Structured Agentic Software Engineering) is a Python toolkit for building and orchestrating AI agents. It is a migration from the `gai` (Google AI) codebase into a properly packaged Python project.

## Build & Run Commands

```bash
just install       # Install in editable mode with dev deps
just lint          # ruff check + mypy
just fmt           # Auto-format code
just test          # pytest with coverage
just check         # All checks (fmt-check + lint + test)
just test-tox      # Multi-version testing (3.12, 3.13, 3.14)
sase               # Run CLI
python -m sase     # Alternative CLI invocation
```

## Architecture

- **Layout**: `src/sase/` (src layout with hatchling build backend)
- **Entry point**: `sase.main.entry:main` → `sase` CLI command
- **Config**: All tool config in `pyproject.toml` (ruff, mypy, pytest, coverage)
- **Testing**: `tests/` directory, mirrors `src/sase/` structure

## Code Conventions

- Use **absolute imports**: `from sase.foo import bar` (not relative)
- Target **Python 3.12+** — use modern syntax (type unions with `|`, `match`, etc.)
- Follow **ruff** rules: E, W, F, I, N, UP, B, SIM, RUF, C4, PT, RET, PIE
- Type annotations on all public functions (mypy strict mode)
- Line length: 88 characters

## Issue Tracking

This project uses **beads** (`bd`) for issue tracking. See `AGENTS.md` for commands.
