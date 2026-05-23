---
create_time: 2026-05-23 15:30:00
status: done
prompt: sdd/prompts/202605/agent_panel_jk_unread.md
---
# Plan: Acknowledge unread agents on Agents-tab `J`/`K` panel switches

## Context

On the `sase ace` Agents tab, lowercase `j`/`k` navigate within the focused agent panel through
`BasicNavigationMixin._navigate_agents_panel`. That path already calls `_acknowledge_agent_unread(agent)` when it lands
on an agent row, so the unread checkbox icon is removed and the matching completion notification is dismissed.

Uppercase `J`/`K` are configured as `focus_next_agent_panel` and `focus_prev_agent_panel`. These actions go through
`AgentPanelNavigationMixin._change_focused_agent_panel`, which switches the focused tag panel and moves `current_idx` to
the first or last selectable row in the newly focused panel. That path refreshes panel highlights and details but does
not call the unread acknowledgment helper for the selected agent. As a result, `J`/`K` can visibly focus an unread
completed agent without marking it read.

The desired behavior is: when `J` or `K` lands on an agent row, it should behave like other row-selection navigation and
acknowledge that row. When it lands on a collapsed group banner, it should not acknowledge the backing agent because the
user selected the banner, not the row itself.

## Implementation Approach

1. Add unread acknowledgment to the panel-switch path after `_change_focused_agent_panel` chooses its destination.
   - Track whether the destination is an agent row or a banner.
   - If the destination is an agent row and `current_idx` is valid, call
     `_acknowledge_agent_unread(self._agents[self.current_idx])`.
   - Keep banner destinations as no-ops for unread state.

2. Preserve existing manual-unread semantics.
   - The existing `_acknowledge_agent_unread` helper already refuses to clear manually guarded rows.
   - If `J`/`K` moves away from a manually unread row, match lowercase `j`/`k` behavior by arming the departed row with
     `_arm_manual_unread_after_departure` so it can clear normally when selected again.

3. Preserve existing refresh behavior.
   - Do not add an extra full rebuild when `_acknowledge_agent_unread` can patch the row.
   - Allow the existing fallback inside `_acknowledge_agent_unread` to refresh when a row patch cannot land.
   - Keep the optimized panel focus/highlight refresh path intact.

4. Add focused regression tests.
   - Extend the existing Agents-tab `J`/`K` panel-switch tests in `tests/ace/tui/test_agent_panel_first_selection.py`.
   - Cover `J` landing on an unread completed agent and clearing it.
   - Cover `K` similarly if the test setup is not redundant.
   - Cover a collapsed-banner landing to ensure it does not clear unread state.
   - Cover manual-unread departure arming if not already indirectly covered.

5. Verify with targeted and required repo checks.
   - Run the focused tests for panel switching and unread behavior.
   - Because this repo requires it after file changes, run `just install` if needed, then `just check`.

## Risks

- The panel-switch code has optimized refresh paths, so the fix should avoid adding unconditional display rebuilds.
- Banner stops intentionally carry a backing `current_idx`; acknowledging on every `current_idx` update would
  incorrectly mark a hidden row read.
- Manual unread is session-local and deliberately sticky until the user leaves and reselects the row; reusing the
  existing helper avoids duplicating that policy.
