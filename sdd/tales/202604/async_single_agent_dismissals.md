---
create_time: 2026-04-24 16:49:36
status: done
prompt: sdd/prompts/202604/async_single_agent_dismissals.md
---
# Make Single-Agent Dismissals Asynchronous

## Goal

Make every user-facing single-agent dismissal path in the Agents tab update the UI immediately and defer slow
filesystem/notification/workspace cleanup to an async persistence task.

The target paths are the places that dismiss one selected agent through `_dismiss_done_agent()`:

- `action_kill_agent()` for completed/dismissable agents.
- `action_kill_agent()` for agents with no PID that should be dismissed rather than process-killed.
- `_kill_and_edit_agent()` for completed/no-PID agents before showing the relaunch prompt.
- Any direct future call to `_dismiss_done_agent()`.

This plan does not broaden the request to notification-modal dismissals, task-queue dismissals, or batch "dismiss all"
behavior unless a small shared-helper adjustment is needed. Bulk marked kill/dismiss already has an async persistence
path and should continue to use it.

## Current State

`_dismiss_done_agent()` in `src/sase/ace/tui/actions/agents/_dismissing.py` still does expensive work synchronously
before removing the agent from the UI:

- Dismisses matching notifications from the JSONL store.
- Releases workflow workspace claims.
- Saves dismissed bundles.
- Deletes artifact files.
- Saves `dismissed_agents.json`, including an extra save for workflow parent children.

The UI is already updated in memory through `_apply_dismissal_in_memory()`, but that happens only after the blocking
work above.

There is already useful async persistence machinery from the recent bulk kill change:

- `_do_bulk_kill_agents()` performs optimistic in-memory removal.
- `_run_bulk_kill_persistence_async()` sends cleanup to `asyncio.to_thread()`.
- `_persist_dismiss_side_effects()` contains most of the side effects needed for completed-agent dismissals.

The main design work is to make the single-agent path use the same optimistic transaction model without creating
divergent behavior.

## Design

1. Add a single-agent dismissal transaction to `AgentDismissingMixin`.

   `_dismiss_done_agent(agent)` should become a fast preflight plus optimistic state update:
   - Validate `agent.raw_suffix`; keep the existing error notification if missing.
   - Snapshot `self._agents_with_children` before mutating it, so workflow child cleanup can run later.
   - Collect the identities dismissed by this operation, including workflow children when a workflow parent is
     dismissed.
   - Clear status/pre-question overrides for all removed identities.
   - Add all identities to `self._dismissed_agents`.
   - Append removed agent objects for same-session revive.
   - Remove the rows through the existing in-memory path.
   - Emit the same user notification text as today.
   - Schedule one async persistence callback with `call_later()`.

2. Move/reuse dismissal side-effect helpers cleanly.

   The side-effect body should live where single dismissals and bulk kill dismissals can both call it without circular
   imports or private-helper lint issues.

   Preferred shape:
   - Expose a public module-level `persist_dismiss_side_effects(agent, agents_with_children_snapshot)` from
     `_dismissing.py`.
   - Have `_killing.py` import and use that function inside `persist_bulk_kill_side_effects()`.
   - Keep low-level leaf helpers private only within their defining module.

   This keeps dismissal behavior owned by the dismissal module while allowing the bulk kill worker to share the exact
   same cleanup code.

3. Add an async runner for single dismiss persistence.

   Add `_run_dismiss_persistence_async(agent, dismissed_snapshot, agents_with_children_snapshot)` to
   `AgentDismissingMixin`.

   It should:
   - Guard duplicate work with an in-flight identity set. Prefer adding `_dismiss_persistence_inflight` in startup/core
     typing; alternatively reuse the existing persistence-inflight set only if the implementation cost of a new set is
     disproportionate.
   - Run `persist_dismiss_side_effects()` in `asyncio.to_thread()`.
   - Persist `dismissed_snapshot` with `save_dismissed_agents()` in the worker phase, so child identities are saved
     once.
   - Dismiss matching notifications in the worker phase using the batched notification helper, even for a single agent,
     to avoid repeated load/rewrite behavior.
   - On completion, refresh the notification count and schedule an async agents refresh, matching the kill persistence
     pattern.
   - On failure, notify the user with the affected agent name and leave the optimistic dismissed state intact, matching
     existing kill semantics.

4. Preserve behavior at call sites.

   `action_kill_agent()` and `_kill_and_edit_agent()` should not need behavioral rewrites because they already call
   `_dismiss_done_agent()`.

   The relaunch path should continue immediately after scheduling persistence. This is acceptable because relaunch uses
   a fresh timestamp/artifact path; waiting for artifact cleanup would reintroduce the responsiveness problem.

5. Keep batch behavior compatible.

   `_do_bulk_kill_agents()` should continue to do one optimistic UI transaction and one persistence task. If the shared
   function moves from `_killing.py` to `_dismissing.py`, update imports and tests without changing bulk semantics.

   `_do_dismiss_all()` can remain synchronous for this task unless the shared-helper refactor makes a minimal update
   cheaper and low-risk. The request is specifically about single-agent dismissal paths.

## Tests

Add or update focused tests in `tests/test_agent_dismiss_in_memory.py` and, if needed, `tests/test_agent_kill.py`:

- `_dismiss_done_agent()` removes the agent from memory before any filesystem persistence callback runs.
- `_dismiss_done_agent()` schedules exactly one async persistence callback.
- Synchronous patches for bundle saving, artifact deletion, dismissed-agent saving, workspace release, and notification
  dismissal are not called during the immediate stage.
- Running the scheduled callback calls the persistence helper, saves the dismissed snapshot, dismisses related
  notifications, refreshes notification count, and schedules an async agents refresh.
- Workflow parent dismissal removes child rows immediately and passes a pre-removal snapshot to the persistence worker.
- ChangeSpec-sourced single-agent dismissal remains optimistic and schedules persistence instead of writing
  `dismissed_agents.json` inline.
- Existing bulk kill/dismiss regression tests still pass after moving the shared persistence helper.

## Verification

Run the focused suite first:

```bash
uv run pytest -q tests/test_agent_dismiss_in_memory.py tests/test_agent_kill.py tests/ace/tui/test_agent_marking.py
```

Then follow workspace requirements:

```bash
just install
just check
```

## Risks and Mitigations

- Notification badge staleness: if notification dismissal moves to the worker, the badge may only update after
  persistence completes. Mitigate by refreshing notification count in the async runner's completion path.
- Workflow child persistence: child identities must be collected before mutating in-memory lists, and the worker needs
  the pre-removal snapshot.
- Revive support: same-session revive must still receive dismissed objects immediately; restarted revive depends on the
  worker saving bundles.
- Duplicate dismisses: guard the worker with an in-flight set so repeated keypresses do not start duplicate cleanup for
  the same identity.
- Test fakes: existing minimal mixin fakes will need `call_later()` and async-refresh counters because the dismiss path
  will schedule work rather than do it inline.
