---
create_time: 2026-05-24 10:06:06
status: done
---
# Plan: `sase memory read -r` Alias

## Goal

Add `-r` as the short-option alias for `sase memory read --reason` while preserving the existing audited read behavior,
argument destination, validation, and long-option compatibility.

## Context

- The command is registered in `src/sase/main/parser_memory.py`.
- `sase memory read` currently accepts `memory_path` plus required `--reason`.
- The handler in `src/sase/memory/cli_read.py` reads `args.reason`, normalizes it, and logs the audited read.
- Existing parser tests in `tests/main/test_memory_parser_handler.py` cover the long `--reason` spelling.
- Project memory notes explicitly say new CLI options should have both long and short options.

## Implementation Plan

1. Update the `read_parser.add_argument` definition for reason to register both `-r` and `--reason`, keeping
   `required=True`, the same help text, and the same argparse destination name (`reason`).
2. Add parser coverage proving that `sase memory read long/foo.md -r "Need context"` parses to
   `args.reason == "Need context"`.
3. Keep existing long-option tests intact so the change is demonstrably backward compatible.
4. Update user-facing command references where they enumerate available memory read options, especially the CLI docs
   tables that currently list only `--reason`.

## Verification

1. Run the focused parser test module: `pytest tests/main/test_memory_parser_handler.py`
2. Run the focused memory read/list tests if the parser change or docs wording exposes adjacent behavior:
   `pytest tests/main/test_memory_read_list.py`
3. Because this repo requires it after code changes, run `just install` if needed, then `just check`.

## Risks

- `-r` could conflict only within the `memory read` subparser; the current inspected parser state shows no existing `-r`
  option for that subcommand.
- No handler change should be necessary because argparse will still populate `args.reason`.
- Documentation examples can continue to use the explicit long form, but option tables should mention the short alias so
  discovery is accurate.
