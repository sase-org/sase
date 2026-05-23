---
create_time: 2026-05-23 15:39:59
status: done
prompt: sdd/prompts/202605/agents_back_jump_sources.md
---
# Agents Back-Jump Sources Plan

## Goal

Make the Agents-tab double-apostrophe workflow treat more navigation commands as jump origins.

Today, pressing `'` enters entry-jump mode and pressing `'` again either restores `_entry_jump_last_agents_anchor` or
falls through to the first jump hint. That anchor is only updated by the one-key apostrophe jump dispatch path. The new
behavior should also update the same back-jump anchor after successful Agents-tab jumps from:

- `,j`: jump to next unread completed agent.
- `,J`: jump to next stopped agent.
- `J`: focus next tag panel.
- `K`: focus previous tag panel.

No keymap configuration changes are needed. This is presentation-layer TUI state and should stay in this repo; the Rust
core boundary does not need to change.

## Current Behavior

The existing back-jump state lives in `src/sase/ace/tui/actions/navigation/_advanced.py`:

- `_save_agents_jump_anchor()` snapshots either the focused agent row or the focused collapsed banner.
- `_restore_agents_jump_anchor()` restores that snapshot and swaps the current location into the anchor so repeated `''`
  toggles between the two locations.
- `_handle_entry_jump_key("apostrophe")` uses the saved anchor on the Agents tab, otherwise falls through to hint `1`.
- `_update_jump_footer()` already advertises apostrophe as `back` whenever `_entry_jump_last_agents_anchor` is set.

The key paths the user wants to include live elsewhere:

- `,j` / `,J` route through `LeaderModeMixin._dispatch_leader_key()` into
  `AgentUnreadMixin._jump_to_next_unread_done_agent()` and `_jump_to_next_stopped_agent()`.
- Both helpers share `_jump_to_next_matching_agent_by_time()`, which already computes the old focused row/panel/group
  before moving.
- `J` / `K` route through `AgentPanelNavigationMixin.action_focus_next_agent_panel()` /
  `action_focus_prev_agent_panel()` into `_change_focused_agent_panel()`, which changes the focused panel and lands on
  the first/last selectable stop in that panel.

Do not include normal lowercase `j` / `k` row movement. Treating every small row step as a jump origin would make `''`
noisy and would overwrite intentional jump history during ordinary scanning.

## Design

Use one shared Agents-tab anchor contract for all these commands rather than creating separate histories per command.
The existing anchor shape is right because it supports both agent rows and collapsed banner rows:

- `("agent", agent_idx, panel_idx)`
- `("banner", panel_idx, group_key)`

Refactor the current snapshot logic slightly so non-apostrophe navigation paths can use it without duplicating the tuple
construction. A good shape is:

- Add an `AgentJumpAnchor` type alias near the current jump target aliases.
- Add a pure helper such as `_current_agents_jump_anchor() -> AgentJumpAnchor`.
- Keep `_save_agents_jump_anchor()` as the existing mutating wrapper for apostrophe jump dispatch.
- Add a narrow helper such as
  `_remember_agents_jump_origin_if_changed(target_idx=..., target_panel_idx=..., target_group_key=None)` or record
  explicitly at call sites after they know a real jump will happen.

The important semantic rule is: record the origin only when the command will actually move focus or switch between a
banner and an agent row. Do not set a back anchor for a no-op, a guard-blocked command, or a failed search.

## Implementation Steps

1. Harden and centralize anchor construction.
   - Add the `AgentJumpAnchor` alias.
   - Factor `_save_agents_jump_anchor()` into current-anchor construction plus assignment.
   - In `_restore_agents_jump_anchor()`, keep the existing toggle behavior, but add minimal stale-anchor guards:
     - agent anchors must still point at a loaded agent index.
     - panel indexes must still be valid before assigning `focused_idx`.
     - stale anchors should return `False` so `''` can fall back to the first hint instead of restoring an invalid row.

2. Track `,j` and `,J`.
   - In `_jump_to_next_matching_agent_by_time()`, after candidates are found and the target row/panel is known, compare
     the target with the current `(current_idx, focused_idx, _current_group_key)`.
   - If the command changes row, panel, or clears a focused banner, save the current Agents anchor before mutating panel
     focus, `_current_group_key`, `current_idx`, or `current_attempt_number`.
   - Preserve existing unread acknowledgement, notification dismissal, refresh behavior, and leader-repeat behavior.
     Repeated `,,` should naturally record the origin of each successful repeated jump.

3. Track `J` and `K`.
   - In `_change_focused_agent_panel()`, after the tab/guard checks and after confirming `focus_next()` / `focus_prev()`
     will change the focused panel, save the current Agents anchor before landing on the new panel's first/last
     selectable stop.
   - Do not record anything when there is only one panel, the current tab is not Agents, or the artifact-viewer guard
     blocks navigation.
   - Preserve current first/last rendered-stop landing semantics, including collapsed banner stops.

4. Keep the footer behavior automatic.
   - Because `_update_jump_footer()` already keys off `_entry_jump_last_agents_anchor`, no footer API change should be
     required.
   - After any successful tracked jump, the next apostrophe entry into jump mode should show the back affordance.

## Tests

Add focused tests rather than broad Pilot coverage.

- Extend Agents apostrophe back-jump tests to cover non-apostrophe origins:
  - After `,j` moves from one agent/panel to an unread completed agent, `''` returns to the origin.
  - After `,J` moves to a stopped agent, `''` returns to the origin and stopped navigation still does not acknowledge
    unread state.
  - From a focused collapsed banner, `,j` or `,J` records the banner anchor before clearing banner focus.
  - Repeating leader jump with `,,` updates the anchor to the immediately previous jump point, not the original point.

- Extend panel-switch tests:
  - After `J`, `''` restores the previous panel/row.
  - After `K`, `''` restores the previous panel/row.
  - If `J` / `K` lands on a collapsed banner, `''` restores the original row or banner.
  - Guard-blocked and one-panel no-op cases do not overwrite an existing anchor.

- Add stale-anchor coverage if `_restore_agents_jump_anchor()` is hardened:
  - removed/out-of-range agent anchor returns `False` and falls back to first hint.
  - invalid panel index does not assign `focused_idx`.

Likely files:

- `src/sase/ace/tui/actions/navigation/jump_hints.py`
- `src/sase/ace/tui/actions/navigation/_advanced.py`
- `src/sase/ace/tui/actions/navigation/_types.py`
- `src/sase/ace/tui/actions/agents/_unread.py`
- `src/sase/ace/tui/actions/agents/_panel_navigation.py`
- `tests/ace/tui/test_jump_hints_for_folded_banners.py`
- `tests/ace/tui/test_agent_unread_done_navigation.py`
- `tests/ace/tui/test_agent_stopped_navigation.py`
- `tests/ace/tui/test_agent_panel_first_selection.py`

## Verification

Run targeted tests first:

```bash
pytest tests/ace/tui/test_jump_hints_for_folded_banners.py \
  tests/ace/tui/test_agent_unread_done_navigation.py \
  tests/ace/tui/test_agent_stopped_navigation.py \
  tests/ace/tui/test_agent_panel_first_selection.py
```

After implementation changes, run the repo-required checks:

```bash
just install
just check
```

No visual snapshots should be required because this is navigation state, not rendering. If footer text changes
unexpectedly in tests, inspect whether an anchor is being recorded for a no-op before updating expectations.
