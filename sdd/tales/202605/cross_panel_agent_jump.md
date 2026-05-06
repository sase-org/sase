---
create_time: 2026-05-06 00:10:05
status: done
prompt: sdd/prompts/202605/cross_panel_agent_jump.md
---
# Cross-panel agent jump hint fix

## Problem

In `sase ace`, the apostrophe jump mode shows hints across every visible agent panel. Pressing a hint for an agent in
the currently focused panel works, but pressing a hint for an agent in another panel can appear to do nothing. The user
snapshot shows this with hint `[3]` in the untagged panel while the selected agent/detail belongs to a tagged panel.

## Root cause

Agent jump hints are allocated globally in visual order. `_jump_candidate_targets()` correctly records agent targets as
`("agent", global_agent_index)` and banner targets as `("banner", panel_index, group_key)`.

The dispatch path in `_handle_entry_jump_key()` handles banner targets by switching `_panel_group.focused_idx` to the
banner's panel before leaving jump mode. Agent targets do not do the same; they only set `current_idx`.

On the following agents refresh, the panel sync/highlight logic still considers the old panel focused. If the new
`current_idx` is outside that panel, `_sync_panel_group()` can snap selection back into the focused panel, so the
cross-panel jump is lost.

## Implementation plan

1. Add a small helper in the agents jump dispatch path to resolve a global agent index to its current panel index using
   the existing panel index/cache or the same `panel_key_per_agent` data already used elsewhere.
2. When dispatching an agent hint, switch `_panel_group.focused_idx` to the target agent's panel before setting
   `current_idx`.
3. Preserve existing back-jump behavior: `_save_agents_jump_anchor()` should continue to run before focus moves, so
   apostrophe back returns to the original agent or banner panel.
4. Add a focused regression test for cross-panel agent hint dispatch: start focused on one panel, enter jump mode,
   dispatch a hint for an agent in another panel, and assert both `current_idx` and focused panel moved to the target.
5. Run the targeted jump/panel tests, then run `just check` per repo instructions after code changes.

## Risk

This is local to Agents-tab jump dispatch. CL, AXE, banner jumps, and jump-all modal behavior should be unaffected.
