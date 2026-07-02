---
create_time: 2026-07-02 05:53:43
status: done
prompt: sdd/prompts/202607/agents_starting_total.md
---
# Plan: Include STARTING Agents in the Agents Tab Total

## Problem

The Agents tab can show an impossible-looking summary such as `0 [1 starting]`. The underlying behavior is that
transient `STARTING` rows are intentionally hidden from the rendered agent panels, but the info-panel headline total
currently comes from the rendered non-child row count. The separate `starting` metric is computed from the
hidden-starting index, so the bucket can be nonzero while the headline total excludes it.

## Relevant Existing Design

- `AgentPanelIndex` precomputes rendered panel slices, non-child row positions, dismissable counts, and
  `hidden_starting_indices`.
- `agent_is_rendered_in_agents_panel()` deliberately hides `STARTING` rows from panel slices, navigation, and neighbor
  walks.
- `_agent_info_metrics()` builds the info-panel counts from `panel_index.non_child_indices` plus
  `panel_index.hidden_starting_indices`.
- `AgentInfoPanel` displays `_visible_agent_count` as the leading headline count and then displays nonzero status
  buckets such as `starting`, `running`, and `unread`.

The fix should therefore adjust only the aggregate count semantics. It should not make STARTING rows selectable or
rendered in the list.

## Proposed Approach

1. Make the intended total explicit in the cached index/count path.
   - Add a small `AgentPanelIndex` property such as `top_level_total` or `non_child_total_including_hidden_starting`.
   - Define it as rendered top-level rows plus hidden top-level STARTING rows.
   - Keep `non_child_total` as the rendered/selectable top-level total used for row position and navigation semantics.

2. Update the info-panel metrics path to use the inclusive total for the headline.
   - In `_agent_info_metrics()`, compute `starting_count` from `hidden_starting_indices` as today.
   - Return the inclusive top-level total as the displayed agent count.
   - Preserve the existing cache shape and invalidation pattern: no disk reads, no new scans beyond the already cached
     panel-index lists, and no event-loop work.

3. Keep selection/position totals separate from display totals.
   - In `_update_agents_info_panel_impl()`, use a clearly named `selectable_total` for `update_position()` and
     current-row position.
   - Pass the inclusive display total to `AgentInfoPanel.update_state()` as `visible_agent_count`.
   - Also pass the inclusive display total to the legacy `update_agent_counts()` fallback so test harnesses and older
     widget stubs do not preserve the bug.

4. Update tests around the locked-in bad behavior.
   - Change `test_info_panel_agent_counts_use_visible_top_level_agents` so the status buckets still report one starting
     agent, but the count-strip total includes that starting row.
   - Add or extend a model-level `AgentPanelIndex` test proving the inclusive total counts top-level hidden STARTING
     rows while still excluding workflow children.
   - Add a focused regression for the user-observed case: one top-level STARTING agent and no rendered agents should
     produce a displayed total of `1` and a starting bucket of `1`.

5. Verify with targeted and full checks.
   - Run the relevant targeted tests first:
     `pytest tests/ace/tui/models/test_agent_panel_index.py tests/ace/tui/test_agent_panel_index_integration.py tests/ace/tui/widgets/test_agent_info_panel.py`.
   - Because this repo requires it after file changes, run `just install` if needed and then `just check`.

## Non-Goals

- Do not render STARTING rows in the agent list.
- Do not change panel grouping, folding, neighbor navigation, or row selection.
- Do not move this logic into the Rust core backend; this is presentation-only TUI aggregate state.
