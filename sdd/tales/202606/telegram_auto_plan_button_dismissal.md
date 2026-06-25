---
create_time: 2026-06-25 15:38:04
status: done
prompt: sdd/prompts/202606/telegram_auto_plan_button_dismissal.md
---
# Telegram Auto-Approved Plan Button Dismissal

## Context

Plan approval actions are represented in SASE as `PlanApproval` notifications with a file-based response protocol under
the notification's `response_dir`. Telegram turns those notifications into inline keyboard messages and stores callback
context in its legacy `~/.sase/telegram/pending_actions.json` file. The SASE core repo also has a newer shared pending
action store at `~/.sase/pending_actions/actions.json` with a `transports` field, but Telegram does not currently
register its sent message there.

The normal Telegram callback path removes its own inline keyboard after a button press. The TUI and CLI paths write the
same response file and dismiss the SASE notification, and Telegram's inbound chop has a compatibility scan that clears
legacy buttons when it can see that the response file, approval marker, or missing request file means the action was
handled elsewhere.

The fragile gap is cross-surface cleanup, especially for agents launched with `%auto`:

- The plain `%auto` and `%auto:tale` / `%auto:epic` path can approve a plan outside the Telegram callback path.
- The current auto-approval path normally skips creating a new PlanApproval notification, but stale Telegram plan
  messages can still exist for the same plan or agent because Telegram's durable record lives outside the shared
  pending-action store.
- Once such a plan has been approved elsewhere, Telegram should remove the inline keyboard so later button presses
  cannot attempt to approve or reject an already-resolved plan.

This should be fixed as a transport-state problem, not by making core SASE know how to call Telegram.

## Goals

1. Make Telegram inline plan-approval keyboards disappear when the corresponding SASE plan action is resolved outside
   Telegram, including auto-approved `%auto` plans.
2. Preserve the existing file-response protocol and current Telegram callback behavior.
3. Keep SASE core independent from the Telegram plugin.
4. Keep legacy pending Telegram records working during the migration.
5. Add regression tests that pin both the `%auto` scenario and the generic "already handled before callback" behavior.

## Plan

1. Establish the exact failing contract with tests first.
   - In the SASE core tests, model a PlanApproval pending action that has a Telegram transport record and then gets
     resolved by an auto-approval path for the same `plan_file` and agent identity.
   - In `sase-telegram`, model a pending Telegram plan message whose shared pending-action state is already handled
     before inbound polling or before a button callback arrives.
   - Keep a legacy-only test so old `~/.sase/telegram/pending_actions.json` records continue to be cleaned up by the
     existing response-file/marker checks.

2. Promote Telegram message metadata into the shared pending-action store.
   - Add a small public helper in `sase.notifications.pending_actions` that merges a transport record into an existing
     action entry by notification id or prefix. The record should contain only transport-owned data such as `chat_id`
     and `message_id`.
   - Update Telegram outbound to call this helper immediately after successfully sending an actionable notification,
     while still writing the legacy Telegram pending-action file for backward compatibility.
   - Keep the operation best-effort from Telegram's point of view: failure to update shared metadata should be logged
     but should not prevent callbacks from working through the legacy file.

3. Add an explicit handled-state API in the shared store.
   - Add a helper that marks a notification action as `already_handled` with enough audit data to know why (`source`,
     timestamp, and optionally the response action).
   - Have existing approval paths call it after they successfully write the plan response or otherwise resolve the
     action. The CLI/mobile path can use `run_plan_side_effects`; the TUI direct-write path should mark the same state
     after the response file is created. The helper must remain best-effort so it never blocks the runner response.
   - Add a targeted auto-approval helper that can mark matching PlanApproval actions handled by exact `plan_file` plus
     agent identity fields (`agent_timestamp`, `agent_root_timestamp`, or `agent_name`). This covers the stale-message
     case without broadly clearing unrelated plan approvals.

4. Teach Telegram inbound cleanup to use shared action state.
   - Extend the existing external-handled cleanup pass so it reads the shared pending-action store with legacy entries
     merged in.
   - For each Telegram transport record whose action is no longer available (`already_handled`, stale, or missing
     target), call `edit_message_reply_markup(..., reply_markup=None)` and then remove the legacy Telegram pending
     record if one exists.
   - Keep `clear_awaiting_feedback_by_prefix(prefix)` in the cleanup path so a feedback flow cannot continue after the
     underlying plan was approved elsewhere.
   - Keep the old filesystem checks as a fallback for legacy records that do not yet have shared transport state.

5. Harden button callbacks against races.
   - Before writing a response for a Telegram callback, resolve the shared pending-action state for that prefix.
   - If it is already handled or stale, answer the callback with the existing "already handled" or expired message,
     remove the inline keyboard, and do not write a new response file.
   - Preserve the current happy path for approve, run, tale/epic/legend, reject, and feedback.

6. Verification.
   - In the SASE core repo, run the focused pending-action and plan-approval tests, then `just install` and `just check`
     after implementation changes.
   - In the `sase-telegram` linked repo, run the focused outbound/inbound integration tests, then `just install` and
     `just check`.
   - Manually inspect the JSON shape of both pending-action stores in a temporary test home to confirm legacy and shared
     records do not fight each other.

## Risks And Constraints

- Do not make SASE core import or shell out to Telegram code. Core should only record that an action is handled; the
  Telegram inbound chop should perform Telegram API cleanup.
- Avoid broad matching in the `%auto` cleanup helper. Matching only by plan file is risky if paths are reused; matching
  by plan file plus agent identity is safer.
- Do not delete shared pending-action rows immediately after handling. Keeping a handled state for a short period lets
  late Telegram callbacks receive a deterministic "already handled" response.
- The legacy Telegram pending-action file should remain supported until all active installs reliably register Telegram
  transports in the shared store.
