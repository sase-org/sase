---
create_time: 2026-05-09 17:13:26
status: done
prompt: sdd/prompts/202605/agent_panel_counts.md
---
# Plan: Per-Panel Shorthand Agent Counts

## Goal

Show compact count summaries in each dynamic Agents-tab panel title in `sase ace`. The counts should mirror the metrics
currently shown at the top of the Agents tab, but they must be scoped only to the agents rendered in that specific
panel.

## Current Shape

- The top Agents-tab count strip is rendered by `AgentInfoPanel` in `src/sase/ace/tui/widgets/agent_info_panel.py`.
- Its counts are computed in `src/sase/ace/tui/actions/agents/_display_detail.py::_update_agents_info_panel`.
- Dynamic panel titles are built in `src/sase/ace/tui/actions/agents/_display_panels.py::_agent_panel_border_title`.
- `_refresh_panel_widgets_impl` already has the exact `panel_agents` slice for each panel, making it the right place to
  compute per-panel counts without changing backend/core behavior.
- Existing panel-title tests live in `tests/ace/tui/test_agent_panel_titles.py`.

## Design

Add a small presentation helper in `_display_panels.py` that computes the same metric categories as the top strip for an
arbitrary panel slice:

- `asking`: status is an explicit human-input pause, using `agent_is_asking`.
- `running`: non-terminal/non-dismissable agents excluding waiting, failed, and asking.
- `waiting`: `status_bucket_for(agent) == "Waiting"`.
- `failed`: `status_bucket_for(agent) == "Failed"`.
- `unread`: agent identity is in `_unread_completed_agent_ids`.
- `read`: `status_bucket_for(agent) == "Done"` and identity is not unread.
- total remains the existing panel count after the tag label.

Use compact labels in panel titles to fit narrow widths:

```text
#tag · 6 [A1 R2 W1 F1 U1]
```

Only non-zero shorthand metrics should render. If every metric is zero, the panel title stays at the existing `#tag · N`
/ `(untagged) · N` / `All agents · N` shape. This preserves the current clean title for panels that contain only
uncategorized or empty data.

The shorthand should reuse the same color roles as the top strip where possible, so users can visually map `A/R/W/F/U/D`
to `asking/running/waiting/failed/unread/read`.

## Implementation Steps

1. Add a small count structure/helper in `_display_panels.py`.
   - Keep it local to the TUI presentation layer.
   - Import `agent_is_asking`, `status_bucket_for`, and `DISMISSABLE_STATUSES`.
   - Accept the panel agent slice and the unread identity set.

2. Extend `_agent_panel_border_title`.
   - Preserve the existing tag label and `· N` count.
   - Accept optional shorthand counts.
   - Append compact non-zero metrics in a dim bracket, with styled metric numbers and short labels.

3. Wire per-panel counts from `_refresh_panel_widgets_impl`.
   - Use `panel_agents` and the existing `unread` set already computed for `widget.update_list`.
   - Pass the count summary into `_agent_panel_border_title`.
   - No changes to panel grouping, sorting, focus, or row rendering.

4. Update focused tests.
   - Adjust existing title assertions to expect the compact suffix when statuses produce non-zero metrics.
   - Add explicit coverage that each panel only counts its own agents.
   - Add coverage that unread vs read counts are scoped by panel.
   - Keep grouped-mode title coverage for `All agents`.

5. Verify.
   - Run the focused panel-title/display tests.
   - Run `just install` if needed, then `just check` per repo memory after code changes.

## Risks and Mitigations

- Risk: top-strip and panel-title counts drift over time.
  - Mitigation: factor the per-slice count helper so both title code and tests make the intended metric mapping
    explicit. Avoid duplicating logic deeper than needed.

- Risk: titles become too wide.
  - Mitigation: use one-letter labels, omit zero metrics, and keep the existing total count as the only always-visible
    count.

- Risk: workflow child rows inflate user-facing counts.
  - Mitigation: match the current top strip semantics by counting visible non-child agents only. If a panel slice
    includes workflow children, filter them out before computing shorthand metrics.
