---
create_time: 2026-04-29 18:52:02
status: done
prompt: sdd/prompts/202604/submitted_status_timestamp.md
---
# Submitted STATUS Timestamp Plan

## Problem

When a ChangeSpec status changes to `Submitted`, the status state machine plans a `STATUS` timestamp event, but the
event is recorded after terminal ChangeSpecs are moved from the main project file to the archive file. The recorder is
still called with the original `project_file`, so a main-file `Mailed -> Submitted` transition moves the block to
`<project>-archive.gp` and then fails to find the ChangeSpec in `<project>.gp`. The failure is silent because
`add_timestamp_entry_atomic()` returns `False`.

This affects at least:

- `sase ace` manual submit for non-git/non-gh paths that call `transition_changespec_status()` directly.
- Git/GitHub submit flows through `workspace_provider.submit_changespec()` and `finalize_submission()`.
- Scheduler-driven submission detection in `checks_runner._handle_cl_submitted_completion()`.

## Design

Keep the pure status planner unchanged. It already returns the correct logical timestamp event (`"<old> -> Submitted"`)
and post-rename target name. The bug is in host-side side-effect routing after archive movement.

Update `transition_changespec_status_python()` so the timestamp recorder writes to the file that contains the ChangeSpec
after all post-lock side effects:

1. Track a `timestamp_project_file` initialized to the incoming `project_file`.
2. During archive handling, compute `main_file` and `archive_file` as today.
3. If the archive move succeeds logically by action:
   - `ARCHIVE_ACTION_TO_ARCHIVE`: set `timestamp_project_file = archive_file`.
   - `ARCHIVE_ACTION_FROM_ARCHIVE`: set `timestamp_project_file = main_file`.
   - no archive action: leave it as the incoming file.
4. Record the timestamp using `timestamp_project_file`, `plan.timestamp_target_name`, event type `STATUS`, and
   `plan.timestamp_event`.

This preserves the existing side-effect ordering and keeps timestamp recording after suffix rename and archive movement,
which matters because `timestamp_target_name` is already the post-rename name.

## Tests

Add focused regression coverage in `tests/test_status_state_machine_transitions.py`:

1. `Mailed -> Submitted` with `validate=True`:
   - starts in the main `.gp` file,
   - succeeds,
   - moves the ChangeSpec to the archive file,
   - writes `STATUS: Submitted`,
   - records a `TIMESTAMPS` entry containing `Mailed -> Submitted` in the archive file,
   - leaves the ChangeSpec absent from the main file.
2. Archive restore path, `Submitted -> WIP` with `validate=False` on the archive file:
   - moves the ChangeSpec back to the main file,
   - records `Submitted -> WIP` in the main file,
   - leaves the ChangeSpec absent from the archive file.

These cases prove both archive directions pick the post-move destination for timestamp recording.

## Validation

Run targeted tests first:

```bash
just install
pytest tests/test_status_state_machine_transitions.py tests/ace/changespec/test_timestamps.py
```

Because this repo requires it after edits, finish with:

```bash
just check
```
