---
create_time: 2026-05-15 09:49:15
status: done
prompt: sdd/prompts/202605/remove_starting_panel_shorthand.md
---
# Remove STARTING Shorthand From Agent Panel Titles

## Goal

Stop showing the compact `T<n>` STARTING-agent metric in any Agents-tab panel title. STARTING agents should continue to
be counted only in the top Agents info strip, where the label is already rendered as `<n> starting`.

## Current Behavior

- STARTING rows are intentionally hidden from rendered panel lists by `agent_is_rendered_in_agents_panel()` in
  `src/sase/ace/tui/models/agent_panels.py`.
- Hidden STARTING rows are tracked separately in `AgentPanelIndex.hidden_starting_indices` in
  `src/sase/ace/tui/models/agent_panel_index.py`.
- The top info strip already uses that hidden count through `_agent_info_metrics()` and `AgentInfoPanel.update_state()`
  in `src/sase/ace/tui/actions/agents/_display_detail.py`.
- The unwanted panel title shorthand is injected in two panel-title paths:
  - Full refresh: `src/sase/ace/tui/actions/agents/_display_panel_refresh.py`
  - Incremental row patch refresh: `src/sase/ace/tui/actions/agents/_display_panel_patches.py`
- The panel title metric set currently includes `("starting", "T")` in
  `src/sase/ace/tui/actions/agents/_display_panel_titles.py`.
- Tests currently encode the old behavior in `tests/ace/tui/test_agent_panel_titles.py`, especially
  `test_panel_title_counts_are_scoped_to_each_panel()` and
  `test_panel_title_starting_count_is_scoped_to_untagged_panel()`.

## Implementation Plan

1. Remove STARTING from the panel-title shorthand model.
   - Drop `starting` from `_PANEL_METRIC_LABELS` so `AgentPanelCounts.metric_items()` cannot render `T<n>`.
   - Remove the `with_starting()` helper if it becomes unused.
   - Keep the style entry only if another local import or test needs it; otherwise remove it from panel-title styles as
     part of dead-code cleanup.

2. Stop injecting hidden STARTING counts into panel title counts.
   - Remove the `hidden_starting_count` calculation and `counts.with_starting(...)` branch in
     `_display_panel_refresh.py`.
   - Remove the equivalent `counts.with_starting(...)` branch in `_display_panel_patches.py`.
   - Leave `AgentPanelIndex.hidden_starting_indices` intact because selection snapping and the top info strip still use
     it.

3. Preserve panel existence and visible-row behavior.
   - Keep `_panel_keys_for()` behavior that creates the untagged panel when hidden STARTING agents exist. This avoids
     changing focus targets or empty-state behavior while agents are in the transient pre-run state.
   - Do not make STARTING agents visible in any panel list.

4. Preserve top-strip STARTING reporting.
   - Do not change `_agent_info_metrics()` or `AgentInfoPanel`; those already report STARTING only at the top of the
     TUI.
   - Keep existing info-panel tests that assert `<n> starting` is rendered.

5. Update focused tests.
   - Change `test_panel_title_counts_are_scoped_to_each_panel()` so the untagged title no longer includes `T1`; it
     should show only the visible waiting count.
   - Replace or rename `test_panel_title_starting_count_is_scoped_to_untagged_panel()` to assert that no panel title
     includes the STARTING shorthand even when hidden STARTING agents exist.
   - Remove panel-title style assertions that target the STARTING shorthand.
   - Keep or add an assertion that the top info-panel path still receives the hidden STARTING count, using the existing
     integration/info-panel tests.

## Verification

- Run the targeted tests first:

```bash
pytest tests/ace/tui/test_agent_panel_titles.py tests/ace/tui/test_agent_panel_index_integration.py tests/ace/tui/widgets/test_agent_info_panel.py
```

- If implementation files are changed, follow repo guidance and run:

```bash
just install
just check
```

## Risks

- Removing the panel-level `T<n>` display should not affect navigation because STARTING rows remain hidden and indexed
  separately.
- Leaving the empty untagged panel when only STARTING agents exist may still look visually sparse, but it preserves the
  existing transient focus target while the top strip communicates the STARTING count.
