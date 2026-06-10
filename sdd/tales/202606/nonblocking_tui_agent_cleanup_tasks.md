---
create_time: 2026-06-09 20:45:40
status: done
---
# Nonblocking TUI Agent Kill/Dismiss Tasks

## Goal

Make Agents-tab kill/dismiss operations (`x` = `kill_agent`, `X` = `open_agent_cleanup_panel`) first-class background
tasks, mirroring the tracked launch tasks added in `eb5db8a27`. The blocking persistence work for these operations
should run in tracked task-queue workers so it is visible in the top-right task indicator and the Task Queue modal,
counted by the quit flow, and inspectable (captured output, success/error state) after completion.

The current code already keeps the heavy work off the Textual event loop: each flow performs an immediate optimistic
stage on the UI thread (cleanup planning, non-blocking process-group kill signal, in-memory row removal, toast) and then
schedules an ad hoc `asyncio.to_thread` persistence worker via `call_later`. The product gap is identical to the
pre-task-queue launch gap: these persistence workers are invisible — not registered with `TaskQueue`, not shown in the
Task Queue modal, not included in the running-task count, and silently abandoned by the quit flow even though they
mutate project files, the dismissed-agents file, the artifact index, and notification files.

There are exactly four untracked persistence workers behind `x`/`X`, all in `src/sase/ace/tui/actions/agents/`:

- `_run_kill_persistence_async` (`_killing.py`) — single focused-row kill (`x` → ConfirmKillModal → `_do_kill_agent`).
- `_run_bulk_kill_persistence_async` (`_killing.py`) — every bulk kill/dismiss path (`x` with marks, `x` on a focused
  group banner, and the `X` cleanup panel's kill-panel/kill-all/marked/group/tag/custom actions, all funneling through
  `_do_bulk_kill_agents`).
- `_run_dismiss_persistence_async` (`_dismissing.py`) — single dismiss-only cleanup (`x` on a completed agent →
  `_dismiss_planned_agent`, also reached via `_dismiss_done_agent`).
- `_run_bulk_dismiss_persistence_async` (`_dismissing.py`) — bulk dismiss-done (`X` panel's dismiss-panel-done /
  dismiss-all-done → `_do_dismiss_all`).

## Design

Reuse the tracked-task layer built for launches; do not redesign it.

- Keep the two-stage optimistic model exactly as is.
  - The immediate UI stage stays on the UI thread: confirmation modals, Rust-backed cleanup planning (in-memory, fast),
    `request_user_kill(..., wait=False, background=True)` signal dispatch, optimistic in-memory removal /
    `_apply_dismissal_in_memory`, focus restoration, and the existing "Killed …"/"Dismissed …" toasts. Kill-signal
    failures must keep gating which rows are optimistically removed, so the signal phase cannot move into the worker.
  - Only the persistence stage becomes a tracked task: the filesystem/project-file transactions currently run through
    `asyncio.to_thread` (`persist_kill_side_effects` + `save_dismissed_agents` + `sync_dismissed_agent_artifact_index`
    - `dismiss_notifications_for_agents`, `persist_bulk_kill_side_effects`, `_persist_single_dismiss_transaction`,
      `_persist_bulk_dismiss_transaction`).

- Add a TUI-local cleanup task layer mirroring `_launch_tasks.py`.
  - New `src/sase/ace/tui/actions/agents/_cleanup_tasks.py` with a frozen `CleanupTaskOutcome` (message, severity,
    notify flag, refresh-notifications flag, schedule-agents-refresh flag) and a small mixin providing
    `_submit_cleanup_task(...)` that routes a synchronous worker body through `_submit_tracked_task` with
    `reload_on_complete=False` / `notify_on_complete=False`, plus an `_on_cleanup_task_complete` callback that applies
    outcome effects on the UI thread.
  - Worker bodies run the existing synchronous transaction functions directly (they already execute on a worker thread,
    so the `asyncio.to_thread` indirection disappears). Bodies catch their own exceptions and return failure outcomes
    carrying the exact current error messages ("Kill cleanup failed for …", "Bulk kill cleanup failed: …", "Dismissed N
    agent(s) in memory, but cleanup failed: …. Refresh recommended.") and the current recovery effects (error toast,
    `_schedule_agents_async_refresh(source="kill_error_recovery"/"dismiss_error_recovery")`, notification-count refresh
    where the dismiss path does that today).
  - On success, completion stays quiet (the optimistic toast already fired) and refreshes the notification count via the
    existing off-thread refresh path.

