# Structured Agentic Software Engineering (SASE) - Agent Instructions

## Project Overview

**sase** (Structured Agentic Software Engineering) is a Python toolkit for building and orchestrating AI agents.

## Build & Run Commands

```bash
just install       # Install in editable mode with dev deps
just lint          # ruff check + mypy
just fmt           # Auto-format code
just test          # pytest with coverage
.venv/bin/sase     # Run CLI (use this for non-bead commands)
sase bead          # Use bare `sase bead` for bead workflows
```

IMPORTANT: If you made file changes in this repo, make sure to run the `just check` command before terminating /
replying to the user.

## Ephemeral `sase_<N>` Workspace Directories

Sase runs agents (like you) are run from ephemeral workspace directories, which are full clones of the sase repo that
live in the same parent directory as the main repo. These directories are named `sase_<N>` where `<N>` is some integer.
You need to be mindful not to run commands outside of these workspace directories, since they have their own isolated
virtual environments. So, for example, if you need to run `sase`, make sure to run `.venv/bin/sase` from within the
`sase_<N>` directory. Exception: for bead commands, run `sase bead ...`.

**IMPORTANT**: One consequence of this is that you need to run `just install` before running other commands like
`just check` (since it is possible we haven't used this workspace directory in a long time and package dependencies may
have changed).

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

## Runtime Parity

All supported agent runtimes (Claude, Gemini, Codex, etc.) have the same capabilities: they all support hooks, skills,
and the same commit workflow. Do NOT introduce runtime-specific special cases or branching logic that assumes one
runtime lacks a capability that others have. Treat all runtimes uniformly.

## Code Conventions

- Use **absolute imports**: `from sase.foo import bar` (not relative)
- Target **Python 3.12+** — use modern syntax (type unions with `|`, `match`, etc.)
- Follow **ruff** rules: E, W, F, I, B, C4, UP
- Type annotations on all public functions (to pass mypy lint)
- **Always define short options** (e.g., `-m`, `-f`) for every argument on all `sase` CLI subcommands

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
needed, but make sure to commit your changes to the chezmoi repo using your `/sase_git_commit` skill (NOT `git commit`)
after making them. Ignore the .sase_beads/ changes in commits when composing your commit message. IMPORTANT: After
committing to this repo, you MUST run the `chezmoi apply` command. Otherwise, the changes to the chezmoi files will not
be applied to the system (i.e. copied to their proper locations).

Chezmoi files related to sase that I know about:

- The sase.yml files that I use to configure sase can be found in the ~/.local/share/chezmoi/home/dot_config/sase/
  directory.

IMPORTANT: After committing to this repo, you MUST run the `chezmoi apply` command. Otherwise, the changes to the
chezmoi files will not be applied to the system (i.e. copied to their proper locations).

## Plugin Repos

- The ../sase-github and ../sase-google directories are git repositories that contain plugins for GitHub and Mercurial
  VCS providers, respectively.
- The ../sase-telegram directory is a git repository that contains a plugin for Telegram integration (implemented using
  chops).
- The ../sase-nvim directory is a git repository that contains a plugin for Neovim integration (ex: for project spec
  file syntax highlighting).

IMPORTANT: You can edit files in these repos if necessary. Just make sure to run the `just check` command in each plugin
repo that you've modified before terminating / replying to the user.

## Config Changes

When changing keymaps, leader mode keys, or any configuration values, don't forget to update the keymap configuration in
the `src/sase/default_config.yml` file if necessary.

## Workspace State is Ephemeral

Sase workspaces (`sase_<N>` directories) are reused across agent runs. Do not assume:

- That the current git state (HEAD, diff, working tree) in a workspace belongs to the current agent
- That files from the main repo are up-to-date in a stale workspace

When workspace state matters (e.g., reading diffs, checking file existence), verify the workspace has been synced to the
expected revision first. For completed/failed agents, only trust artifact paths (like `diff_path`) — never fall back to
live workspace state.

## Multi-Step Workflow Artifacts

For multi-step xprompt workflows, completion artifacts (like `done.json`) must be written to the **root** artifacts
directory, not just the last step's directory. Other agents waiting on workflow completion (via `%wait`) check the root
— if `done.json` is only in a child step's directory, the workflow name may be recycled by auto-naming and the wait will
never resolve.

## Plan Mode and Questions

- You do NOT have access to plan mode (`EnterPlanMode`/`ExitPlanMode`). Use the `/sase_plan` skill instead.
- You do NOT have access to `AskUserQuestion`. Use the `/sase_questions` skill instead.
