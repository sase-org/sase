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

This project uses **bd** (beads) for issue tracking. Always use `.venv/bin/sase bead` instead of `bd` directly. Run
`.venv/bin/sase bead onboard` to get started. IMPORTANT: Do NOT create beads unless you are explicitly asked to by the
user.

### Quick Reference

```bash
.venv/bin/sase bead ready              # Find available work
.venv/bin/sase bead show <id>          # View issue details
.venv/bin/sase bead update <id> --status in_progress  # Claim work
.venv/bin/sase bead close <id>         # Complete work
.venv/bin/sase bead sync               # Sync with git
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

## Plan Mode and Questions

- You do NOT have access to plan mode (`EnterPlanMode`/`ExitPlanMode`). Use the `/sase_plan` skill instead.
- You do NOT have access to `AskUserQuestion`. Use the `/sase_questions` skill instead.

## Issue Tracking with beads

**IMPORTANT**: This project uses **beads** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other
tracking methods. Always use `.venv/bin/sase bead` (NEVER bare `bd` or `sbd`).

### Why beads?

- Dependency-aware: Track blockers and relationships between issues
- Git-friendly: Dolt-powered version control with native sync
- Agent-optimized: JSON output, ready work detection, discovered-from links
- Prevents duplicate tracking systems and confusion

### Quick Start

**Check for ready work:**

```bash
.venv/bin/sase bead ready
```

**Create new issues:**

```bash
.venv/bin/sase bead create "Issue title" --description="Detailed context" -t bug|feature|task -p 0-4
.venv/bin/sase bead create "Issue title" --description="What this issue is about" -p 1 --deps discovered-from:sase-123
```

**Claim and update:**

```bash
.venv/bin/sase bead update <id> --claim
.venv/bin/sase bead update sase-42 --priority 1
```

**Complete work:**

```bash
.venv/bin/sase bead close sase-42 --reason "Completed"
```

### Issue Types

- `bug` - Something broken
- `feature` - New functionality
- `task` - Work item (tests, docs, refactoring)
- `epic` - Large feature with subtasks
- `chore` - Maintenance (dependencies, tooling)

### Priorities

- `0` - Critical (security, data loss, broken builds)
- `1` - High (major features, important bugs)
- `2` - Medium (default, nice-to-have)
- `3` - Low (polish, optimization)
- `4` - Backlog (future ideas)

### Workflow for AI Agents

1. **Check ready work**: `.venv/bin/sase bead ready` shows unblocked issues
2. **Claim your task atomically**: `.venv/bin/sase bead update <id> --claim`
3. **Work on it**: Implement, test, document
4. **Discover new work?** Create linked issue:
   - `.venv/bin/sase bead create "Found bug" --description="Details about what was found" -p 1 --deps discovered-from:<parent-id>`
5. **Complete**: `.venv/bin/sase bead close <id> --reason "Done"`

### Auto-Sync

Beads automatically sync via Dolt:

- Each write auto-commits to Dolt history
- Use `.venv/bin/sase bead dolt push`/`.venv/bin/sase bead dolt pull` for remote sync
- No manual export/import needed!

### Important Rules

- Always use `.venv/bin/sase bead` for ALL task tracking
- Link discovered work with `discovered-from` dependencies
- Check `.venv/bin/sase bead ready` before asking "what should I work on?"
- Do NOT create markdown TODO lists
- Do NOT use external issue trackers
- Do NOT duplicate tracking systems

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   .venv/bin/sase bead dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**

- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
