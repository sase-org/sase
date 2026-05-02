---
create_time: 2026-04-29 23:54:50
status: done
prompt: sdd/prompts/202604/bead_work_reentry.md
---
# Plan: make `sase bead work <epic>` re-runnable

## Summary

`sase bead work <epic_id>` should be safe to invoke more than once for the same epic. A later invocation should inspect
the current bead state, launch agents only for phase beads that are not yet closed, and leave already-closed phases out
of the new multi-prompt. This is primarily a recovery path: if a previous batch of phase agents failed because of an
external issue such as authentication, the user should be able to fix the external problem and run the same command
again without manually resetting the epic's `is_ready_to_work` flag or recreating beads.

The important product definition is that "still open" must mean "not closed", not only `Status.OPEN`. The current
`sase bead work` implementation pre-claims phases as `in_progress` before launching agents, so a failed phase agent will
usually leave its bead in `in_progress`. A retry that selected only literal `open` phases would miss the exact recovery
case.

## Current behavior

The core implementation is split between:

- `src/sase/bead/work.py`
  - `build_epic_work_plan()` validates the epic, selects every child phase whose status is not `closed`, layers those
    phases into Kahn waves, and renders waits between in-epic open blockers.
  - Closed in-epic blockers are treated as satisfied, and out-of-epic blockers must be closed.
  - `render_multi_prompt()` emits one `%name:<phase_id>` segment per phase plus a final `<epic_id>.land` segment.

- `src/sase/bead/cli.py`
  - `handle_bead_work()` currently rejects an epic if `is_ready_to_work=True`.
  - On first launch it marks the epic ready, pre-claims every planned phase as `in_progress` with `assignee=<phase_id>`,
    and calls `launch_agent_from_cwd()` once with the rendered multi-prompt.
  - It checks for generated agent-name collisions before mutation and rolls back pre-claims if launch fails.

The plan builder is already close to the desired retry semantics because it excludes closed phases and considers
non-closed dependencies. The CLI guard around `is_ready_to_work` is the main re-entry blocker.

There is one additional recovery problem: the existing name-collision check uses `get_active_agent_name_map()`, which
includes visible completed agents as well as live agents. That was useful for preventing accidental orphan collisions,
but it would block the most common retry after failed agents, because failed agents have terminal artifacts that still
carry the phase agent names. For re-entry, terminal prior attempts must not block a new attempt.

## Goals

1. Re-running `sase bead work <epic_id>` after the epic is already marked ready should be allowed.
2. Each invocation should build a fresh plan from the current bead state and launch only non-closed child phases.
3. Closed phase beads should not be re-claimed, relaunched, or included in the rendered multi-prompt.
4. Non-closed phases, including `open` and `in_progress`, should be eligible for relaunch.
5. Live agents that already own one of the names the new batch would use should still block launch, so we do not create
   duplicate workers for a phase that is already running or waiting.
6. Terminal prior attempts, including failed/done agents with the same phase names, should not block recovery.
7. The land agent should be launched only when there is at least one non-closed phase in the retry plan; it should wait
   on the leaf phases of that retry plan.
8. `--dry-run` should reflect the same filtered retry plan without mutating bead state.

Non-goals:

- Do not add a new bead status or attempt table.
- Do not auto-reset `in_progress` beads back to `open`; `in_progress` is still a valid claimed state for phase work.
- Do not auto-kill live prior phase agents. If a live name collision exists, the command should refuse and tell the user
  to kill or dismiss the conflicting agent deliberately.
- Do not change the broad semantics of manual explicit `%name:<name>` claims outside this bead workflow.

## Design

### 1. Make the ready flag idempotent for `work`

Keep `mark_ready_to_work()` strict for direct API callers, but change `handle_bead_work()` so an already-ready plan is
not a fatal error.

Flow:

1. Load the target issue.
2. Reject non-plan targets as today.
3. Build the current `EpicWorkPlan`.
4. Check name collisions for the plan.
5. On live launch:
   - If `issue.is_ready_to_work` is false, call `proj.mark_ready_to_work(args.id)`.
   - If `issue.is_ready_to_work` is true, skip the mark call and continue.

This keeps the ready flag meaningful ("this epic has entered the work automation flow") without using it as a one-shot
lock. Rollback should only unmark the flag if this invocation flipped it from false to true; a retry that started with
the flag already true should not clear it on a launch failure.

Implementation detail: track `marked_ready_this_run: bool` and pass it to rollback.

### 2. Preserve current non-closed phase selection

`build_epic_work_plan()` already selects:

```python
c.status != Status.CLOSED
```

That behavior should remain. Add explicit tests documenting that `Status.IN_PROGRESS` phases are included, because this
is the recovery-critical behavior and should not regress.

The dependency behavior also stays right:

- A closed phase dependency is satisfied and does not produce `%w`.
- A non-closed in-epic dependency becomes a wait edge if both phases are included in the retry plan.
- A non-closed out-of-epic dependency remains an error.

### 3. Rework collision detection for retry semantics

Introduce a bead-work-specific helper that reports only live blocking names, for example:

```python
def _find_live_name_collisions(plan: EpicWorkPlan) -> dict[str, str]:
    ...
```

This should treat an agent name as blocking only when the matching artifact has no `done.json` and its process is still
alive. Terminal prior attempts should not block the retry. There are two reasonable implementation options:

- Add a sibling helper in `sase.agent.names`, such as `get_live_agent_name_map()`, next to
  `get_active_agent_name_map()`.
- Keep the live-only scan local to `src/sase/bead/cli.py` if no other caller needs it.

Prefer the shared helper if it can reuse the existing `_auto.py` scan structure without making the public API confusing.
The naming should be explicit: current `active` means "visible and reserving a name"; this new helper means "live and
unsafe to duplicate".

