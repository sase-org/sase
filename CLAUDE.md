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

This project uses **bd** (beads) for issue tracking. Always use `sase_bd` (at `tools/sase_bd`) instead of `bd` directly.
Run `sase_bd onboard` to get started.

### Quick Reference

```bash
sase_bd ready              # Find available work
sase_bd show <id>          # View issue details
sase_bd update <id> --status in_progress  # Claim work
sase_bd close <id>         # Complete work
sase_bd sync               # Sync with git
```

## End-to-End Testing w/ `sase ace --agent`

The `sase ace --agent` command runs the TUI headlessly and returns structured JSON output. Use `--keys` to send
keystrokes and `--size` to control terminal dimensions.

```bash
# See initial TUI state
sase ace --agent

# Navigate down two items
sase ace --agent --keys j j

# Open query modal
sase ace --agent --keys slash

# Switch to agents tab
sase ace --agent --keys tab

# Custom terminal size
sase ace --agent --size 200x50 --keys j
```

## Chezmoi Repo

Some files associated with this project live in the ~/.local/share/chezmoi/ directory. Feel free to modify these if
needed, but make sure to commit your changes to the chezmoi repo using your commit skill (NOT `git commit`) after making
them.

Chezmoi iles related to sase that I know about:

- The sase.yml files that I use to configure sase can be found in the ~/.local/share/chezmoi/home/dot_config/sase/
  directory.
