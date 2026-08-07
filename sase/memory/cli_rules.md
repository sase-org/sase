---
type: long
parent: AGENTS.md
description: Read anytime new CLI subcommands or options are added.
---

# CLI Rules

When adding or changing CLI subcommands or options:

- Make `-h|--help` output excellent: clear, complete, consistent, and easy to scan.
- Keep listed subcommands and options sorted alphabetically.
- Give every public long option a short alias; this does not apply to internal subprocess arguments.
- Prefer beautiful, colored output over black-and-white output when color improves readability.

## Default `list` Subcommand Convention

- A command group that has an exact `list` child defaults to that child when invoked bare. Running
  `sase <group>` behaves like `sase <group> list`. This is wired centrally in
  `_default_list_subcommands()` in `src/sase/main/parser.py`; do not re-implement it per command.
- When a bare invocation delegates to `list`, SASE prints a runtime notice before the list output,
  for example `No subcommand provided for 'sase agent'; delegating to 'sase agent list'.`. Explicit
  `list` (and explicit non-`list`) invocations print no notice. Nested groups (e.g.
  `sase agent tribe`, `sase project alias`) report only the actually omitted group. The notice is
  emitted in `src/sase/main/entry.py` right after parsing via `default_list_delegation_notice()`.
- Flags owned by `list` still belong after the explicit `list` token (e.g. `sase plan list --json`,
  not `sase plan --json`). Document the bare default in the group's help/description, matching
  `sase plan`.
