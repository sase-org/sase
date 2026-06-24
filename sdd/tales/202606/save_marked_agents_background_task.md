---
create_time: 2026-06-24 12:23:39
status: done
prompt: sdd/prompts/202606/save_marked_agents_background_task.md
---
# Plan: Route the `s` (save marked agents) persistence through the tracked-task background queue

## Problem / product context

On the ACE TUI **Agents** tab there are two destructive bulk keymaps:

- **`x`** — kill/dismiss the marked (or focused) agents.
- **`s`** — kill/dismiss the marked agents **and** save them to a revivable group that shows up on the "Agent Restore"
  panel (the `SaveAgentGroupModal` → saved-group revival flow).

Both keymaps do the same kind of "slow work": writing the dismissed-agents index and (for `s`) the saved-group archive
to disk, syncing the artifact index, and refreshing notification state. This is real file I/O and should never run on
the UI thread.

The `x` path (kill **and** dismiss) routes this slow work through the app's **central tracked-task queue**: it builds a
worker that returns a `CleanupTaskOutcome` and submits it via `_submit_cleanup_task`. That gives it:

- a row in the task indicator / task-queue modal (the spinner count the user can see),
- uniform completion + error handling (toast on failure, notification-count refresh on success),
- inflight de-duplication, and
- the ability to be observed/killed like any other background task.

The `s` path is the **odd one out**. Instead of the tracked-task queue, it offloads its persistence with an ad-hoc
`call_later(...)` → `asyncio.to_thread(...)` coroutine. The work does run off the UI thread, but it is **not a tracked
background task**: it never appears in the task queue/indicator, it has bespoke (duplicated) error and refresh handling,
and it diverges from every other agent kill/dismiss path.

This is the inconsistency the user observed. The single-agent dismiss path (`x` on a completed agent) and the bulk
dismiss path already use the tracked-task queue — only the marked-group **save** path was left on the old ad-hoc
mechanism.

**Goal:** make the `s` save path submit its persistence through the same tracked-task queue the `x`/dismiss paths use,
removing the one-off `call_later` + `asyncio.to_thread` mechanism, with no user-visible behavior regressions (same
toasts, same optimistic in-memory hide, same error recovery).

## Scope boundary (Rust core)

This change is presentation/glue only: it swaps **which Python background mechanism wraps the persistence call**. The
actual persistence logic (`_persist_marked_agent_group_save`, which writes the dismissed index, saved-group archive,
recent-group record, and artifact-index sync) is unchanged and stays where it is. No Rust core / `sase_core_rs` wire or
binding changes are required.

## Current state (where the code lives)

- Keymap binding: `s` → action `save_marked_agents` (TUI bindings).
- Action handler: `action_save_marked_agents` → `_prompt_and_save_marked_agent_group` (shows `SaveAgentGroupModal`) → on
  confirm, `_save_marked_agent_group(...)` in `src/sase/ace/tui/actions/agents/_marking.py`.
- `_save_marked_agent_group` does the optimistic in-memory work (build saved-group wire with
  `resolve_bundle_paths=False`, cache the recent dismissed group, clear status overrides, mark identities dismissed,
  `_apply_dismissal_in_memory`, show the "Saved and dismissed N agents" toast) and then **schedules the slow
  persistence** via:
  ```python
  self.call_later(self._run_marked_agent_group_save_persistence_async, ...)
  ```
- `_run_marked_agent_group_save_persistence_async` (same file) is the ad-hoc coroutine to delete. It manages
  `_dismiss_persistence_inflight`, runs `_persist_marked_agent_group_save` via `asyncio.to_thread`, notifies on
  failure + `_schedule_agents_async_refresh(source="mark_error_recovery")`, and on success awaits
  `_refresh_notification_count_async()`.

### The model to copy (the `x`/dismiss tracked-task pattern)