- Task identity, dedup, and labels.
  - Use a distinct task type per flow (`kill` / `dismiss`) with display labels like `kill foo`, `dismiss foo`,
    `kill 3 agents`, `dismiss 5 agents`, and `kill 2 + dismiss 3 agents` for mixed bulk cleanups. `TaskInfo` already
    supports `display_name`, and the modal/output naming already render it.
  - Pass a unique per-submission `dedup_key` (as launch tasks do) so cleanup tasks never collide with ChangeSpec per-CL
    dedup (`get_running_for_cl`) for the same CL name.
  - Real duplicate suppression keeps using the existing identity-based inflight sets (`_kill_persistence_inflight` /
    `_dismiss_persistence_inflight`): check them at submit time on the UI thread and silently skip (today's behavior),
    and release identities in the worker body's `finally` so a Task Queue kill of a cleanup task can never permanently
    leak an inflight identity and block future kills/dismissals of the same agent.

- Preserve existing semantics and boundaries.
  - No behavior moves across the Rust-core boundary: planning and persistence helpers stay where they are; this change
    is purely TUI task tracking (`sase.ace.tui`).
  - The `x` behavior on the changespecs/axe tabs (`toggle_hide_submitted`, axe toggle/kill) and the `X` behavior on the
    axe tab (clear output) are untouched.
  - The deferred `call_later(_apply_dismissal_in_memory, ...)` toast-paint ordering in `_do_dismiss_all` is preserved;
    only the persistence scheduling changes from `call_later(coroutine)` to a tracked-task submission.
  - Other callers of the shared dismissal helpers (e.g. `_dismiss_done_agent` from non-keymap flows) inherit task
    tracking automatically since the conversion happens inside the shared `_dismiss_planned_agent` /
    `_do_bulk_kill_agents` / `_do_dismiss_all` layer.

## Implementation Steps

1. Add `src/sase/ace/tui/actions/agents/_cleanup_tasks.py`.
   - `CleanupTaskOutcome` frozen dataclass + `success` property (severity != "error"), mirroring `LaunchTaskOutcome`.
   - Cleanup task mixin with `_submit_cleanup_task(display_name, cl_name, project_file, task_callable, ...)` and
     `_on_cleanup_task_complete(completion)`; mix it into the `AgentDismissingMixin`/`AgentKillingMixin` chain.

2. Convert single-kill persistence (`_killing.py`).
   - Extract the body of `_run_kill_persistence_async` into a module-level synchronous transaction function (persist
     kill side effects, save dismissed snapshot, sync artifact index, conditional notification dismissal).
   - `_do_kill_agent` submits a tracked `kill <agent>` task instead of
     `call_later(self._run_kill_persistence_async, …)`; keep perf logging.

3. Convert bulk kill/dismiss persistence (`_killing.py`).
   - `_do_bulk_kill_agents` submits one tracked task per confirmed bulk operation wrapping
     `persist_bulk_kill_side_effects` (with cleanup-plan/recent-group arguments preserved), labeled by the kill/dismiss
     counts.

4. Convert single-dismiss persistence (`_dismissing.py`).
   - `_dismiss_planned_agent` submits a tracked `dismiss <agent>` task wrapping `_persist_single_dismiss_transaction`,
     preserving the failure path's notification-count refresh + recovery refresh.

5. Convert bulk-dismiss persistence (`_dismissing.py`).
   - `_do_dismiss_all` submits a tracked `dismiss N agents` task wrapping `_persist_bulk_dismiss_transaction`.

6. Remove the four ad hoc `_run_*_persistence_async` coroutines once call sites are converted (or keep a thin
   compatibility wrapper only where a test legitimately needs to drive the worker body directly), and move the inflight
   add/check to submit time with release in the worker `finally`.

7. Task Queue modal/indicator sanity.
   - Confirm cleanup tasks render readable labels and output, count in the indicator and quit-flow prompt, and that
     killing a cleanup task from the modal marks it killed without firing completion effects and without leaking
     inflight identities.

8. Update and add focused tests.
   - Update the suites that patch or await the old coroutines: `tests/test_agent_kill_single.py`,
     `tests/test_agent_kill_bulk.py`, `tests/test_agent_dismiss_persistence.py`,
     `tests/test_agent_dismiss_in_memory.py`, `tests/test_agent_kill_phase1_async_io.py`,
     `tests/test_agent_artifact_dismissed_save_audit.py`, plus the TUI suites `tests/ace/tui/test_agent_group_kill.py`
     and `tests/ace/tui/test_agents_tab_completion_dismiss_e2e.py`.
   - New focused tests: `x`/`X` confirm flows submit tracked tasks (visible in `TaskQueue`, no inline persistence);
     worker completion clears the running entry, refreshes the notification count, and performs no broad reload; failure
     outcomes preserve today's error toasts and recovery refreshes; duplicate submissions for an inflight identity are
     skipped; quit flow counts a running cleanup task.

9. Verify.
   - Run targeted kill/dismiss/task-queue suites, then `just install` (ephemeral workspace) and `just check`.

## Risks and Mitigations

- Killing a cleanup task from the Task Queue modal cannot undo work: the process signal and optimistic UI removal
  already happened, thread cancellation is cooperative, and persistence may have partially run. Treat task kill as "stop
  waiting": rely on the worker-`finally` inflight release and the existing error-recovery refresh; do not promise
  rollback.
- Test churn: these suites patch the old coroutines heavily. Convert one flow at a time (single kill → bulk kill →
  single dismiss → bulk dismiss), keeping the worker transaction functions directly testable so most assertions move
  rather than disappear.
- Toast ordering: completion-side toasts now flow through the tracked completion callback. Success stays silent (the
  optimistic toast is unchanged), so only failure toasts move; keep messages byte-identical to today's.
- Global stdout/stderr capture remains process-wide and can interleave across overlapping tasks — an accepted existing
  limitation of the task queue.

## Expected Outcome

Pressing `x` or `X` on the Agents tab keeps today's instant optimistic feedback, while the persistence work for each
kill/dismiss appears as a running task in the top-right indicator and Task Queue modal with a readable label (e.g.
`kill foo`, `dismiss 5 agents`), captured output, and a success/error record. Quitting the TUI warns when kill/dismiss
persistence is still in flight instead of silently abandoning half-written project-file mutations. All existing
kill/dismiss semantics — confirmation modals, optimistic removal, rollback-free signal gating, notification dismissal,
recent-dismissal groups, and error-recovery refreshes — are preserved.
