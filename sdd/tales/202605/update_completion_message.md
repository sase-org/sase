---
create_time: 2026-05-04 16:47:43
status: done
prompt: sdd/prompts/202605/update_completion_message.md
---
# Plan: Send Chat Update Completion Messages

## Goal

When a user starts the SASE update workflow from Telegram with `/update`, they should receive a second message after the
detached update worker finishes. That completion message should clearly distinguish success from failure and include the
log path for follow-up debugging.

The screenshot shows the current behavior: `/update` replies only with "Update worker started; log: ...". The core
worker already computes a final exit code in `sase.integrations.chat_install.run_worker()`, but that result is currently
only written to the worker log and is not surfaced back to Telegram.

## Current Shape

- `sase-telegram` implements `/update` in `src/sase_telegram/scripts/sase_tg_inbound.py`.
- The command calls `sase.integrations.chat_install.start_chat_install_worker()` and immediately sends a launch
  acknowledgement.
- The shared core worker lives in `src/sase/integrations/chat_install.py`.
- `start_chat_install_worker()` launches a detached `python -m sase.integrations.chat_install --workspace ...` process.
- `run_worker()` stops axe, optionally syncs the registered primary `sase` workspace, runs `chat_install.command`,
  always attempts to restart axe, logs the final exit code, then exits.
- Google Chat also uses this worker via `.update`, so the shared completion mechanism should not be Telegram-only.

## Product Behavior

Keep the immediate acknowledgement because it confirms the command was accepted and gives the user the log path while
the long-running work proceeds.

Add a completion notification after the worker exits:

- Success: "Update completed successfully; log: <path>"
- Failure: "Update failed with exit code <n>; log: <path>"
- Optional detail if cheap and reliable: include the resolved workspace or the high-level failed stage, but do not paste
  full command output into chat.

If axe restart fails after the install command succeeds, treat the overall update as failed or degraded. The user asked
for completion of the operations associated with `/update`; restarting axe is part of those operations and should be
visible in the result.

## Technical Design

Add a small integration-neutral completion record to the shared core worker instead of importing Telegram code from
core.

Core changes in `sase`:

1. Extend the chat install launch model with a stable job identity and status path.
   - Generate a job id when `start_chat_install_worker()` launches the detached process.
   - Store status records under `~/.sase/chat_install/completions/` or a similar state directory.
   - Return the job id/status path on `ChatInstallLaunchResult` for integrations that want to remember delivery context.

2. Pass the job id/status path into the detached worker.
   - Add a CLI argument such as `--status-path`.
   - `run_worker()` should write a final JSON record in a `finally` block after stop/sync/install/restart handling is
     known.
   - Use an atomic write pattern so chat integrations never read a partial record.

3. Make the completion record explicit and durable. Suggested fields:
   - `job_id`
   - `status`: `success` or `failed`
   - `exit_code`
   - `log_path`
   - `workspace`
   - `started_at`
   - `completed_at`
   - `restart_succeeded` if restart outcome is separately tracked
   - `message`

4. Revisit restart status semantics.
   - `_restart_axe()` currently returns `None` even if all attempts fail.
   - Change it to return a boolean so `run_worker()` can mark the completion as failed/degraded when axe does not come
     back.
   - Keep existing process exit behavior compatible where possible, but make the persisted completion honest.

Telegram changes in `sase-telegram`:

1. Persist delivery context for launched update jobs.
   - When `/update` gets a `launched` result, save a small pending update record under `~/.sase/telegram/`, keyed by the
     job id or status path.
   - Include `chat_id`, `log_path`, and enough state to avoid duplicate delivery.

2. On each inbound chop run, scan pending update records before or after processing Telegram updates.
   - If the core completion record is absent, leave the pending record alone.
   - If present, format and send the success/failure Telegram message.
   - Mark the pending record delivered or delete it after a successful send.
   - If sending fails, keep the record so the next inbound run can retry.

3. Keep formatting plain and robust.
   - No MarkdownV2 is required unless we need emphasis.
   - Always include the shortened home-relative log path when available.

Google Chat follow-up:

- Because `.update` uses the same shared worker, add the same pending/delivery flow in `retired chat plugin` either in the same
  change or as a follow-up bead.
- If this work is scoped only to Telegram, design the core completion record so Google Chat can adopt it without another
  core refactor.

## Tests

In `sase`:

- `start_chat_install_worker()` returns a launched result with job/status metadata and passes the status path to
  `Popen`.
- `run_worker()` writes a success completion record when sync/install/restart succeed.
- `run_worker()` writes a failure record for sync failure, install nonzero, missing workspace, timeout, and unexpected
  exception.
- `_restart_axe()` failure is represented in the completion record.
- Existing launch failure, missing config, workspace resolution, and lock tests still pass.

In `sase-telegram`:

- `/update` still sends the immediate launch acknowledgement.
- A launched update persists pending delivery context.
- Pending completion scan sends a success message exactly once.
- Pending completion scan sends a failure message with exit code and log path.
- Missing completion record does nothing.
- Send failure leaves the pending record for retry.

If implementing Google Chat in the same pass:

- Mirror the Telegram pending-completion tests around `.update`, preserving thread delivery where applicable.

## Validation

Run targeted tests first:

- In `sase`: `just test tests/test_chat_install.py`
- In `sase-telegram`: `just test tests/test_inbound.py`
- If touched: in `retired chat plugin`: `just test tests/test_inbound.py`

Then run required checks in each modified repo:

- In `sase`: `just check`
- In `sase-telegram`: `just check`
- In `retired chat plugin` if modified: `just check`

Because this workspace may be stale, run `just install` in a repo before checks if dependencies are not already current.

## Risks And Mitigations

- Duplicate completion messages: use job ids and delete/mark pending records only after successful send.
- Lost completion messages: persist both the core completion record and chat delivery context before the detached worker
  can finish.
- Core/plugin coupling: core writes neutral JSON; chat plugins own chat delivery.
- Axe restart timing: inbound delivery depends on the chop running again after axe restarts, which matches the existing
  architecture and avoids making the core worker depend on Telegram credentials.
- Compatibility: keep existing `ChatInstallLaunchResult.status` values and launch acknowledgement behavior so existing
  chat integrations do not break.

## Suggested Implementation Order

1. Add core completion records and tests in `sase`.
2. Add Telegram pending delivery persistence and completion scan with tests.
3. Update Telegram docs for `/update`.
4. Decide whether to implement Google Chat delivery in the same change; if yes, mirror the adapter work there.
5. Run targeted tests and full checks for every modified repo.