When a terminal failed/done agent has the canonical phase name, the new retry will still use `%name:<phase_id>`. The
explicit name claim path may rename the older terminal artifact to `<phase_id>.2` so the new attempt owns the canonical
name. That is acceptable for this recovery path: the bead id maps to the current attempt, and the older failed attempt
remains visible under a deduplicated historical name.

### 4. Pre-claim only phases in the current retry plan

Keep pre-claiming, but make sure the loop only touches `plan.waves`. This is already true, and because the plan excludes
closed phases, closed phases will not be reopened or reassigned.

For each relaunched non-closed phase:

- Set `status="in_progress"`.
- Set `assignee=<current agent name>`.
- Record enough prior state for rollback.

Rollback currently stores only the prior assignee and always restores `status="open"`. That is too destructive for
re-entry because a retried phase may have started as `in_progress`. Change the rollback tracking to store both prior
status and prior assignee:

```python
claimed: list[tuple[str, Status, str]]
```

Rollback should restore the exact prior status value and assignee for every phase this invocation touched.

### 5. Adjust rollback of the ready flag

Change `_rollback_work_launch()` to accept `unmark_ready: bool`.

- First invocation failure after flipping the flag: `unmark_ready=True`, preserving current behavior.
- Retry failure when the epic was already ready: `unmark_ready=False`, so the epic remains in the ready-to-work state.

This avoids a failed retry accidentally making the epic look like it never entered the work automation flow.

### 6. User-facing output

Keep the current summary shape, but make retry behavior clear without adding noise:

- If the epic was already ready, print a short line before the summary:
  `Epic <id> is already ready; retrying remaining non-closed phases.`
- The existing summary already states the number of phase agents and waves. Because the plan is rebuilt from current
  state, this naturally shows fewer phases after some children close.
- If no non-closed phases remain, keep raising the existing "has no open phase children" style error. Consider updating
  the wording to "has no non-closed phase children" so it matches the real status semantics.

For live collisions, keep the refusal behavior but update wording to make retry recovery actionable:

```text
Error: refusing to launch; these phase agent names are still live:
  sase-12.1 (running at ...)

Kill or dismiss those agents before retrying, or wait for them to finish.
```

`--dry-run` should warn on the same live collisions and print the retry multi-prompt without mutation.

## Test Plan

Add focused unit tests in `tests/test_bead/test_work.py`:

1. `build_epic_work_plan` includes `Status.IN_PROGRESS` child phases.
2. A closed upstream blocker is omitted and does not appear in downstream `%w`.
3. A mixed epic with one closed phase and two non-closed phases renders only the non-closed phase prompts plus land.
4. The no-work error message covers the all-closed case.

Add CLI tests in `tests/test_bead/test_cli_work.py`:

1. `test_work_allows_already_ready_epic_and_launches_remaining_phases`
   - Seed a diamond.
   - Mark the epic ready.
   - Close one phase.
   - Leave other phases `in_progress` or `open`.
   - Assert launch occurs, query excludes the closed phase, and included phases are pre-claimed.

2. `test_work_retry_does_not_unmark_already_ready_epic_on_launch_failure`
   - Mark ready before invoking.
   - Make launcher raise.
   - Assert rollback restores prior phase status/assignee and leaves `is_ready_to_work=True`.

3. `test_work_first_launch_failure_still_unmarks_ready`
   - Preserve the existing first-attempt rollback behavior.

4. `test_work_rollback_restores_prior_in_progress_status`
   - Start a phase as `in_progress` with a previous assignee.
   - Force a launch failure.
   - Assert rollback restores `in_progress` and the previous assignee, not `open`.

5. `test_work_retry_allows_terminal_same_name_attempt`
   - Write a fake colliding artifact with `done.json` and the same phase name.
   - Assert `handle_bead_work()` does not reject before launch.

6. `test_work_retry_refuses_live_same_name_attempt`
   - Write a fake colliding artifact with a live PID and no `done.json`.
   - Assert `handle_bead_work()` exits with a clear collision error and does not mutate.

7. `test_work_dry_run_retry_filters_closed_phases_without_mutating`
   - Mark ready and close one phase.
   - Assert dry-run output excludes the closed phase and includes the remaining non-closed phases.

Run focused tests first:

```bash
just install
pytest tests/test_bead/test_work.py tests/test_bead/test_cli_work.py
```

Then run the repo check required by this workspace after code changes:

```bash
just check
```

## Implementation Sequence

1. Add explicit work-plan tests for `in_progress` inclusion and mixed closed/non-closed rendering.
2. Update `handle_bead_work()` to allow already-ready epics and track whether this invocation flipped the flag.
3. Expand rollback bookkeeping to restore prior status plus assignee, and gate `unmark_ready_to_work()` on
   `marked_ready_this_run`.
4. Replace the collision check with a live-only collision check for bead work.
5. Add CLI retry tests covering already-ready launch, rollback, terminal-name retry, live-name refusal, and dry-run.
6. Run the focused test set, then `just check`.

## Risks and Open Questions

- Terminal same-name artifacts will likely be renamed by the existing explicit `%name` claim path when the retry agent
  starts. That is acceptable for recovery, but the final implementation should verify the TUI remains understandable
  with the historical failed attempt renamed to `<phase_id>.2`.
- If a prior failed agent did not write `done.json` but its process is dead, it should not block retry. The live-only
  collision scan should treat that as non-blocking, matching existing name reservation behavior for dead non-done
  artifacts.
- If the user retries while some phase agents from the previous batch are still waiting on dependencies, the live
  collision check should refuse. That is safer than launching duplicate agents for the same phase.
