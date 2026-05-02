---
create_time: 2026-04-02 11:37:47
status: done
prompt: sdd/prompts/202604/ace_axe_nav_freeze.md
---

# Fix: sase ace TUI freeze when pressing `k` on AXE tab

## Problem

The TUI freezes when pressing `k` from the first item (`sase axe`) on the AXE tab to wrap-navigate to the last item
(`xpad`, a completed BgCmdItem). The app becomes completely unresponsive.

## Root Cause

A race condition in `BgCmdList.update_list()` causes an event feedback loop between the OptionList's `OptionHighlighted`
messages and the app's `current_idx` reactive property.

### The Event Chain

1. User presses `k` -> `action_prev_changespec()` wraps `current_idx` from 0 to 5 (xpad)
2. `watch_current_idx(0, 5)` fires synchronously -> calls `_refresh_axe_display()`
3. `_refresh_axe_display()` calls `bgcmd_list.update_list(current_idx=5)`
4. `update_list()` sets `_programmatic_update = True`, rebuilds the list, sets `self.highlighted = 5`
5. Setting `highlighted` triggers Textual's reactive system -> `watch_highlighted(5)` is called **synchronously**
6. `watch_highlighted` calls `post_message(OptionHighlighted(5))` — message goes into the async queue
7. `update_list()` schedules `call_later(self._clear_programmatic_flag)` to clear the flag

### The Race

The `call_later` callback and the queued `OptionHighlighted` message are both pending in the event loop. Their execution
order is **not guaranteed**:

- **Intended order**: Messages processed first (flag is True, events ignored) -> flag cleared
- **Actual order** (intermittent): `call_later` runs first -> flag cleared -> `OptionHighlighted` processed with
  flag=False -> `SelectionChanged` posted -> `current_idx` set

When combined with the auto-refresh timer (`_on_auto_refresh` fires every N seconds), the situation worsens:

- Auto-refresh calls `_load_axe_status()` -> `_build_axe_items()` -> clamps `current_idx` to 0 if items changed
- This creates a ping-pong: `current_idx` bounces between 0 and 5 as stale `OptionHighlighted` events and auto-refresh
  clamping fight each other
- Each bounce triggers `_refresh_axe_display()` -> `update_list()` -> more events queued
- The synchronous I/O in each `_refresh_axe_display()` call (reading lumberjack status files, bgcmd info, output logs)
  compounds the blocking

## Fix

Override `watch_highlighted` in `BgCmdList` to suppress `OptionHighlighted` messages during programmatic updates, and
clear the flag synchronously instead of via `call_later`.

### Changes

**`src/sase/ace/tui/widgets/bgcmd_list.py`**:

1. Add `watch_highlighted` override that checks `_programmatic_update` — if True, skip calling
   `super().watch_highlighted()` entirely (suppresses both the message post and the scroll-to-highlight)
2. In `update_list()`, replace `self.call_later(self._clear_programmatic_flag)` with synchronous
   `self._programmatic_update = False` in a `finally` block
3. Remove the `_clear_programmatic_flag` method (no longer needed)

This eliminates the race entirely: no `OptionHighlighted` messages are posted during programmatic updates, so no
`SelectionChanged` events cascade back, and no recursive `_refresh_axe_display()` calls occur.

### Why this is safe

- `watch_highlighted` on `OptionList` does two things: scroll to highlight and post `OptionHighlighted`. Both are
  unnecessary during programmatic rebuilds — the list is being fully replaced, and the final highlight position is set
  explicitly.
- User-initiated highlight changes (arrow keys, mouse) occur when `_programmatic_update` is False, so they go through
  the normal path.
- The `on_option_list_option_highlighted` handler can keep its existing flag check as a belt-and-suspenders guard.
