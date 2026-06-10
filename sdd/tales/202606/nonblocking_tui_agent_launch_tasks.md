---
create_time: 2026-06-09 19:40:02
status: done
prompt: sdd/prompts/202606/nonblocking_tui_agent_launch_tasks.md
---
# Nonblocking TUI Agent Launch Tasks

## Goal

Make TUI agent launches first-class background tasks so launch preparation, single-agent spawn, and fanout spawn work
never needs to block the Textual event loop and is visible in the top-right task indicator and Task Queue panel.

The current code already moved most launch work off the UI thread with `asyncio.to_thread`, including single launch,
multi-prompt, prompt fanout, repeat fanout, and bulk launch. The remaining product gap is that these launch workers are
ad hoc: they show toast notifications and schedule refreshes, but they do not register with the central `TaskQueue`,
cannot be inspected from the Task Queue modal, and are not included in the running-task count or quit flow.

## Design

Use the existing TUI task infrastructure as the launch orchestration surface:

- Extend `TaskQueue`/`TaskInfo` enough to represent non-ChangeSpec work cleanly.
  - Preserve the existing per-CL dedup behavior for sync/mail/status/rebase/etc.
  - Add an optional task key or dedup scope so launch tasks can either dedup by a launch identity or intentionally allow
    concurrent launches for different prompts/fanout groups.
  - Add a display label separate from `cl_name` so the Task Queue can show entries like `launch foo`,
    `launch fanout foo`, or `launch bulk 4 CLs` without abusing ChangeSpec names.

- Generalize the TUI background-task submit helper.
  - Keep the current `_submit_background_task(...) -> bool` API stable for existing callers.
  - Add an internal richer helper that can run a callable in a Textual worker thread, capture stdout/stderr, complete a
    `TaskInfo`, and pass a typed result object to a completion callback on the UI thread.
  - Completion callbacks should be able to schedule exact artifact-delta refreshes from returned `AgentLaunchResult`
    lists.

- Route TUI launch entry points through task-queue workers.
  - Single launch: `_finish_agent_launch` should still unmount the prompt bar immediately, notify the user, and then
    submit a `launch` task instead of scheduling `_run_agent_launch_body_async` as a separate untracked async wrapper.
  - Multi-prompt, prompt fanout, repeat fanout, and bulk launch should submit tracked launch tasks around their existing
    worker bodies.
  - Launch body dispatch should return structured results instead of relying only on nested `call_later` side effects
    where practical. Keep UI mutations on the UI thread.

- Preserve existing launch semantics.
  - Keep all blocking VCS resolution, history writes, xprompt expansion, workspace allocation, naming waits, and
    subprocess spawn work off the event loop.
  - Preserve partial-launch rollback for multi-prompt/fanout errors.
  - Preserve exact artifact-delta refresh behavior by calling `_handle_launch_results_delta(results)` once per completed
    launch task.
  - Preserve persistent fanout failure notifications and notification-count refreshes.
  - Do not move shared launch behavior into the TUI. Core execution stays in `sase.agent.*` and `sase.core.*`; only UI
    task tracking belongs in `sase.ace.tui`.

## Implementation Steps

1. Update `src/sase/ace/tui/task_queue.py`.
   - Add optional fields for `display_name` and `dedup_key`.
   - Keep `cl_name` and `get_running_for_cl()` compatibility for existing tests/callers.
   - Add `get_running_for_key()` or equivalent for generic task dedup.

2. Update `src/sase/ace/tui/actions/task_actions.py`.
   - Add a generic tracked-task submission helper that returns the created `TaskInfo` or `None`.
   - Keep `_submit_background_task` as a compatibility wrapper for existing ChangeSpec operations.
   - Ensure worker success/error paths complete the queue entry, update the indicator, fire typed completion callbacks,
     and avoid broad reloads when the task provides its own UI refresh behavior.

3. Add launch-task result types in the TUI launch package.
   - Represent outcomes such as launched results, user-visible message, warning/error severity, notification refresh
     request, and whether a broad agents refresh is needed.
   - Keep these types TUI-local so core launch code remains frontend-neutral.

4. Refactor launch dispatch.
   - Single launch body should produce a launch-task outcome instead of directly completing through scattered callbacks
     where feasible.
   - Fanout helpers should use the tracked task helper and call their existing worker bodies from the worker thread.
   - On success, the task completion callback should call `_handle_launch_results_delta(results)` and then toast the
     final message.
   - On failure, the task should show the same error toast and preserve any rollback/failure-report side effects
     currently performed by the worker bodies.

5. Update Task Queue display.
   - Render `display_name` when available.
   - Make launch task rows and output readable for single and fanout launches.
   - Confirm kill/dismiss behavior remains sane for Textual workers. Launch tasks can be cancelled before/while
     preparing; already-spawned detached agents are not killed by cancelling the launch task unless the worker-specific
     rollback path already owns that behavior.

6. Add focused tests.
   - TaskQueue compatibility: old per-CL behavior still passes; new display/dedup-key behavior works.
   - `_finish_agent_launch` submits a tracked launch task and does not call the body inline.
   - Launch worker completion updates the queue and schedules exact artifact-delta refresh.
   - Fanout launch task submissions appear as running tasks and batch results into one delta refresh.
   - Event-loop nonblocking tests continue to prove the launch body runs off-thread.
   - Existing fanout partial-failure tests continue to prove rollback and persistent notifications.

7. Verify.
   - Run targeted tests for task queue and TUI launch dispatch/nonblocking/fanout.
   - Run `just install` if needed, then `just check` because implementation changes modify repo files.

## Risks and Mitigations

- Global stdout/stderr capture is process-wide. The existing task queue already uses it; launch tasks may overlap with
  other tasks, so captured output can interleave. Keep this as an existing limitation for now unless tests expose a
  regression.
- Cancelling a launch worker cannot reliably undo detached subprocesses after spawn. Do not promise that Task Queue `K`
  kills launched agents; it should cancel still-running launch preparation and rely on existing partial-launch rollback
  where present.
- The existing launch body mixes dispatch decisions and UI callbacks. Refactoring too broadly would increase risk. Keep
  the first implementation incremental: task-track the worker boundary, return result lists where straightforward, and
  leave deeper launch-core cleanup for later.

## Expected Outcome

Launching agents from the TUI should immediately return control to navigation and input, show a running task in the
top-right indicator and Task Queue panel, stream/capture launch output where available, and complete by scheduling the
same exact agent artifact refreshes currently used after successful launches. Fanout launch work should appear as one
task per user-submitted launch, not as a blocking UI operation and not as a burst of unrelated broad refreshes.
