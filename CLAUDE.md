# Structured Agentic Software Engineering (SASE) - Agent Instructions

## Project Overview

**sase** (Structured Agentic Software Engineering) is a Python toolkit for building and orchestrating AI agents.

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
- Follow **ruff** rules: E, W, F, I, B, C4, UP
- Type annotations on all public functions (to pass mypy lint)

## Issue Tracking

This project uses **bd** (beads) for issue tracking. Run `bd onboard` to get started.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
```

## End-to-End Testing w/ `tmux_sase`

The `tmux_sase` script can be run with the `uv run tmux_sase <KEYS>` command, where `<KEYS>` is a sequence of keystrokes
to send to the tmux session. This script will run the `sase ace` command in a new tmux window, emulate the keystrokes
that you specified with `<KEYS>`, capture the contents of the tmux pane, and then output those contents on STDOUT.

## sase.yml

The sase.yml files that I use to configure sase can be found in the ~/.local/share/chezmoi/home/dot_config/sase/
directory. Feel free to modify these if needed, but make sure to commit your changes to the chezmoi repo using your
commit skill (NOT `git commit`) after making them.
