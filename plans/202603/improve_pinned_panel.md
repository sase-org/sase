---
create_time: 2026-03-30 19:27:07
status: done
---

# Plan: Improve Pinned Panel on Agents Tab

## Context

The Pinned panel was recently added to the Agents tab (merged via PR #59, then repositioned to the left side below the
main agent list). It allows users to pin completed agents (DONE, FAILED, PLAN DONE, PLAN COMMITTED) so they survive
dismiss-all operations (`X`).

The core mechanics work well — pin/unpin toggle, panel focus switching, auto-hide when empty, dismiss-all correctly
skipping pinned agents. But there are several UX and correctness issues worth addressing.

## Phase 1: Visual cleanup — remove ✘ icon from pinned panel entries

**Problem**: Every entry in the pinned panel shows the red `✘` (done/dismissible) icon. This is redundant and misleading
— the panel title already says "📌 Pinned", and all entries are by definition completed. Worse, `✘` visually means
"dismiss me" but the whole point of pinning is to _protect_ from dismissal. It adds visual noise without information.

**Change**: In `agent_list.py:_format_agent_option()`, skip the `✘` icon when `self._panel == "pinned"`. Same for
`_calculate_entry_display_width()`.

## Phase 2: Status-enriched panel title

**Problem**: The border title shows "📌 Pinned (3)" — a flat count that doesn't distinguish between successful and
failed agents. Users pin agents to reference them later; knowing the status breakdown at a glance saves having to focus
into the panel.

**Change**: In `_display.py:_update_panel_focus_styling()`, compute status counts from `_pinned_panel_indices` and
render something like:

- `📌 Pinned (3✓ 1✗)` — compact with status symbols
- Use green for done count and red for failed count via Rich markup in the border title

## Phase 3: Clean up pin on dismiss

**Problem**: When a user dismisses an individual agent from within the pinned panel (focus pinned → select agent → press
`x`), the agent is dismissed but its identity remains in `_pinned_agents` and `pinned_agents.json`. This creates an
orphaned pin that persists across sessions.

**Change**: In `_killing.py:_dismiss_done_agent()`, if the dismissed agent's identity is in `_pinned_agents`, remove it
and save. This is a one-line fix with a save call.

## Phase 4: Stale pin garbage collection

**Problem**: If an agent's artifacts are deleted externally (or the agent simply ages out), the pin identity in
`pinned_agents.json` persists indefinitely. Over time, this file accumulates orphaned entries.

**Change**: In `_loading.py:_load_agents()`, after building the final `_agents` list and calling
`_build_panel_indices()`, compare `_pinned_agents` against agents actually found. Remove any pinned identities that
don't match any loaded agent and save the cleaned set. Only do this GC when the set actually shrinks (to avoid
unnecessary disk writes every refresh cycle).

## Phase 5: Dim panel title when unfocused

**Problem**: The border title color is always `#AF87D7` (lavender) regardless of focus state. The border itself changes
(muted when inactive, bright when active), but the title stays bright even when the panel isn't focused. This weakens
the visual distinction between focused and unfocused states.

**Change**: In `styles.tcss`, set `border-title-color` to the muted color by default, and override to the bright color
in the `.panel-active` rule. Similarly, dim the main panel's border title when it gets `.panel-inactive`.

## Files touched

- `src/sase/ace/tui/widgets/agent_list.py` — Phase 1 (skip ✘ in pinned panel)
- `src/sase/ace/tui/actions/agents/_display.py` — Phase 2 (status-enriched title)
- `src/sase/ace/tui/actions/agents/_killing.py` — Phase 3 (clean pin on dismiss)
- `src/sase/ace/tui/actions/agents/_loading.py` — Phase 4 (stale pin GC)
- `src/sase/ace/pinned_agents.py` — Phase 3-4 (save after cleanup)
- `src/sase/ace/tui/styles.tcss` — Phase 5 (dim title)
