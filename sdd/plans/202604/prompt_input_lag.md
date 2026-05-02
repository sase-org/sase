---
create_time: 2026-04-27 16:30:50
status: done
---
# Plan: Diagnose and Fix Prompt Input Lag

## Context

Users sometimes see typed characters stop appearing in the ace TUI prompt input bar and then appear all at once seconds
later. That symptom means the Textual UI thread is being blocked while prompt-key events queue up.

Recent commits in the relevant window changed ace TUI refresh behavior:

- `0c8d55f6 feat(ace/tui/perf): event-driven auto-refresh + small wins`
- `b3ecd077 fix(ace/tui): unify selection-identity preservation across all tabs`

The prompt text-area itself already schedules prettier formatting asynchronously and file completion is explicit
(`ctrl+t`), so ordinary printable-key handling is unlikely to be the direct source. The more plausible regression is a
background refresh or notification reconciliation still applying work on the UI thread while the prompt bar has focus.

## Findings So Far

`EventHandlersMixin._on_auto_refresh()` only checks `_prompt_context` after it has already:

1. potentially awaited `_load_axe_status_async()`, whose apply phase refreshes widgets on the UI thread;
2. potentially awaited `_poll_agent_completions()`, which loads notifications off-thread but then does additional work
   on the UI thread.

`_poll_agent_completions()` has extra synchronous hazards after its off-thread load:

- `expire_due_snoozes(notifications)` can rewrite the notification file on the UI thread.
- `_apply_notification_status_overrides()` can auto-dismiss externally answered plan notifications, call
  `mark_dismissed()`, and then call synchronous `_load_agents()`, which performs disk reads and render/finalize work.

`EventHandlersMixin._on_artifact_change()` is another path that bypasses the prompt-bar guard. It marks all dirty flags
and immediately schedules agent and changespec async refreshes. Those refreshes move disk I/O off-thread, but their
apply/render legs still run on the UI thread and can block prompt keystrokes.

The current input-mode check is also incomplete: it keys only off `_prompt_context`, while some prompt bars, such as
approval prompt editing, use `_approve_prompt_context` and still mount `PromptInputBar`.

## Root-Cause Hypothesis

The lag is caused by background refresh work continuing during prompt entry. Most of the heavy disk reads are async, but
the UI-thread apply/render phases and some notification-store rewrites can still monopolize the Textual event loop. The
effect is intermittent because it depends on auto-refresh timing, filesystem watcher events, notification state, and the
number of agents/changespecs/artifacts currently loaded.

## Implementation Plan

1. Add a small helper on the TUI event-handling side that answers "is a prompt-like input surface active?".
   - Include `_prompt_context`, `_approve_prompt_context`, and `_plan_feedback_context`.
   - Also defensively detect a mounted `PromptInputBar` so future prompt-bar modes are covered.

2. Move the input-mode guard to the beginning of `_on_auto_refresh()`.
   - While prompt input is active, do not run axe polling, notification polling, agent refresh, or changespec refresh.
   - Keep the countdown timer and idle/activity tracking unchanged; the user is typing, so responsiveness matters more
     than background freshness.
   - Leave dirty flags set so the next refresh after the prompt closes catches up.

3. Gate filesystem watcher refresh scheduling while prompt input is active.
   - `_on_artifact_change()` should mark dirty flags, then defer itself briefly instead of scheduling agent/changespec
     refreshes immediately.
   - This preserves event-driven catch-up without applying UI work during prompt editing.

4. Add focused regression tests.
   - Auto-refresh with a prompt context should perform no background work, including axe and notification polling.
   - Artifact changes with prompt input active should mark dirty flags and defer instead of scheduling refreshes.
   - Approval/feedback prompt contexts should be treated as active input surfaces, not just normal agent-launch prompts.

5. Run targeted tests around event handlers and prompt behavior first.
   - `pytest tests/ace/tui/test_event_handlers_dirty_flags.py`
   - Any new regression test module if separate.

6. Run the repository check expected by local instructions after code changes.
   - Per memory, run `just install` first if needed, then `just check`.

## Acceptance Criteria

- Typing in the prompt input bar is not interrupted by auto-refresh or watcher-driven refresh work.
- Dirty background state still refreshes after the prompt bar closes.
- Existing refresh behavior remains unchanged when no prompt-like input surface is active.
- Tests cover the previously missing guard paths.