- `CleanupTaskMixin._submit_cleanup_task(...)` (`_cleanup_tasks.py`) wraps a `() -> CleanupTaskOutcome` worker into a
  `TrackedTaskResult` and submits it through `_submit_tracked_task` (which runs it in a Textual worker thread via
  `run_worker(thread=True)` and updates the task indicator). Its completion handler `_on_cleanup_task_complete` already
  maps a `CleanupTaskOutcome` onto: optional toast (`notify`/`severity`), optional
  `_schedule_agents_async_refresh(source=...)`, and an off-thread `_refresh_notification_count_async` when
  `refresh_notifications=True`.
- `_submit_dismiss_persistence_task` (`_dismissing.py`) is the closest existing analog: it guards on
  `_dismiss_persistence_inflight`, builds a `_worker()` that returns a `CleanupTaskOutcome` (success message +
  `refresh_notifications=True`; on exception, error message + `notify=True` +
  `schedule_agents_refresh_source="dismiss_error_recovery"`), releases inflight in `finally`, and releases inflight
  again on the UI thread if `_submit_cleanup_task` rejects the submission.

All of `AgentMarkingMixin`, `CleanupTaskMixin`, `AgentKill/DismissPersistenceTaskMixin`, and `TaskActionsMixin` are
composed into the same `AceApp`, so `_submit_cleanup_task` is already available from within `AgentMarkingMixin`.

## Proposed change

### 1. Add a tracked-task submission method for the marked-group save

In `src/sase/ace/tui/actions/agents/_marking.py`, add a method on `AgentMarkingMixin` (mirroring
`_submit_dismiss_persistence_task`), e.g.
`_submit_marked_group_save_persistence_task(agents, dismissed_snapshot, added, group, group_name)` that:

- Computes `identities = {a.identity for a in agents}`; if `identities & self._dismiss_persistence_inflight`, return
  (same guard the old coroutine used); otherwise `self._dismiss_persistence_inflight.update(identities)`.
- Defines a `_worker() -> CleanupTaskOutcome` that:
  - calls `_persist_marked_agent_group_save(agents, dismissed_snapshot, added, group, group_name)` (unchanged body),
  - on exception returns
    `CleanupTaskOutcome(message="Saved N <agents> in memory, but group archive failed: ... Refresh recommended.", severity="error", notify=True, schedule_agents_refresh_source="mark_error_recovery")`
    (preserving the exact current error UX),
  - in `finally`, `self._dismiss_persistence_inflight.difference_update(identities)` and keep the existing
    `log.debug("marked agent group save persistence: count=%d elapsed=%.3fs", ...)` timing line,
  - on success returns `CleanupTaskOutcome(message="Saved N <agents>", refresh_notifications=True)` (the
    `refresh_notifications=True` reproduces the old success-path `_refresh_notification_count_async()`).
