---
create_time: 2026-04-30 17:39:24
status: done
prompt: sdd/prompts/202604/rebase_timestamps.md
---
# Plan: Add REBASE ChangeSpec TIMESTAMPS Entries

## Problem

The `b` keymap on the `sase ace` CLs tab runs the rebase workflow in `src/sase/ace/tui/actions/proposal_rebase.py`. On
success, `_rebase_task()`:

- claims a workspace,
- checks out the target ChangeSpec,
- runs the VCS provider rebase,
- updates the ChangeSpec `PARENT` field,
- refreshes deltas.

It never records a `TIMESTAMPS` entry, so rebases are missing from the same lifecycle history that already records
`COMMIT`, `STATUS`, `SYNC`, `REWORD`, `REWIND`, and `RENAME` events.

## Design

Add a new `REBASE` event type with an arrow detail matching the existing transition-style events:

```text
[YYMMDD_HHMMSS] REBASE  old-parent -> new-parent
```

For root rebases, use the display value `root`, not the internal `__root__` sentinel or provider-specific default
revision. This keeps the TIMESTAMPS field user-facing and consistent with the parent selection modal.

The implementation should record the timestamp only after:

1. the VCS rebase succeeds, and
2. the `PARENT` field update succeeds.

That mirrors the existing durable-mutation-then-timestamp pattern used by status, sync, and rename flows. If timestamp
recording fails, the rebase should still be considered successful, consistent with current timestamp recorder callers.

## Changes

1. Extend timestamp parsing/model documentation:
   - Update `TimestampEntry` docs/type comments in `src/sase/ace/changespec/models.py`.
   - Add `REBASE` to the accepted event-type regexes in `src/sase/ace/changespec/section_parsers.py`.
   - Update `add_timestamp_entry_atomic()` docs in `src/sase/ace/timestamps/recording.py`.

2. Record successful rebase events:
   - Extend `_rebase_task()` to accept the old parent display name.
   - Pass `changespec.parent` from `_run_rebase_workflow()`.
   - Normalize old/new display names with `root` for missing parent or `_ROOT_PARENT_SENTINEL`.
   - After `update_changespec_parent_atomic()` succeeds, call
     `add_timestamp_entry_atomic(project_file, cl_name, "REBASE", detail)`.

3. Add a unique TUI color for rebases:
   - Add `_COLOR_REBASE = "bold #FFAF5F"` in `src/sase/ace/tui/widgets/timestamps_builder.py`.
   - Map `"REBASE"` in `_EVENT_COLORS`.
   - This is unique within the TIMESTAMPS event palette and visually distinct from the existing
     green/gold/cyan/lavender/red event colors.

4. Tests:
   - Add parsing/recording coverage for `REBASE` in `tests/ace/changespec/test_timestamps.py`.
   - Add renderer coverage that verifies a `REBASE` event uses the new color.
   - Add a focused `_rebase_task()` regression test that mocks the workspace and VCS provider, runs the success path
     against a temporary `.gp` file, and asserts both `PARENT` and the `REBASE old -> new` timestamp are written.

## Validation

Run targeted tests first:

```bash
just install
pytest tests/test_rebase.py tests/ace/changespec/test_timestamps.py tests/ace/tui/test_timestamps_builder.py
```

Because this repo requires it after edits, finish with:

```bash
just check
```
