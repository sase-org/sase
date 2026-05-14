---
create_time: 2026-05-14 18:51:37
status: done
prompt: sdd/prompts/202605/hide_starting_agent_rows.md
---
# Hide STARTING Agent Rows In The TUI

## Goal

Stop rendering individual `STARTING` agent rows in the Agents tab. Instead, surface their count as a visible metric in
the untagged agent panel and in the existing top info strip. This should reduce TUI row churn caused by transient
pre-run rows while keeping the underlying agent records available for lifecycle, status transitions, and non-display
code.

## Current Shape

- The TUI keeps the loaded visible agents in `self._agents`.
- `AgentPanelGroup` and `AgentPanelIndex` derive rendered tag panels and panel slices from `self._agents`.
- `AgentList.update_list()` renders every agent in each panel slice.
- The global info panel already computes `starting_count` from visible top-level rows in `_agent_info_metrics()`.
- Panel border titles already compute per-panel status chips through `agent_panel_counts()`.
- STARTING rows currently affect panel membership, row counts, navigation stops, grouping buckets, panel sizing, and row
  refreshes.

## Design

Keep `STARTING` agents in `self._agents`, but exclude them from the rendered panel model:

1. Add a single presentation predicate such as `agent_is_rendered_in_agents_panel(agent)` or `agent_is_starting(agent)`
   in the TUI panel/model layer.
2. Update the panel index builder to support hidden display rows:
   - Preserve `keys_per_agent` length and global indexing for every `self._agents` entry.
   - Exclude `STARTING` agents from panel slices, `non_child_indices`, and selectable/display counts.
   - Keep `completed_count` unchanged except that STARTING rows are not completed anyway.
3. Update panel-key generation so `STARTING` agents do not create tag panels:
   - If the only agents are STARTING, the panel set should still be `[None]`.
   - Any STARTING count should be rendered on the untagged panel title, even if the STARTING agents themselves have
     tags.
4. Update navigation helpers that currently call `agents_for_panel()` directly to use the rendered panel slices or a
   filtered `agents_for_panel(..., include_starting=False)` equivalent. This keeps keyboard and mouse mapping aligned
   with what is actually rendered.
5. Keep detail and action behavior conservative:
   - A hidden STARTING row should not be selectable through normal list navigation because it has no row.
   - If `current_idx` points at a STARTING agent after a reload, snap focus to the first rendered row in the focused
     panel.
   - If there are no rendered rows, show empty detail rather than a hidden STARTING agent’s detail.

## Starting Count Display

Show the STARTING count in the untagged panel title regardless of where the hidden STARTING agents would otherwise have
appeared.

- Extend `AgentPanelCounts` or the border-title call path so the untagged title receives a starting count computed from
  all top-level STARTING agents.
- Do not include STARTING in tagged panel titles once rows are hidden.
- Style the STARTING chip like unread count inspiration:
  - Use a visible background for the number.
  - Highlight the `T` chip in panel titles, not only the number.
  - In the global info strip, style both the number and the word `starting` with the highlighted background, mirroring
    the unread metric behavior.

## Tests

Update and add focused tests:

- `AgentPanelGroup.from_agents()` does not create tag panels from STARTING-only tagged agents and still returns `[None]`
  when all rows are hidden.
- `build_agent_panel_index()` excludes STARTING agents from rendered panel slices and non-child totals while retaining
  global `keys_per_agent` alignment.
- `_sync_panel_group()` and panel switching snap selection away from hidden STARTING rows.
- `AgentList` rendering no longer emits STARTING rows, including in `BY_STATUS` mode.
- Panel titles show all STARTING count only on `(untagged)` and use highlighted `T`/number styling.
- `AgentInfoPanel` styles both `starting` count and label with a visible background.
- Existing STARTING row-render unit tests should either move down to pure row-render compatibility if still useful, or
  be updated to assert the list-level renderer hides STARTING rows.
- Update visual snapshots if the info strip or panel title pixels intentionally change.

## Verification

Run targeted tests first:

- `pytest tests/ace/tui/models/test_agent_panels.py tests/ace/tui/models/test_agent_panel_index.py`
- `pytest tests/ace/tui/test_agent_panel_titles.py tests/ace/tui/test_agent_panel_index_integration.py`
- `pytest tests/ace/tui/widgets/test_agent_info_panel.py tests/ace/tui/widgets/test_agent_list_grouping_buckets.py`

Then run the repo-required check after code changes:

- `just install`
- `just check`

If PNG snapshot tests fail only because of intentional highlight changes, inspect `.pytest_cache/sase-visual/` before
deciding whether to update snapshots.
