---
create_time: 2026-04-24 21:12:36
status: done
---
# Remove shard migration tooling

## Goal

Delete the recently-added one-shot shard migration tooling — both the standalone script
`tools/migrate_sase_shard_dirs.py` and the `sase migrate shard-dirs` subcommand and its handler — along with all
references in code, tests, and docs. Leave the underlying YYYYMM sharding feature (write/read helpers in
`src/sase/core/paths.py`, per-subdir writer call sites) intact.

## Why

The migration script was added to backfill existing files into `YYYYMM/` shards on machines whose installed `sase`
predates the sharding feature. Readers already tolerate a mixed layout via `include_legacy=True`, so dropping the
migration path costs nothing for new installs and only means existing unmigrated files stay where they are.

## Background

Two recent commits added migration tooling on top of the underlying sharding work:

- `852f8fd0` — sharding feature + `sase migrate shard-dirs` subcommand.
- `39eb2791` — standalone `tools/migrate_sase_shard_dirs.py` (a stdlib-only port of the in-tree handler) plus a parity
  test that runs both implementations on identical synthetic trees and asserts byte-equal output.

The underlying sharding feature (helpers `sharded_path`, `iter_sharded_files`, `find_sharded_file`, plus the per-subdir
writer changes in `chats/`, `workflows/`, etc.) is **not** in scope and stays as-is.

## Open questions for the user

1. **Historical plans/specs** — by default these stay (they document what was built at the time). Confirm or list which
   to delete:
   - `plans/202604/standalone_shard_migration_script.md`, `specs/202604/standalone_shard_migration_script.md`
   - `plans/202604/shard_sase_dirs_by_yyyymm.md`, `specs/202604/shard_sase_dirs_by_yyyymm.md`
   - `plans/202604/migrate.md`, `specs/202604/migrate.md`
2. **Underlying sharding feature stays** — confirm only the one-shot migration tooling is being removed; `sharded_path`
   / `iter_sharded_files` / `find_sharded_file` and the per-subdir writers remain.

## Scope

### Files to delete

- `tools/migrate_sase_shard_dirs.py` (standalone script, ~242 lines).
- `tests/main/test_migrate_shard_dirs_script.py` (parity test, ~286 lines).
- `tests/main/test_migrate_shard_dirs.py` (smoke tests for the subcommand).
- `src/sase/main/migrate_handler.py` (subcommand handler, ~165 lines).

### Files to edit

- `src/sase/main/parser.py` — drop `register_migrate_parser` from the import block (lines 7–26) and the call at line 53.
- `src/sase/main/parser_commands.py` — delete `register_migrate_parser` (lines 290–325).
- `src/sase/main/entry.py` — delete the `--- migrate ---` dispatch block (lines 138–143).
- `src/sase/core/paths.py` — delete migration-only symbols `_SHARDED_SENTINEL` (line 107), `shard_is_migrated` (line
  235), and `mark_shard_migrated` (line 240). Grep confirms these are only referenced by `migrate_handler.py` and the
  standalone script (both being deleted).
- `README.md` — remove the `sase migrate shard-dirs` row from the CLI table at line 169.
- `docs/configuration.md`:
  - Remove the entire `### sase migrate` section (lines 892–901).
  - In `## Directory Sharding`, remove the "To backfill existing files…" block and the trailing standalone-script
    paragraph (roughly lines 913–923). Keep the surrounding paragraphs that explain the YYYYMM layout itself.

### Non-goals

- Do not touch the underlying sharding helpers in `src/sase/core/paths.py` beyond the three listed migration-only
  symbols.
- Do not modify per-subdir write sites (`chats`, `workflows`, etc.) — they keep using `sharded_path`.

## Implementation order

1. Delete the four files in the "Files to delete" list.
2. Edit the parser/entry/paths/docs files in the "Files to edit" list.
3. Re-grep for any of: `migrate_handler`, `handle_migrate_command`, `migrate_subcommand`, `register_migrate_parser`,
   `shard_is_migrated`, `mark_shard_migrated`, `_SHARDED_SENTINEL`, `migrate_sase_shard_dirs`, `migrate shard-dirs` —
   expect zero hits in `src/`, `tests/`, `docs/`, `README.md`, `tools/`.
4. (Pending answer to open question 1) optionally delete historical plans/specs.

## Validation

- `just install` (workspace may be stale per `memory/short/workspaces.md`).
- `just lint` — catches stale imports of removed symbols.
- `just test` — confirms nothing else depends on the removed handler / helpers; the deleted test files won't run.
- `just check` — final gate before replying per `memory/short/build_and_run.md`.
