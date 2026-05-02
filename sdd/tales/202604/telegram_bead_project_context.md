---
status: draft
create_time: 2026-04-29 01:07:46
prompt: sdd/prompts/202604/telegram_bead_project_context.md
---

# Plan: Fix `/bead` Telegram Project Context

## Problem

The `/bead` Telegram slash command is executing `sase bead list` and `sase bead show <id>` without an explicit working
directory. As a result, those subprocesses inherit the inbound chop process CWD. In the observed failure, that CWD is
the `sase-telegram` plugin repo:

- `sase bead list` in `/home/bryan/projects/github/sase-org/sase-telegram` returns `No issues found.`
- `sase bead show sase-16` in that same repo returns `Error: issue not found: sase-16`.

The screenshot matches those exact outputs. Running the same commands in the active SASE project workspace
(`/home/bryan/projects/github/sase-org/sase_104`) does find `sase-16` and its children. So the formatter and bead parser
are not the root issue; the command is looking at the wrong project.

## Goal

Make `/bead` resolve bead commands against the intended SASE project workspace instead of the Telegram plugin process
CWD.

The fix should preserve the existing UX:

- `/bead` lists open beads with buttons.
- `/bead <id>` renders that bead.
- Button callbacks render the selected bead.
- Errors still return a clear Telegram message.

## Design

Add a small project-context resolver in `sase_tg_inbound.py` and route all bead subprocess calls through it.

Context resolution order:

1. If `SASE_TELEGRAM_BEAD_PROJECT` is set, resolve that project via
   `sase.running_field.get_workspace_directory(project, 1)`.
2. Otherwise, infer a default project from active Telegram context: scan recent/pending Telegram action prompts for a
   leading VCS workflow tag such as `#gh:sase` or `#gh_sase`, extract the project name, and resolve its primary
   workspace.
3. Otherwise, fall back to the current working directory to keep existing behavior for installations that already run
   the chop from the desired repo.

The environment override gives operators an explicit, deterministic escape hatch. The pending-prompt fallback matches
the actual Telegram flow: users launch work with `#gh_sase`, then use slash commands in the same bot chat.

## Implementation Steps

1. Add helper functions in `sase_tg_inbound.py`:
   - `_extract_project_from_prompt(prompt: str) -> str | None`
   - `_resolve_bead_cwd() -> str | None`
   - `_run_bead_command(args: list[str]) -> subprocess.CompletedProcess[str]`
2. Update `_show_bead_selection()` to call `_run_bead_command(["list"])`.
3. Update `_handle_bead_command()` to call `_run_bead_command(["show", bead_id])`.
4. Keep callback data unchanged for now. The resolved CWD is process-global per inbound invocation, and the immediate
   bug is wrong default project context.
5. Add tests that prove:
   - bead list/show subprocesses receive `cwd=<resolved workspace>`.
   - `SASE_TELEGRAM_BEAD_PROJECT` takes precedence.
   - the resolver can extract `sase` from recent pending prompts containing `#gh_sase` or `#gh:sase`.
   - fallback behavior remains unchanged when no context is available.

## Verification

Run in `sase-telegram`:

```bash
just check
```

Manual smoke after implementation:

```bash
cd /home/bryan/projects/github/sase-org/sase-telegram
SASE_TELEGRAM_BEAD_PROJECT=sase python - <<'PY'
from sase_telegram.scripts.sase_tg_inbound import _run_bead_command
print(_run_bead_command(["show", "sase-16"]).stdout)
PY
```

Expected result: it prints the `sase-16` bead from the SASE project, not `Error: issue not found: sase-16` from the
plugin repo.
