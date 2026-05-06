---
create_time: 2026-05-06 17:23:09
status: done
prompt: sdd/prompts/202605/agents_panel_first_selection.md
---
# Plan: Agents Panel J/K First Selection

## Context

The `sase ace` Agents tab is split into tag-driven panels. `J` and `K` move focus between those panels via
`AgentPanelsMixin._change_focused_agent_panel()`.

The current implementation changes the focused panel and then scans `keys_per_agent` for the first global `_agents`
index whose panel key matches the destination panel. That is only the first item in raw loader order. The rendered
`AgentList` can be in a different order because each panel is rendered through `build_agent_tree()` using project /
ChangeSpec / name grouping and stable sorting. Existing tests for ordinary `j`/`k` navigation and kill/dismiss focus
restoration already encode this exact distinction: raw `_agents` order is not necessarily visible row order.

## Goal

When the user presses `J` or `K` to move between agent panels, the newly focused panel should always select the first
visible agent row in that panel's rendered list.

If the first selectable rendered stop is a collapsed group banner rather than an agent row, panel switching should focus
that banner and use its first backing agent for the detail panel, matching the existing banner navigation model.

## Implementation Approach

1. Reuse the existing panel-aware visible-order machinery instead of adding another raw-order scan.

   The production method `AgentsMixinCore._panel_navigation_stops()` already returns the focused panel's selectable rows
   in the same order the widget renders them, including collapsed banners.

2. Update `_change_focused_agent_panel()` after the panel focus changes:
   - Clear any stale attempt selection.
   - Read the destination panel's first selectable stop from `_panel_navigation_stops()`.
   - If it is an agent stop, clear `_current_group_key` and set `current_idx` to that global index.
   - If it is a banner stop, set `_current_group_key` to that group key and set `current_idx` to the first visible agent
     inside that banner using the existing `AgentsMixinCore._agents_visible_order()` helper as a backing/detail anchor.
   - If the destination panel has no stops, fall back to the existing `_snap_current_idx_to_focused_panel()` behavior.

3. Make cache behavior explicit.

   `_panel_navigation_stops()` caches by the `_panel_group` object and focused index, so changing `focused_idx` is
   already part of the cache key. No new cache invalidation should be necessary for normal panel switching.

4. Add focused regression coverage.

   Add tests that create a multi-panel Agents fixture whose destination panel raw order differs from rendered grouping
   order. Assert that `action_focus_next_agent_panel()` / `action_focus_prev_agent_panel()` select the first rendered
   agent in the destination panel, not the first raw matching index.

   Add a collapsed-group case so a panel switch can land on the first collapsed banner while keeping `current_idx`
   anchored to a real agent for details/actions.

5. Verify narrowly first, then run the repo check.

   Run the new/nearby TUI tests first, then run `just install` followed by `just check` as required by the workspace
   instructions after code changes.

## Risks and Notes

- The change is presentation-only TUI state, so it stays in this Python repo and does not cross the Rust core backend
  boundary.
- This should preserve existing behavior for single-panel lists and for panels whose raw order already matches rendered
  order.
- The implementation should avoid rebuilding the `AgentList` more often than the current `list_changed=True` refresh
  already does for `J`/`K`.
