---
create_time: 2026-04-15 12:35:04
status: done
prompt: sdd/prompts/202604/cls_tab_scroll_to_top_bottom.md
---

# Plan: Add `g`/`G` scroll-to-top/bottom on CLs tab

## Problem

The `g` (scroll to top) and `G` (scroll to bottom) keymaps work on the Agents and Axe tabs but are no-ops on the CLs
tab. The user expects them to scroll the ChangeSpec detail panel to the top/bottom.

## Root Cause

`action_scroll_to_top()` and `action_scroll_to_bottom()` in `_basic.py` only handle the `axe` and `agents` branches —
there is no `changespecs` case. The detail panel container (`#detail-scroll`) already exists and is used by
`action_scroll_detail_down`/`action_scroll_detail_up` for the CLs tab.

## Changes

### 1. Add `changespecs` handling to scroll actions

**File:** `src/sase/ace/tui/actions/navigation/_basic.py`

In `action_scroll_to_top()` (line 162), add a `changespecs` branch that queries `#detail-scroll` and calls
`scroll_home(animate=False)`.

In `action_scroll_to_bottom()` (line 173), add a `changespecs` branch that queries `#detail-scroll` and calls
`scroll_end(animate=False)`.

### 2. Add `g`/`G` to CLs tab help modal

**File:** `src/sase/ace/tui/modals/help_modal/bindings.py`

In `cls_bindings()`, add a `scroll_to_top / scroll_to_bottom` entry to the "Navigation" section (after the existing
`scroll_detail_down / scroll_detail_up` entry at line 55-57), with the description
`"Scroll detail panel to top / bottom"`.
