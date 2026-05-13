---
create_time: 2026-05-13 16:20:53
status: done
prompt: sdd/prompts/202605/telegram_agent_runtime.md
---
# Plan: Show Agent Runtime in Telegram Completion Messages

## Goal

Show the same agent runtime users see on the Agents tab in Telegram completion messages for agent runs. The runtime
should be visible for both successful and failed agent-completion notifications without changing notification routing,
unread state, or action handling.

## Current Shape

- The Agents tab computes runtime in `src/sase/ace/tui/models/agent_time.py`.
- For leaf agent rows, elapsed runtime is based on `run_start_time` when available, falling back to `start_time` only
  for historical terminal rows. This deliberately excludes pre-run WAITING/STARTING time.
- Agent runners persist `run_started_at` in `agent_meta.json` immediately before the execution loop and persist
  `stopped_at` during finalization via `record_completion_metrics()`.
- Completion notifications are created in `src/sase/axe/run_agent_runner_finalize.py` through
  `send_completion_notification()`.
- `sase-telegram` formats `user-agent` notifications in `../sase-telegram/src/sase_telegram/formatting.py` via
  `_format_workflow_complete()`.

## Design

1. Add a small, testable runtime helper in SASE that mirrors the Agents-tab terminal leaf calculation:
   - Inputs: launch timestamp suffix, `run_started_at`, and completion time.
   - Use `run_started_at` when present.
   - Fall back to parsed launch timestamp only when `run_started_at` is absent.
   - Clamp negative elapsed values to zero through the existing compact duration formatter.
   - Return the same compact format as the TUI (`4m32s`, `1h05m`, etc.).

2. In `run_agent_runner.py`, capture the `run_started_at` returned by `record_run_started_at()` before calling the
   execution loop.

3. During finalization, capture a single completion timestamp before recording metrics/stop time and use it for:
   - Metrics duration as today.
   - Persisted `stopped_at` timestamp, so disk state and notification metadata agree.
   - Notification `runtime` action data.

4. Extend `record_completion_metrics()` and/or `record_stop_time()` narrowly so callers can pass the already-captured
   completion timestamp. Keep the existing default behavior for other callers.

5. Extend `send_completion_notification()` with optional runtime metadata:
   - Include `runtime` in `action_data` for both `JumpToAgent` and `ViewErrorReport`.
   - Consider including `runtime_seconds` only if useful for future clients; Telegram only needs the compact string.
   - Do not add another human note line in SASE, because Telegram has a dedicated formatter and TUI notification text
     should stay stable.

6. Update `sase-telegram` workflow-complete formatting:
   - Read `n.action_data["runtime"]`.
   - Render it near the header, before notes and before prompt text.
   - Keep MarkdownV2 escaping and existing Resume button behavior unchanged.

7. Tests:
   - Add SASE unit coverage for the runtime helper:
     - Uses `run_started_at` over launch timestamp.
     - Falls back to launch timestamp for historical data.
     - Handles malformed/missing timestamps by omitting runtime.
   - Update `tests/test_run_agent_runner_notifications.py` to assert `runtime` appears in action data for success and
     failure notifications when provided.
   - Update `tests/test_axe_run_agent_runner_started_at.py` or a focused runner test to ensure the runner passes the
     recorded `run_started_at` through finalization.
   - Add `sase-telegram/tests/test_formatting.py` coverage that workflow completion messages render runtime and still
     preserve provider label, bead line, prompt, attachments, and Resume button behavior.

## Verification

- In the SASE repo:
  - Run focused tests for agent runtime/notifications first.
  - Run `just install` if needed, then `just check` before finishing.
- In `../sase-telegram`:
  - Run focused formatting tests first.
  - Run `just check` before finishing because the plugin repo will be modified.

## Non-Goals

- Do not change the Agents tab display.
- Do not change plan approval, HITL, question, or generic notification rendering.
- Do not rework notification storage schema; action data already carries optional structured fields.
- Do not add runtime-specific provider branches.
