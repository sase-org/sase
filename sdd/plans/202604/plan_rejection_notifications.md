---
status: done
---

# Plan: Stop Treating Plan Rejection as Agent Failure

## Problem

Rejecting a `%plan` agent from Telegram writes `{"action": "reject"}` into the plan approval response file. The runner
correctly interprets that as `plan_rejected`, but the outer agent runner only receives `success=False`. It then sends
the normal user-agent completion notification with text like `CODEX(gpt-5.5) @name failed: ...`. Telegram faithfully
formats that core notification, so the user sees a failure notification even though rejection is an intentional human
decision.

There is a second related status problem: `done.json` records `outcome: plan_rejected`, but the done-agent loader treats
any non-`failed` outcome as `DONE`. A `.plan` workflow with no follow-up is then re-labeled as `PLANNING`, which can
make a rejected plan look like it is still awaiting approval.

## Root Cause

The execution loop preserves a specific terminal outcome (`plan_rejected`), but the public result object collapses it
into a boolean `success`. Downstream notification, exit status, metrics, and status rendering cannot distinguish user
rejection from real agent failure.

## Approach

1. Preserve the execution-loop outcome in `_AgentExecResult`.
   - Add an `outcome` field populated from `state.loop_outcome`.
   - Keep `success` for existing callers, but make intent explicit for plan rejection.

2. Classify `plan_rejected` as a non-error terminal outcome at the runner boundary.
   - After `run_execution_loop()`, set `success=True` for `outcome == "plan_rejected"` so the process exits cleanly and
     does not produce failure metrics.
   - Suppress the generic completion notification for `plan_rejected`, because the user already acted on the plan
     approval notification and a second "complete" message adds noise.
   - Keep real failures and user kills unchanged.

3. Render rejected plans as their own terminal status.
   - Update done-agent loading to map `outcome == "plan_rejected"` to `PLAN REJECTED`.
   - Include `PLAN REJECTED` in completed/dismissable status handling where the TUI currently treats `DONE`, `FAILED`,
     `PLAN DONE`, and `PLAN COMMITTED` as terminal.
   - Avoid the existing `DONE -> PLANNING` override for rejected plan workflows.

4. Add focused regression tests.
   - Unit-test `_send_completion_notification` or runner notification gating so `plan_rejected` does not call
     `notify_workflow_complete`.
   - Unit-test `_AgentExecResult`/runner classification so `plan_rejected` is non-error while real failure remains
     error.
   - Unit-test done-agent loading/status overrides so a rejected plan becomes `PLAN REJECTED`, not `FAILED` and not
     `PLANNING`.

5. Verify.
   - Run the targeted tests for runner notification behavior, execution-loop plan handling, and agent loader status
     overrides.
   - Run `just install` if needed, then `just check` before finishing because this repo requires it after code changes.

## Non-Goals

- Do not change Telegram callback semantics; it is already writing the correct reject response.
- Do not hide real agent failures or feedback-based replanning failures.
- Do not change plan approval, commit, or epic behavior.
