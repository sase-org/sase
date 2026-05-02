---
create_time: 2026-04-02 13:10:51
status: done
prompt: sdd/prompts/202604/task_panel_scroll_fix.md
---

# Plan: Fix task panel scroll jumping back to bottom

## Problem

When viewing a running task in the task queue modal, pressing `ctrl+u` to scroll up works momentarily but the view snaps
back to the bottom every 1-2 seconds. This makes it impossible to read earlier output of a running task.

## Root Cause

The 1-second refresh timer (`set_interval(1, self._refresh_running_output)` at line 196) calls
`_display_task_live_output()` for the selected running task, which unconditionally calls
`scroll.scroll_end(animate=False)` at line 235. This overwrites any manual scroll position the user has set.

The same pattern exists in `_display_output()` (line 162-163), which auto-scrolls to bottom for running tasks.

## Fix

Track whether the user has manually scrolled away from the bottom. When this "user scrolled" flag is set, suppress the
auto-scroll-to-end behavior in both `_display_task_live_output()` and `_display_output()`.

### Implementation

1. **Add a `_user_scrolled` flag** to `TaskQueueModal.__init__`, defaulting to `False`.

2. **Set the flag in scroll actions**: `action_scroll_output_up()` sets `_user_scrolled = True`.
   `action_scroll_output_down()` clears it if the user scrolls back to the bottom.

3. **Guard auto-scroll calls**: In `_display_task_live_output()` and `_display_output()`, only call `scroll_end()` /
   `_scroll_output_to_end()` when `_user_scrolled` is `False`.

4. **Reset the flag on task switch**: When the user highlights a different task (in `on_option_list_option_highlighted`
   and `_rebuild_list`), reset `_user_scrolled = False` so the new task starts at the natural position.

### File changes

- `src/sase/ace/tui/modals/task_queue_modal.py` — all changes in this single file
