---
create_time: 2026-06-14 18:04:04
status: done
prompt: sdd/prompts/202606/repeat_stop_status_1.md
---
# Plan: Display Repeat STOP Slots As STOPPED

## Problem

`%repeat` STOP currently writes `done.json` with `outcome: "completed"` plus repeat-specific fields:

- `repeat_stopped: true`
- `stopped_by: <predecessor-name>`

That is the right marker shape for orchestration because downstream `%wait` resolution must continue to treat the slot
as completed. The Agents tab, however, does not currently preserve those repeat-stop fields through the Rust-backed
artifact scan wire, and the TUI done-agent loader only maps generic outcomes to `DONE`, `FAILED`, or `PLAN REJECTED`. As
a result, intentional repeat STOP slots can be misclassified in the Agents tab instead of getting a distinct `STOPPED`
display status.

## Product Semantics

Introduce `STOPPED` as a terminal, non-error agent display status for repeat slots skipped by a predecessor's `STOP`
output variable.

`STOPPED` should mean:

- not failed, and not counted/grouped as failed;
- terminal and dismissable like other finished rows;
- not resumable as a successful chat completion;
- not revertable as a completed code-producing agent;
- still compatible with `%wait` cascading by keeping `done.json` outcome as `completed`.

## Implementation Plan

1. Preserve repeat STOP metadata across the scan boundary.
   - Add `repeat_stopped: bool = False` and `stopped_by: str | None = None` to Python `DoneMarkerWire`.
   - Add matching fields to Rust `sase-core` `DoneMarkerWire`.
   - Parse `repeat_stopped` and `stopped_by` in the Rust scanner.
   - Keep this additive and backward-compatible; old markers/index rows should default to `False`/`None`.

2. Map repeat-stopped done markers to `STOPPED` in the TUI loaders.
   - Update both direct filesystem loading and snapshot loading in `_done_loaders.py`.
   - Check `repeat_stopped` before the generic completed outcome mapping.
   - Keep error fields empty because this is not a failure.

3. Teach shared status helpers about `STOPPED`.
   - Add `STOPPED` to terminal/dismissable status sets.
   - Ensure status grouping does not place it in the Failed bucket.
   - Add row-rendering style for `STOPPED`.
   - Keep resume/revert predicates from treating `STOPPED` as a normal successful completion.
   - Update the Rust cleanup planner's dismissable statuses so cleanup/dismiss behavior matches the Python TUI.

4. Add focused regression coverage.
   - Extend the agent scan golden fixture with a repeat-stopped done marker.
   - Assert Python scan records and Rust scan parity expose `repeat_stopped` and `stopped_by`.
   - Add a loader test proving a repeat-stopped marker produces an `Agent(status="STOPPED")`.
   - Add status-bucket/predicate tests proving `STOPPED` is not failed, is terminal/dismissable, and is not
     resumable/revertable.
   - Add a cleanup planner test in `sase-core` proving `STOPPED` is dismissable.

5. Verify.
   - Run focused Python tests around repeat STOP, scan records, done-agent loading, status grouping, and cleanup facade
     behavior.
   - Run focused Rust `sase-core` tests for agent scan parity and cleanup planner.
   - Because implementation edits will touch this repo, run `just install` if needed and `just check` before finalizing.
