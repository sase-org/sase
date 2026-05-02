---
create_time: 2026-04-24 16:51:00
status: wip
prompt: sdd/prompts/202604/fast_plan_approval.md
---
# Fast Plan Approval From The TUI

## Problem

Pressing `a` in the plan review modal currently dismisses the modal and then runs the full plan-approval side-effect
chain synchronously on the Textual event loop. The code path is:

- `PlanApprovalModal.action_approve()` returns `PlanApprovalResult(action="approve")`.
- `handle_plan_approval(...).on_dismiss()` in `src/sase/ace/tui/actions/agents/_notification_modals.py` handles that
  result.
- The dismiss callback writes `plan_response.json`, may copy and format the plan into `.sase/plans/YYYYMM`, marks the
  notification dismissed, persists `plan_approved` into `agent_meta.json`, updates status overrides, and calls
  `app._load_agents()`.

That callback includes several operations that can noticeably block a TUI keypress:

- Importing and running `format_with_prettier()` for the best-effort plan copy.
- Resolving the primary workspace and creating sharded plan directories.
- Reading and rewriting the notifications JSONL file via `mark_dismissed()`.
- Re-reading all agent sources through synchronous `_load_agents()`.

Only one operation is latency-critical for correctness: writing `plan_response.json` so the blocked agent runner can
resume. The rest can be deferred or done through already-existing async refresh machinery.

## Goals

- Make pressing `a` feel immediate: the modal should disappear, the waiting agent should get its response promptly, and
  the TUI should remain interactive.
- Preserve existing behavior: response schema, approval statuses, plan committed/approved/epic statuses, notification
  dismissal, persistent `agent_meta.json` markers, and commit-only clipboard behavior.
- Avoid adding broad new infrastructure. Use existing app primitives such as `_refilter_agents()`,
  `_schedule_agents_async_refresh()`, `run_worker(..., thread=True)`, and `call_from_thread()` where available.
- Keep tests focused on ordering and behavior rather than timing.

## Proposed Implementation

1. Extract the approval response construction and best-effort plan archiving into small helpers in
   `_notification_modals.py`.
   - A helper should build the JSON response from `PlanApprovalResult` without touching slow dependencies.
   - A helper should perform the existing best-effort workspace plan copy:
     - resolve `project_dir`,
     - compute `.sase/plans/YYYYMM`,
     - read the source plan,
     - format with prettier,
     - add frontmatter,
     - write the destination,
     - return the saved path or `None`.

2. Reorder `on_dismiss()` for approve/epic results so the fast path is tiny.
   - Find the matching agent.
   - Write `plan_response.json` immediately, before any plan formatting or agent reload.
   - Notify that the plan response was sent.
   - Apply the in-memory status override immediately:
     - approve + `run_coder=True`: `PLAN APPROVED`
     - approve + `run_coder=False` + `commit_plan=True`: `PLAN COMMITTED`
     - approve + `run_coder=False` + `commit_plan=False`: `PLAN APPROVED`
     - epic: `EPIC APPROVED`
     - reject with feedback: `RUNNING`
   - Refresh the current in-memory agent list with `_refilter_agents()` when possible, not synchronous `_load_agents()`.

3. Move non-critical side effects into a background worker.

   The worker should do:
   - `mark_dismissed(notification.id)`.
   - `persist_plan_approved(agent, action=...)` when an agent exists.
   - The best-effort plan copy for approve/epic.

   When the worker finishes, schedule any UI-only follow-up back on the app thread:
   - For commit-only approvals, copy the saved plan path to the clipboard and show the path notification if a saved path
     exists.
   - Refresh the notification count.
   - Schedule `_schedule_agents_async_refresh()` so disk-derived state catches up without blocking the keypress.

4. Keep fallback behavior conservative.
   - If `run_worker` is unavailable, run the worker synchronously only as a fallback for non-Textual tests or unusual
     app objects.
   - If `_refilter_agents()` has no cached agent list yet, fall back to `_schedule_agents_async_refresh()` rather than
     `_load_agents()` on the keypress path.
   - Continue swallowing exceptions in the best-effort plan copy just as today, but log them at debug/warning level if
     useful.

5. Add regression coverage.

   Focused tests should verify:
   - Approving writes `plan_response.json` before the slow plan-copy helper is invoked.
   - Approving does not call synchronous `_load_agents()` on the immediate path when `_refilter_agents()` / async
     refresh are available.
   - Commit-only approval still sets `PLAN COMMITTED` and eventually copies/notifies the saved plan path when the
     background worker reports one.
   - Existing rejection and approve-with-options tests continue to pass.

## Validation

- Run the focused plan approval tests:
  - `pytest tests/test_plan_rejection_response.py tests/test_plan_approval_modal_title.py tests/test_approve_options_modal.py`
- Run broader TUI agent tests if focused tests pass:
  - `pytest tests/test_ace_tui_app.py tests/test_agent_loader.py`
- Per repo instructions, after code changes run:
  - `just install`
  - `just check`

## Expected Outcome

The approval response reaches the waiting agent as fast as before or faster, but the TUI no longer waits for prettier,
plan archive writes, notification JSONL rewrites, or a full synchronous agent reload before becoming responsive again.
The visible status should update from cached in-memory state immediately, and the heavier disk-backed refresh should
follow asynchronously.
