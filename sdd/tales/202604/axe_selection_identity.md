---
create_time: 2026-04-27 14:37:56
status: done
prompt: sdd/prompts/202604/axe_selection_identity.md
---
# Plan: Stabilize AXE Tab Selection By Item Identity

## Problem

The AXE tab currently tracks focus primarily as a flat row index (`current_idx` / `_axe_last_idx`) into `_axe_items`.
That works only while the AXE side-panel item ordering is unchanged.

The snapshot shows `xpad` as a background-command row after configured lumberjack rows:

- `sase axe`
- lumberjacks: `checks`, `comments`, `gchat`, `hooks`, `housekeeping`, `waits`
- bgcmd: `xpad`

On a different machine or after a config/state refresh, the configured lumberjack list can contain a different set or
order. Because selection is restored by row number, the row that used to mean `xpad` can later mean `housekeeping`. This
is identity drift: the TUI preserves a position, not the thing the user selected.

## Root Cause Hypothesis

`AxeDisplayLoadersMixin._build_axe_items()` rebuilds `_axe_items` from sorted lumberjack config names and active bgcmd
slots, then only clamps `current_idx` when it is out of bounds. It does not capture the previously selected item
identity and re-anchor to the matching rebuilt item.

Related code paths also save/restore AXE tab position as an index:

- `_save_current_tab_position()` writes `_axe_last_idx = current_idx`
- `_get_clamped_axe_idx()` returns the clamped saved index
- `_switch_to_axe_view()` changes `_axe_current_view` without moving `current_idx` to the matching row

Any of these can select the wrong row when lumberjack config differs between machines or when bgcmd rows
appear/disappear.

## Fix Strategy

Introduce a small stable identity helper for AXE items and use it wherever the AXE item list is rebuilt or restored.

Stable keys:

- `AxeParentItem()` -> `("axe", None)`
- `LumberjackItem(name)` -> `("lumberjack", name)`
- `BgCmdItem(slot)` -> `("bgcmd", slot)`

Implementation steps:

1. Add helper functions in the AXE display loader module:
   - derive a key from an `AxeItem`
   - find the index for a key in a rebuilt item list
   - get the currently selected AXE item key

2. Update `_build_axe_items()`:
   - snapshot the selected AXE item key before rebuilding
   - rebuild the item list as today
   - if on the AXE tab, restore `current_idx` to the matching key when present
   - otherwise fall back to clamping, preserving existing behavior for removed items
   - keep `_axe_last_idx` synchronized when the AXE tab is active

3. Update tab position restore:
   - save `_axe_last_item_key` alongside `_axe_last_idx`
   - make `_get_clamped_axe_idx()` prefer the saved key and fall back to the saved index only if that key no longer
     exists

4. Update `_switch_to_axe_view()`:
   - when switching to a bgcmd slot or the parent AXE view programmatically, move `current_idx` to the matching rebuilt
     item row if available before refreshing
   - this avoids header/detail state disagreeing with the highlighted row

5. Add focused regression tests:
   - rebuilding AXE items preserves a selected bgcmd slot when a new earlier-sorting lumberjack is inserted before it
   - saved AXE tab selection restores by bgcmd slot key rather than old row index
   - rebuilding preserves a selected lumberjack by name when other lumberjacks are inserted before it
   - if the selected item disappears, the existing clamp/fallback behavior still works

6. Verify:
   - run the focused AXE navigation/display tests
   - run `just install` if needed, then `just check` before finishing because repo instructions require it after edits

## Expected Outcome

The AXE tab will keep focus on `xpad` as long as the bgcmd slot still exists, even if another machine has extra
configured lumberjacks such as `housekeeping`. If `xpad` is actually gone, the UI will fall back to a valid row instead
of silently selecting an unrelated row by stale index.
