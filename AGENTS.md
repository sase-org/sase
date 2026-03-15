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
.venv/bin/sase     # Run CLI (always use .venv/bin/sase, NEVER bare `sase`)
```

## Ephemeral `sase_<N>` Workspace Directories

Sase runs agents (like you) are run from ephemeral workspace directories, which are full clones of the sase repo that
live in the same parent directory as the main repo. These directories are named `sase_<N>` where `<N>` is some integer.
You need to be mindful not to run commands outside of these workspace directories, since they have their own isolated
virtual environments. So, for example, if you need to run `sase`, make sure to run `.venv/bin/sase` from within the
`sase_<N>` directory; you should NEVER run just `sase`.

**IMPORTANT**: One consequence of this is that you need to run `just install` before running other commands like
`just lint` or `just test` (since it is possible we haven't used this workspace directory in a long time and package
dependencies may have changed).

## Architecture

- **Layout**: `src/sase/` (src layout with hatchling build backend)
- **Entry point**: `sase.main.entry:main` → `sase` CLI command
- **Config**: All tool config in `pyproject.toml` (ruff, mypy, pytest, coverage)
- **Testing**: `tests/` directory, mirrors `src/sase/` structure

### Glossary

- **xprompt** : Triggered with strings like `#foo` in agent prompts, where foo must be in an xprompts/ directory
  (several location supported) or in a ~/.config/sase/sase.yml file (see the `xprompts` field). If definded in an
  xprompts/ directory, it must be a .md file or a .yml file.
- **xprompt part** : If defined by a .md file, an xprompt is considered to be an "xprompt part" and is equivalent to
  defining the same prompt in a .yml file in a xprompts/ directory where the only step is a `prompt_part` step that has
  the same content as the .md file.
- **xprompt workflow** : If defined by a .yml file, an xprompt is considered to be an "xprompt workflow" and can have
  multiple steps of any (ex: `prompt_part` allows you to expand `#foo` into some pre-defined content, `python` or `bash`
  let you run code, etc.).

## Code Conventions

- Use **absolute imports**: `from sase.foo import bar` (not relative)
- Target **Python 3.12+** — use modern syntax (type unions with `|`, `match`, etc.)
- Follow **ruff** rules: E, W, F, I, B, C4, UP
- Type annotations on all public functions (to pass mypy lint)

## Issue Tracking

This project uses **bd** (beads) for issue tracking. Always use `sase_bd` (at `tools/sase_bd`) instead of `bd` directly.
Run `sase_bd onboard` to get started. IMPORTANT: Do NOT create beads unless you are explicitly asked to by the user.

### Quick Reference

```bash
tools/sase_bd ready              # Find available work
tools/sase_bd show <id>          # View issue details
tools/sase_bd update <id> --status in_progress  # Claim work
tools/sase_bd close <id>         # Complete work
tools/sase_bd sync               # Sync with git
```

## End-to-End Testing w/ `sase ace --agent`

The `sase ace --agent` command runs the TUI headlessly and returns structured JSON output. Use `--keys` to send
keystrokes and `--size` to control terminal dimensions.

```bash
# See initial TUI state
.venv/bin/sase ace --agent

# Navigate down two items
.venv/bin/sase ace --agent --keys j j

# Open query modal
.venv/bin/sase ace --agent --keys slash

# Switch to agents tab
.venv/bin/sase ace --agent --keys tab

# Custom terminal size
.venv/bin/sase ace --agent --size 200x50 --keys j
```

## Chezmoi Repo

Some files associated with this project live in the ~/.local/share/chezmoi/ directory. Feel free to modify these if
needed, but make sure to commit your changes to the chezmoi repo using your commit skill (NOT `git commit`) after making
them.

Chezmoi iles related to sase that I know about:

- The sase.yml files that I use to configure sase can be found in the ~/.local/share/chezmoi/home/dot_config/sase/
  directory.

## Plugin Repos

- The ../sase-github and ../sase-google directories are git repositories that contain plugins for GitHub and Mercurial
  VCS providers, respectively.
- The ../sase-telegram directory is a git repository that contains a plugin for Telegram integration (implemented using
  chops).
- The ../sase-nvim directory is a git repository that contains a plugin for Neovim integration (ex: for project spec
  file syntax highlighting).

IMPORTANT: You can edit files in these repos if necessary. Just make sure to commit your changes to the corresponding
repo using your commit skill (NOT `git commit`) after making them.

## Plan Mode and Questions (sase Agents Only)

When running inside sase (`SASE_AGENT` is set):

- You do NOT have access to plan mode (`EnterPlanMode`/`ExitPlanMode`). Use the `/sase_plan` skill instead.
- You do NOT have access to `AskUserQuestion`. Use the `/sase_questions` skill instead.
- The `sase plan` and `sase questions` CLI commands are implementation details used by these skills -- do not reference
  them directly.
