---
create_time: 2026-07-06 13:32:05
status: done
prompt: sdd/prompts/202607/tui_launch_approval_dispatch.md
---
# Fix: ACE TUI launch approval never dispatches the approved agent

## Problem

Approving an agent-initiated `LaunchApproval` from the ACE TUI records the approval but never launches the requested
agent. Live incident (2026-07-06): agent "b" requested a launch via the `/sase_run` skill; the user approved it in the
TUI; no agent was spawned.

On-disk evidence from the incident (`~/.sase/launch_requests/launch-1e533782-9064-4450-a1c7-8c58e2e8fa30/`):

- `launch_response.json` contains only `{"action": "approve"}` — no `dispatch_status` / `launched_count` keys.
- Per the `/sase_run` skill contract (`src/sase/xprompts/skills/sase_run.md`), the requesting agent only polls
  `launch_response.json` and must NOT spawn agents itself. An approved response is supposed to look like
  `{"action": "approve", "dispatch_status": "launched", "launched_count": 1}` — dispatch is the approving host surface's
  job.

## Root cause

Commit `deaf571e0` ("feat: add approved agent launch requests (sase-5g.8)") added host-side dispatch to the shared
approval action `execute_launch_approval_response()` (`src/sase/launch_approval_actions.py`): on approve it writes the
response file, calls `dispatch_approved_launch_request()` (`src/sase/agent/launch_request.py`), and rewrites the
response with `dispatch_status`/`launched_count` (or `dispatch_status: "failed"` + `dispatch_error` on failure).

Two of the three approval surfaces go through that shared action:

- CLI: `sase launch approve` → `src/sase/main/launch_handler.py` ✓
- Mobile/Telegram: `src/sase/integrations/_mobile_notification_actions.py` ✓
- **ACE TUI: ✗** — `handle_launch_approval()` in `src/sase/ace/tui/actions/agents/_notification_modals.py` predates
  sase-5g.8 (from the sase-5g.7 pending-action infrastructure). Its `on_dismiss` callback hand-writes
  `launch_response.json` via `write_workflow_action_response()` and runs only `run_launch_side_effects()` (dismiss +
  mark-handled). It never calls `execute_launch_approval_response()`, so no dispatch ever happens.

The hand-written `{"action": "approve"}` file exactly matches the incident artifact, confirming the approval went
through the TUI path. A side effect of the bug: the notification is dismissed and the response file exists, so the
request cannot simply be re-approved afterwards (the shared action treats an existing response as
`conflict_already_handled`).

## Fix design

Route the TUI approval through the same shared action the CLI and mobile surfaces use, and run it off the event loop as
a tracked background task (agent launches are multi-second work — see the TUI perf rules; long-memory `tui_perf.md` rule
2 explicitly names agent launches and prescribes `_submit_tracked_task()` with the `LaunchTaskMixin` shape).

### Changes in `src/sase/ace/tui/actions/agents/_notification_modals.py`

Rework `handle_launch_approval()`'s `on_dismiss`:

1. **Keep the UI stage fast.** On modal dismissal with a `LaunchApprovalResult`, show an optimistic toast (e.g.
   "Approving launch…" / "Rejecting launch…") and submit a tracked task; do no disk I/O on the keypress path.
2. **Worker body (thread):** call
   `execute_launch_approval_response(launch_context_from_notification(notification), result.action, feedback=result.feedback)`.
   This single call:
   - writes `launch_response.json` once (open-mode `x` conflict detection preserved),
   - dispatches the launch on approve and updates the response with `dispatch_status`/`launched_count` (or `failed` +
     `dispatch_error`),
   - runs the dismiss/mark-handled side effects (so the current direct `write_workflow_action_response` +
     `run_launch_side_effects` calls are removed, not duplicated). Return a typed success/failure outcome carrying the
     action result's `message` ("Launch approved and dispatched N agents" / "Launch rejected").
3. **Completion (UI thread):** toast the outcome message (error severity on failure), refresh the notification count
   (existing `_refresh_notification_count` hook), and on a successful approve request an agents refresh through the
   existing fast path (`request_agents_refresh` / `_schedule_agents_async_refresh`) so the newly launched agent row
   appears without a manual refresh.
4. **Error mapping:** catch `LaunchApprovalActionError` in the worker body and surface its message;
   `conflict_already_handled` should read as a warning ("launch request was already handled"), `dispatch_failed` as an
   error. The response file still ends up with `dispatch_status: "failed"` so the polling requester agent sees the
   failure too.
5. **Submission mechanics:** submit via the app's tracked-task API (task type `"launch"`, dedup key derived from the
   notification/request id so double-pressing approve can't dispatch twice). Follow the existing `LaunchTaskMixin` /
   `_start_plan_approval_background_worker` conventions in this area: resolve app hooks with `getattr(...)` and fall
   back to synchronous execution when the tracked-task API is unavailable (keeps dummy-app unit tests working). Display
   fields (cl name / project file) can be taken from the launch request payload read inside the worker body, with safe
   placeholders when absent.

Reject flows keep their current semantics (`{"action": "reject"}`, optional feedback) — the shared action produces
identical JSON for those; it simply becomes the single writer.

### Non-goals / boundaries

- No change to `execute_launch_approval_response()`, the dispatch logic, the CLI, or the mobile path — they already
  behave correctly. This is presentation-layer wiring, so no Rust core (`sase-core`) change is needed: the shared
  host-side behavior already lives in `sase.launch_approval_actions` and is reused as-is.
- The `LaunchApprovalModal` itself is unchanged (approve/reject/cancel keys, preview render).
- The known pre-existing quirk that `dispatch_approved_launch_request()` briefly `os.chdir()`s the process is unchanged;
  it is the same behavior the mobile surface already has. If it ever becomes a problem for TUI worker threads, a
  follow-up can thread an explicit cwd through `launch_agents_from_cwd`.

## Tests

Add coverage for the TUI surface (none exists today — `tests/test_launch_approval.py` covers only the shared action,
CLI, and mobile paths):

1. **Approve dispatches:** driving `handle_launch_approval`'s dismiss callback with an approve result (using a dummy app
   and a monkeypatched launcher, mirroring `test_approve_launch_response_dispatches_stored_request`) launches the stored
   request and leaves `launch_response.json` with `dispatch_status: "launched"` and `launched_count`.
2. **Reject does not dispatch:** the reject path writes `{"action": "reject"}` (with feedback when provided) and never
   invokes the launcher.
3. **Already-handled conflict:** with a pre-existing `launch_response.json`, approving surfaces a warning toast and does
   not dispatch a second time.
4. **Dispatch failure:** a launcher that raises produces an error toast and a response file with
   `dispatch_status: "failed"` + `dispatch_error`.

Run `just check` (and the focused tests above) before finishing.

## Remediation for the missed launch

The incident request (`launch-1e533782…`, the `actstat` GHA-failure planning agent) cannot be re-approved: its
notification is dismissed and its response file already exists. After the fix lands, re-issue it from the stored payload
— e.g. re-run `sase launch request` with the prompt recorded in that directory's `launch_request.json`
(`dispatch.prompt`) and approve the fresh request — or simply let agent "b" (or the user) re-request it.
