---
create_time: 2026-05-08 21:52:29
status: done
prompt: sdd/prompts/202605/agent_counts.md
---
# Agent Counts In The Agents Header

## Goal

Add a compact count strip to the top Agents-tab info panel, near the existing grouping strategy and auto-refresh
controls. The strip should only be visible when the Agents tab is focused, and should show unread, running, and total
agent counts without adding noise to the CLs or AXE views.

## Product Design

Use the existing Agents info panel as the placement. It is already scoped to `#agents-view`, hidden outside the Agents
tab, and contains the current high-value controls/status: selected position, filter, view mode, grouping mode, and
auto-refresh countdown.

Render the counts as a quiet metric strip after the selected position and before filter/view/group/refresh details:

`Agents: 2/12   3 unread · 5 running · 12 total   [group: by status (g)]   (auto-refresh in 8s)`

Styling should make the data scannable without overpowering the active row list:

- `unread`: warm accent, because it asks for attention.
- `running`: green/cyan accent, because it indicates live work.
- `total`: dimmer neutral count, because it is context.
- Separators should be dim so the line reads as one composed status bar, not three loud badges.

## Count Semantics

Use the final visible Agents-tab model after fold/search/hide filtering, matching what the user sees in the list:

- `unread`: visible top-level agents whose identity is in `_unread_completed_agent_ids`.
- `running`: visible top-level agents whose status is not dismissable/terminal.
- `total`: visible top-level agents, same conceptual total as the existing position denominator.

Exclude workflow children so expanded step rows do not inflate the top-level agent totals. This matches the existing
tab-bar count behavior and the current `AgentPanelIndex.non_child_total` denominator.

## Technical Plan

1. Extend `AgentInfoPanel` with stored count fields and an `update_agent_counts(unread, running, total)` method.
2. Update `AgentInfoPanel._update_display()` to render the metric strip when not loading.
3. Compute counts in `DetailMixin._update_agents_info_panel()` from the current finalized `_agents` list and unread
   identity set, using `DISMISSABLE_STATUSES` for active/running semantics.
4. Keep startup loading behavior unchanged: while loading, the panel should still short-circuit to `Agents: …`.
5. Add focused widget tests for the rendered count strip, styling-neutral plain text, and loading suppression.
6. Run the targeted tests, then run `just install` and `just check` as required by repo memory after edits.

## Risk Notes

The main ambiguity is whether "total" should include hidden agents. I will use visible top-level total because the
header is scoped to the visible Agents tab state, aligns with `position/total`, and avoids surprising totals when search
or hide filters are active. Hidden totals already exist in the global tab label.
