---
create_time: 2026-05-09 19:26:37
status: wip
prompt: sdd/prompts/202605/nonblocking_agent_dismiss.md
---
# Plan: Non-Blocking TUI Agent Dismissal

## Problem

Dismissing agents from the TUI should not make the interface wait on cleanup work. The current dismissal flow already
optimistically removes rows before persistence, but dismiss-only paths still do synchronous cleanup planning on the UI
path and then schedule hidden `asyncio.to_thread` persistence work. That hidden work is not represented in the shared
background-task UI used by status transitions and other long-running operations.

This matters most for `x` on the Agents tab, marked-agent cleanup, focused-group cleanup, and dismiss-all operations:
these can touch many artifacts, dismissed bundles, workspace-release checks, notification rows, and the dismissed-agent
index.

## Goals

- Keep row removal and focus restoration immediate after the user confirms a dismiss.
- Move dismiss-only cleanup planning and filesystem/notification persistence off the UI path.
- Reuse the existing TUI background task queue where practical so users can see pending dismiss cleanup work.
- Preserve existing lifecycle semantics: dismissed agents should be hidden immediately, revivable in-session, persisted
  to `dismissed_agents.json`, bundled before artifacts are deleted, and notification counts refreshed after persistence.
- Keep kill behavior scoped: this change is about dismiss-only work. Killing a live process may still synchronously send
  the signal, while its existing persistence worker can remain a separate path unless a dismiss-only branch shares code.

## Proposed Design

1. Introduce a small dismissal persistence submission helper in the agent dismissal mixin.
   - It will accept the agent list, the dismissed-set snapshot, and the `agents_with_children` snapshot.
   - It will submit a `dismiss-agents` task through `_submit_background_task` when that API is available.
   - It will fall back to the current `call_later` / async worker path for test harnesses or nonstandard callers that do
     not mix in `TaskActionsMixin`.
   - It will use a unique operation key, while `_dismiss_persistence_inflight` continues to prevent duplicate
     persistence for the same identities.

2. Remove synchronous dismiss-only cleanup planning from the keypress path.
   - `_dismiss_done_agent`, `_dismiss_planned_agent`, and `_do_dismiss_all` should derive immediate hidden identities
     from the current in-memory agent snapshot.
   - The background task can run the existing fallback persistence transaction without a precomputed cleanup plan.
   - This avoids calling the Rust cleanup planner synchronously for simple DONE/FAILED dismissal.

3. Route dismiss-only bulk cleanup from `x` through the non-blocking dismissal helper.
   - Marked/group/custom cleanup that resolves to only dismissable agents should still remove rows immediately and
     submit one background persistence task.
   - Mixed kill+dismiss flows can keep the existing bulk kill path for now, because sending signals is the user-visible
     operation there. If the selected set has no killable agents, it should use the dismiss-only path to avoid the
     synchronous bulk kill cleanup plan.

4. Keep UI state optimistic and consistent.
   - Capture `agents_with_children` and dismissed snapshots before mutating lists.
   - Update `_dismissed_agents`, clear status overrides, append same-session revive objects, remove rows, clear relevant
     marks, and notify immediately.
   - Track in-flight dismiss persistence identities before submitting the background task, and clear them in the task
     completion callback or fallback worker.

5. Background task behavior.
   - The task body should call `persist_bulk_dismiss_transaction(...)` with `cleanup_plan=None`, then return a concise
     success/failure message.
   - On task success, refresh notification count asynchronously or schedule the existing async refresh if available.
   - On task failure, show an error via the task queue’s normal failure notification and schedule an agents refresh so
     disk state can reconcile with optimistic UI state.

6. Tests and verification.
   - Add or update regression tests proving dismiss-only `x`/bulk dismiss does not call cleanup planning or persistence
     synchronously.
   - Assert one background task/persistence submission is made for batch dismissal.
   - Preserve existing fast-path row removal, focus restoration, panel scoping, lifecycle, and revive tests.
   - Run targeted pytest for agent dismissal/kill tests first, then `just install` and `just check` before finishing.

## Risks

- `_submit_background_task` currently always reloads/repositions after task completion. This is acceptable for a first
  pass, but if it causes visible churn, add an optional `reload_on_complete` flag to `TaskActionsMixin` rather than
  reintroducing hidden workers.
- Existing tests use minimal mixin harnesses without `TaskActionsMixin`; the fallback path should keep those harnesses
  simple and avoid forcing full Textual app setup into unit tests.
- Concurrent dismiss operations must not overwrite newer dismissed-set state. The implementation should preserve the
  current snapshot discipline and avoid re-reading mutable live state inside the worker.
