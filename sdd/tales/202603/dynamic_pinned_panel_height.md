---
create_time: 2026-03-31 09:09:48
status: pending
prompt: sdd/prompts/202603/dynamic_pinned_panel_height.md
---

# Plan: Dynamic Pinned Panel Height

## Problem

The Pinned panel has a fixed `max-height: 12` (container) / `max-height: 10` (inner list) in `styles.tcss`. When a user
pins many agents or workflows, the panel can't show them all without scrolling. Conversely, when only 1-2 items are
pinned, the panel correctly auto-sizes down (via `height: auto`). The ask is to let the panel grow as items are added,
up to a reasonable cap, so users see more of their pinned items without scrolling.

## Design

**Core idea**: Replace the static CSS `max-height` with a dynamic style update applied each time the pinned panel's
content changes. The container's `max-height` scales with the number of pinned entries: each entry gets ~2 rows (one
content line + one separator/padding line), plus 2 rows for the border chrome. Cap at a configurable maximum (default
~20 rows) so the pinned panel never dominates the screen.

**Formula**: `max_height = min(pinned_count * 2 + 2, MAX_PINNED_HEIGHT)` where `MAX_PINNED_HEIGHT` defaults to 20. The
inner list's max-height tracks at `max_height - 2` to account for the border.

**Why dynamic styles instead of pure CSS**: Textual CSS doesn't support computed properties or `min(content, cap)`
expressions. The `height: auto` + `max-height` pattern works for a static cap, but to scale the cap with content count,
we need Python-side style updates.

**Where to hook in**: `_update_panel_focus_styling()` in `_display.py` already runs on every display refresh, has access
to `pinned_count`, and already manipulates the pinned container. This is the natural place to also adjust its
`max-height`.

## Changes

### 1. `src/sase/ace/tui/actions/agents/_display.py` — Dynamic max-height

In `_update_panel_focus_styling()`, after computing `pinned_count` (line 215), add logic to set the container's
`max-height` and the inner list's `max-height` dynamically:

```python
# Dynamic pinned panel height: scale with content, cap at limit
MAX_PINNED_HEIGHT = 20
container_max = min(pinned_count * 2 + 2, MAX_PINNED_HEIGHT)
pinned_container.styles.max_height = container_max

pinned_list = self.query_one("#pinned-list-panel")
pinned_list.styles.max_height = container_max - 2
```

This replaces the static CSS values at runtime. When `pinned_count` is 0, the panel is hidden entirely (existing
`display = pinned_count > 0` logic), so the max-height value doesn't matter in that case.

### 2. `src/sase/ace/tui/styles.tcss` — Raise static max-height to match cap

Update the static CSS max-heights to match the new dynamic cap so there's no conflict:

- `#pinned-panel-container`: change `max-height: 12` → `max-height: 20`
- `#pinned-list-panel`: change `max-height: 10` → `max-height: 18`

These serve as the initial/fallback values before the first dynamic update runs. The Python code will immediately
override them on first refresh, but having them match avoids a visual flash.

### 3. No changes needed

- **`_core.py` (`_build_panel_indices`)**: Unchanged — the count of pinned entries is already available.
- **`app.py` (compose)**: Layout structure unchanged; the container and list widget IDs are stable.
- **`default_config.yml`**: No new config key needed — the cap is a UI constant, not a user-facing setting.
- **`agent_list.py`**: Rendering per-entry is unchanged; only the container sizing changes.
- **Help modal / footer**: No user-facing behavior change to document.

## Testing

Verify with `sase ace --agent`:

1. Pin 1 agent → panel height ~4 rows (2 \* 1 + 2)
2. Pin 5 agents → panel height ~12 rows (2 \* 5 + 2)
3. Pin 10+ agents → panel height caps at 20 rows
4. Unpin all → panel hides entirely (existing behavior preserved)