- Submits via
  `self._submit_cleanup_task(task_type="save", display_name=f"save N <agents>", cl_name="", project_file="", task_callable=_worker)`;
  if it returns `False`, `difference_update` the inflight set back out (matching the dismiss path's rejection cleanup).

Reuse `plural_agent(count)` for the messages/labels, consistent with the existing save toast.

Notes on faithfulness:

- The success outcome is **not** toasted: `_submit_cleanup_task` sets `notify_on_complete=False`, and
  `_on_cleanup_task_complete` only toasts when `outcome.notify` is true. The user-facing "Saved and dismissed N agents"
  toast continues to come from the synchronous `_notify_after_refresh` call in `_save_marked_agent_group`, so there is
  no double-toast and no change to the success UX.
- The inflight set is mutated inside the worker's `finally` (worker thread) exactly as the existing kill/dismiss
  tracked-task workers already do — this is the established pattern, not a new concurrency assumption.

### 2. Switch `_save_marked_agent_group` to the tracked-task call

Replace the `self.call_later(self._run_marked_agent_group_save_persistence_async, ...)` block at the end of
`_save_marked_agent_group` with a direct call to
`self._submit_marked_group_save_persistence_task(list(agents), snapshot_dismissed_agents(self._dismissed_agents), added, group, normalize_saved_group_name(group_name))`.
The optimistic in-memory steps and the "Saved and dismissed N agents" toast above it are unchanged.

### 3. Remove the now-dead ad-hoc coroutine and unused imports

- Delete `_run_marked_agent_group_save_persistence_async`.
- Add `from ._cleanup_tasks import CleanupTaskOutcome`.
- Drop the now-unused `import asyncio` from `_marking.py` (confirm no other use remains in the file).
- Keep the module-level `_persist_marked_agent_group_save` function as-is — it is still the worker body and is also
  referenced by the dismissed-agent save-audit test.

## Tests

### Update the marking-save test harness

`tests/ace/tui/_agent_marking_helpers.py` `_FakeMarkApp` currently fakes the old mechanism (`call_later` recorded into
`_scheduled`, async callbacks run by `asyncio.run`). Update it to support the tracked-task path:

- Add `CleanupTaskMixin` and `TrackedTaskRecorderMixin` (from `tests/_agent_cleanup_task_helpers.py`) to its bases so
  `_submit_cleanup_task` routes into the recorder's `_submit_tracked_task`.
- Call `self._init_tracked_task_recorder()` in `__init__`.
- It already provides `notify`, `call_later`, `_schedule_agents_async_refresh`, and `_refresh_notification_count_async`,
  which is everything `_on_cleanup_task_complete` + `run_tracked_task` need.

### Update the save tests

In `tests/ace/tui/test_agent_marking_save.py`, the tests that currently read `app._scheduled` and run the coroutine via
`asyncio.run(callback(*args))` (e.g. `test_save_marked_running_agents_hides_without_kill`,
`test_save_marked_group_persists_refs_in_display_order`, `test_blank_save_preserves_generated_group_title`) should
instead assert that exactly one tracked task was submitted (`len(app.tracked_tasks) == 1`, with the expected
`task_type`/`display_name`), and drive completion via `run_tracked_task(app, app.tracked_tasks[0])` — mirroring the
kill/dismiss tracked-task tests in `tests/ace/tui/test_agent_cleanup_tasks.py`.

### Add coverage that locks in the fix

Add a focused test (in `test_agent_marking_save.py` or `test_agent_cleanup_tasks.py`) asserting the save path:

- submits a single tracked task and leaves **no** `call_later` coroutine scheduled for persistence (the regression guard
  — same shape as the kill/dismiss "schedules once, no `call_later`" tests),
- marks identities into `_dismiss_persistence_inflight` on submit and releases them after the worker runs,
- on worker success refreshes the notification count off-thread and does not emit a second toast,
- on worker failure emits the "... group archive failed ... Refresh recommended." error toast and schedules the
  `mark_error_recovery` agents refresh.

### Audit / unchanged tests

- `tests/test_agent_artifact_dismissed_save_audit.py` references `_persist_marked_agent_group_save`; since that function
  is unchanged, the audit should continue to pass (verify).
- The e2e revival tests (`tests/test_agent_group_revival_e2e.py`) drive the real app and should be unaffected, but must
  be re-run to confirm the save→revive flow still works end-to-end.

## Verification

- `just install` (ephemeral workspace may have stale deps), then `just check`.
- Run the targeted suites: `tests/ace/tui/test_agent_marking_save.py`, `tests/ace/tui/test_agent_marking.py`,
  `tests/ace/tui/test_agent_cleanup_tasks.py`, `tests/test_agent_group_revival_e2e.py`, and
  `tests/test_agent_artifact_dismissed_save_audit.py`.
- Manual smoke (optional): on the Agents tab, mark several agents, press `s`, name the group, and confirm the
  task-indicator count briefly increments (the save now appears as a tracked background task) and the group shows up on
  the Agent Restore panel.

## Out of scope

- No change to the persistence logic itself, the saved-group wire format, or the revival/Agent-Restore UI.
- No Rust core changes.
- No change to the `x` kill/dismiss paths (already correct); this only brings `s` into parity with them.
