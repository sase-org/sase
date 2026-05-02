---
create_time: 2026-04-01 18:23:43
status: done
prompt: sdd/prompts/202604/clipboard_on_plan_commit.md
---

# Plan: Copy Plan File Path to Clipboard on "Plan Committed"

## Problem

When a user approves a plan via "Approve with Options" with `commit_plan=True` and `run_coder=False` (the "commit only"
flow), the plan and spec files are committed and the agent status is set to "PLAN COMMITTED" — but the user has no easy
way to grab the committed plan file path. The typical next step is to pass this path to another agent (e.g. via
`#plan`), so having it on the clipboard saves a manual copy step.

## Solution

Automatically copy the saved plan file path to the system clipboard when the "PLAN COMMITTED" status is set in
`handle_plan_approval()`. This mirrors the existing manual `Y` (copy path) binding in the plan approval modal, but fires
automatically at the right moment.

## Changes

### `src/sase/ace/tui/actions/agents/_notification_modals.py`

In the `on_dismiss` callback, in the `elif` block that handles `commit_plan=True, run_coder=False` (lines 332-338), add
clipboard copy logic after setting the status override:

1. Import `copy_to_system_clipboard` from `sase.ace.tui.actions.clipboard`
2. Check if `response_data` contains a `saved_plan_path` (it was set earlier at line 310)
3. Shorten the path with `~` for the home directory (matching the convention in `plan_approval_modal.py`)
4. Call `copy_to_system_clipboard()` with the shortened path
5. Include the path in the notification message so the user knows what was copied

This is ~8 lines of new code in a single location. No new files, no new functions, no architectural changes.
