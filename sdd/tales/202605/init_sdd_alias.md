---
create_time: 2026-05-22 20:53:36
status: done
prompt: sdd/prompts/202605/init_sdd_alias.md
---
# Plan: Add `sase init sdd` Alias

## Goal

Add a new `sase init sdd` command that behaves as an alias for `sase sdd init`, including the same `-p/--path` option
and the same SDD README/directory-map creation behavior.

## Current Shape

The CLI is argparse-based.

- Top-level command registration lives in `src/sase/main/parser.py`.
- `sase init` is registered in `src/sase/main/parser_init.py` with `memory` and `skills` subcommands.
- `sase sdd init` is registered in `src/sase/main/parser_sdd.py`.
- SDD command behavior is centralized in `src/sase/main/sdd_handler.py`; `_handle_init()` calls
  `sase.sdd.files.write_sdd_readme(...)`.
- Top-level dispatch lives in `src/sase/main/entry.py`.

This is a Python CLI glue change only. It does not cross the Rust core boundary and does not need sibling repo changes.

## Proposed Design

Expose `sase init sdd` as a parser-level command under the existing `init` namespace, then dispatch it through the
existing SDD init handler instead of duplicating behavior.

1. Parser support
   - Add an `sdd` subcommand to `register_init_parser(...)`.
   - Give it help text matching the SDD init behavior: creating or refreshing SDD README files and directory map assets.
   - Give it the same `-p/--path` option as `sase sdd init`.
   - Prefer sharing the SDD path-argument helper from `parser_sdd.py` so option spelling and help text stay aligned.

2. Dispatch support
   - In the `args.command == "init"` branch of `src/sase/main/entry.py`, handle `args.init_subcommand == "sdd"`.
   - Set `args.sdd_subcommand = "init"` and call `handle_sdd_command(args)`.
   - This keeps the implementation path identical to `sase sdd init` after parsing and avoids a second SDD init code
     path.

3. Documentation
   - Update the CLI command reference to show `sase init sdd` alongside `sase sdd init`.
   - Update the SDD docs to mention the alias.
   - Update the detailed configuration/CLI reference so `sase init sdd` is discoverable from the `init` namespace and
     from the `sase sdd` section.

4. Tests
   - Extend parser tests to assert `create_parser().parse_args(["init", "sdd", "-p", "sdd"])` parses as
     `command == "init"`, `init_subcommand == "sdd"`, and `path == "sdd"`.
   - Add a dispatch test for `sase init sdd -p <tmp>` through `sase.main.entry.main()` with `write_sdd_readme` patched,
     asserting the same function is called with the provided path and exits successfully.
   - Keep existing sorted-help tests intact; the global help sorter should sort `memory`, `sdd`, and `skills`.

## Verification

After implementation:

1. Run `just install` because this workspace is ephemeral.
2. Run targeted tests first:
   - `pytest tests/main/test_sdd_handler.py tests/main/test_parser_help.py`
3. Run `just check` before finishing because source/docs files will have changed.

## Risks And Mitigations

- Risk: Duplicating the `-p/--path` argument could drift from `sase sdd init`. Mitigation: share a small parser helper
  for the SDD path argument.
- Risk: The alias could accidentally become a second implementation. Mitigation: dispatch through `handle_sdd_command`
  with `sdd_subcommand = "init"`.
- Risk: Docs could imply `sase init` exposes all SDD subcommands. Mitigation: document only `sase init sdd` as an alias
  for init, not a broader mirrored namespace.
