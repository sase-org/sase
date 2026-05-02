---
create_time: 2026-04-06 16:06:36
status: done
prompt: sdd/prompts/202604/fix_jump_back_panel.md
---

# Plan: Fix apostrophe jump-back across agent panels

## Problem

When using `''` to jump back between entries on the Agents tab, switching between the main and pinned panels doesn't
work — the user stays on the same panel. The `current_idx` changes correctly but the panel focus doesn't toggle.

## Root Cause

In `_handle_entry_jump_key()` (lines 176-192 of `_advanced.py`), the apostrophe handler overwrites
`_entry_jump_last_panel` with the **current** panel (line 182) **before** reading the saved panel back (line 187). This
means the "restored" panel is always the current panel, so no panel switch ever happens.

Trace:

1. User at entry A in **main** panel. Jumps to entry B in **pinned** panel.
   - Saved: `last_panel = "main"`, `last_idx = A`
2. User presses `''` to jump back.
   - Line 180: `last_idx` read correctly as A's index
   - Line 182: **Overwrites** `last_panel = "pinned"` (current panel) — destroys saved "main"
   - Line 187: Reads `saved_panel` — gets `"pinned"` instead of `"main"`
   - Result: panel stays pinned, jump-back is broken

## Fix

Read `_entry_jump_last_panel` **before** overwriting it. This is a 3-line change:

```python
# Before the save block, snapshot the saved panel
saved_panel = self._entry_jump_last_panel.get(self.current_tab) if self.current_tab == "agents" else None

# Save current position (overwrites last_panel — safe now)
self._entry_jump_last_index[self.current_tab] = self.current_idx
if self.current_tab == "agents":
    self._entry_jump_last_panel[self.current_tab] = self._pinned_panel_focused

# Restore from snapshot instead of re-reading the dict
if self.current_tab == "agents" and saved_panel is not None:
    self._pinned_panel_focused = saved_panel
```

## File Changes

### `src/sase/ace/tui/actions/navigation/_advanced.py` (~lines 176-192)

Reorder the apostrophe block so that `saved_panel` is captured before the overwrite. No new state, no new methods — just
fix the read/write ordering.
