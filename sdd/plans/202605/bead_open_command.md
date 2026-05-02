---
create_time: 2026-05-01 13:00:42
status: done
prompt: sdd/prompts/202605/bead_open_command.md
---
# Plan: Add `sase bead open <id>`

## Problem

`sase bead update <id> --status open` is the only current way to move a bead back to the `open` state. That is
functionally correct, but it is awkward next to the existing shortcut command `sase bead close <id>`. Add a matching
`sase bead open <id>` command that behaves like the explicit update form:

```bash
sase bead open <id>
# equivalent to:
sase bead update <id> --status open
```

## Current Structure

The bead CLI is split across a few small layers:

- `src/sase/main/parser_bead.py` declares bead subcommands and their argparse surface.
- `src/sase/main/entry.py` dispatches parsed `bead_subcommand` values to handlers.
- `src/sase/bead/cli_crud.py` owns create/update/delete-style handlers.
- `src/sase/bead/cli_basic.py` and `src/sase/bead/cli.py` re-export handlers as compatibility facades.
- `docs/beads.md` documents the user-facing command set.

`handle_bead_update()` already builds a field dictionary and calls `BeadProject.update(args.id, status="open")`.
`BeadProject.update()` handles validation, telemetry, persistence, and JSONL export. The new shortcut should reuse that
same path rather than adding separate status-changing behavior.

## Design

Add a small `handle_bead_open(args)` handler in `src/sase/bead/cli_crud.py`:

1. Open the current bead project with `get_project()`.
2. Call `proj.update(args.id, status="open")`.
3. Preserve the existing update command's failure behavior for unknown IDs by catching `KeyError`, printing
   `Error: issue not found: <id>` to stderr, and exiting with code 1.
4. Print a concise success line. Prefer a command-specific message such as `○ Opened: <id> — <title>` so it is symmetric
   with `close`, while keeping the mutation itself exactly equivalent to `update --status open`.

Do not clear `closed_at` or `close_reason`. The requested behavior is "acts like `sase bead update <id> --status open`",
and the existing update path only changes `status` plus `updated_at`.

## Implementation Steps

1. Add `handle_bead_open()` to `src/sase/bead/cli_crud.py`.
2. Re-export it from `src/sase/bead/cli_basic.py`.
3. Re-export it from `src/sase/bead/cli.py` and include it in `__all__`.
4. Add an `open` subparser to `src/sase/main/parser_bead.py` with one positional `id`.
5. Import and dispatch `handle_bead_open` in `src/sase/main/entry.py`.
6. Update the bead usage string in `entry.py` so the fallback command list includes `open`.
7. Update `docs/beads.md` quick start and CLI command documentation.

## Tests

Add focused CLI coverage under `tests/test_bead/`:

- Parser coverage: `create_parser().parse_args(["bead", "open", "<id>"])` sets `command="bead"`,
  `bead_subcommand="open"`, and `id=<id>`.
- Handler success: create a bead, move it to `in_progress` or `closed`, call `bead_cli.handle_bead_open(...)`, and
  assert the bead status is `Status.OPEN`.
- Handler missing ID: call `handle_bead_open` with a nonexistent ID, assert `SystemExit(1)`, and assert the stderr error
  matches the `update` handler's style.

The handler test should monkeypatch `sase.bead.workspace.resolve_primary_workspace` to `None`, matching existing bead
CLI tests, so it operates on the temp project instead of any real workspace.

## Verification

After implementation:

1. Run the focused bead CLI tests, for example:

   ```bash
   just test tests/test_bead/test_cli_open.py
   ```

2. Because this repo requires it after file changes, run:

   ```bash
   just install
   just check
   ```

3. Optionally smoke-test the command in a temp bead project:

   ```bash
   sase bead open <id>
   sase bead show <id>
   ```
