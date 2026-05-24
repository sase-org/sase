---
create_time: 2026-05-23 19:55:33
status: done
prompt: sdd/prompts/202605/sibling_jump_previous_points.md
---
# Treat sibling agent jumps as entry-jump previous points

## Context

The Agents-tab `~` keymap enters sibling navigation through `TreeNavigationMixin.action_start_sibling_mode`, then
delegates to `AgentSiblingMixin._start_agent_sibling_navigation`. Actual focus changes happen in
`_focus_agent_sibling_by_global_index`.

The double-apostrophe and `ctrl+o` paths share the same previous-point state on the Agents tab:

- `action_jump_to_entry` enters hint mode; pressing apostrophe again calls `_handle_entry_jump_key("apostrophe")`.
- `action_jump_to_entry_fast` prepares the same maps and immediately calls `_handle_entry_jump_key("apostrophe")`.
- `_handle_entry_jump_key` restores `_entry_jump_last_agents_anchor` through `_restore_agents_jump_anchor`; if there is
  no valid anchor, it falls through to hint `1`.
- Other agent navigation paths already populate this anchor by calling `_save_agents_jump_anchor` before moving focus.

The gap is that sibling navigation moves the selected agent, switches panels, acknowledges unread state, and refreshes
views, but it never saves the current agent as `_entry_jump_last_agents_anchor`. As a result, after `~`, `''` or
`ctrl+o` does not treat the pre-sibling location as the previous jump point.

This is TUI presentation/navigation behavior, so it should stay in this repo rather than moving into `sase-core`.

## Implementation Plan

1. Update `src/sase/ace/tui/actions/agents/_siblings.py`.

   In `_focus_agent_sibling_by_global_index`, after the target index and target panel are validated and after the
   artifact viewer guard passes, but before mutating `panel_group.focused_idx`, `_current_group_key`, or `current_idx`,
   save the current Agents-tab anchor when focus will actually change.

   Use the same decoupled pattern already used by panel and unread navigation:
   - compute whether the sibling selection will change the current row, current banner focus, or focused panel;
   - call `getattr(self, "_save_agents_jump_anchor", None)` only if it is callable and a focus change is about to
     happen;
   - do not introduce a hard import or direct dependency from the sibling mixin to the entry-jump mixin.

   This should cover both direct single-sibling jumps and modal-selected sibling jumps, because both paths converge on
   `_focus_agent_sibling_by_global_index`.

2. Preserve existing no-op behavior.

   The anchor should not be overwritten when:
   - the current tab is not `agents`;
   - the selected row has no visible siblings;
   - the sibling chooser is merely opened and then canceled;
   - the target index or target panel cannot be resolved;
   - the artifact viewer guard rejects navigation.

   Existing unread acknowledgment, manual-unread arming, panel switching, focused-panel refresh, detail refresh, and
   modal choice ordering should remain unchanged.

3. Add focused tests in `tests/ace/tui/test_agent_sibling_navigation.py`.

   Extend the local sibling-navigation harness enough to exercise the real entry-jump previous-point behavior, likely by
   mixing in `AdvancedNavigationMixin` and initializing the entry-jump fields used by `action_jump_to_entry`,
   `action_jump_to_entry_fast`, and `_restore_agents_jump_anchor`.

   Add coverage for:
   - a direct single-sibling `~` jump stores the origin as `_entry_jump_last_agents_anchor`;
   - `~` followed by `''` restores the origin and toggles the anchor to the sibling location;
   - `~` followed by `ctrl+o` uses the same saved anchor without painting jump hints;
   - multi-sibling modal selection saves the origin only when a sibling is selected;
   - guarded or no-op sibling navigation leaves any existing previous-point anchor intact.

4. Verify with targeted tests first, then repo checks.

   After implementation, run:

   ```bash
   pytest tests/ace/tui/test_agent_sibling_navigation.py tests/ace/tui/test_jump_hints_for_folded_banners.py tests/ace/tui/test_agent_unread_done_navigation.py tests/ace/tui/test_agent_stopped_navigation.py
   ```

   Because this repo requires it after source changes, run `just install` if needed and then `just check` before
   finalizing.

## Non-Goals

- No keymap/default-config changes; `~`, apostrophe, and `ctrl+o` already exist.
- No changes to ChangeSpec sibling navigation.
- No Rust core changes.
- No memory-file changes.
