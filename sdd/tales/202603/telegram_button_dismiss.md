---
create_time: 2026-03-29 14:18:39
status: done
prompt: sdd/prompts/202603/telegram_button_dismiss.md
---

# Plan: Fix Telegram plan buttons not dismissed on TUI rejection

## Problem

When a user rejects an agent from the TUI (without feedback), the Telegram plan review buttons
(Approve/Commit/Epic/Reject/Feedback) remain visible and interactive. The user rejected agent 'g' from the TUI but the
Telegram buttons were not dismissed.

## Root Cause

The TUI rejection-without-feedback path in `_notification_modals.py:250-263` marks the notification as dismissed and
kills the agent, but does NOT write `plan_response.json`. The killed agent exits via `killed_check()` without cleaning
up `plan_request.json`.

The Telegram inbound chop's `find_externally_handled()` (`sase-telegram inbound.py:398-408`) checks three conditions:

1. `plan_response.json` exists → FALSE (not written on rejection)
2. `plan_approved.marker` exists → FALSE (only for approvals)
3. `plan_request.json` doesn't exist → FALSE (still exists; agent was killed before cleanup)

All three are false, so the pending action is never detected as externally handled, and Telegram buttons remain.

## Fix

Write `plan_response.json` with `{"action": "reject"}` in the TUI rejection-without-feedback path, before killing the
agent.

This makes condition (1) in `find_externally_handled()` true, allowing the Telegram inbound chop to detect and dismiss
the buttons on its next iteration (~5 seconds).

### Safety analysis

- If the agent reads the response before being killed: it sees `action="reject"` with no feedback → returns `None` (same
  outcome as being killed)
- If the agent is killed before reading it: the file persists for Telegram detection
- Both paths result in correct behavior

### Changes

1. **`src/sase/ace/tui/actions/agents/_notification_modals.py`** (~252-263): In the `reject without feedback` block,
   write `plan_response.json` with `{"action": "reject"}` before killing the agent. Update the comment.

2. **`tests/`**: Add a test verifying `plan_response.json` is written on TUI rejection without feedback.
