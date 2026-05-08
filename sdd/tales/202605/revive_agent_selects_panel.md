---
create_time: 2026-05-08 18:16:18
status: done
prompt: sdd/prompts/202605/revive_agent_selects_panel.md
---
# Plan: Select Revived Agents Across Agent Panels

## Goal

When a dismissed agent is revived via the `R` keymap from the Agents tab, the revived agent should become the selected
agent after reload even if the user had a different tag panel focused before invoking revive. This means both the
selection index and the focused Agents-tab panel must point at the revived agent.

## Current Behavior

The single-agent revive path in `src/sase/ace/tui/actions/agents/_revive.py` already tries to auto-select the revived
agent after `_load_agents()` by scanning `self._agents` for the revived identity or raw suffix and setting
`self.current_idx`.

That is not sufficient in the current tag-panel UI:

- The focused panel is stored separately in `self._panel_group.focused_idx`.
- `_refresh_agents_display(list_changed=True)` calls `_sync_panel_group()`, which preserves the previously focused panel
  key when possible.
- If `current_idx` points at an agent outside that focused panel, `_sync_panel_group()` can snap selection back into the
  old focused panel.
- Banner focus is stored separately in `self._current_group_key` and can also prevent the detail/footer from treating an
  agent row as the active selection.

Batch revive currently reloads agents but does not perform an explicit post-revive selection.

## Implementation Strategy

Add one small panel-aware helper to the revive mixin, then call it from the revive flows after `_load_agents()`:

1. Add a helper such as `_select_revived_agent(agent: Agent) -> bool` in `_revive.py`.
2. Locate the revived row by exact identity first, with raw-suffix fallback to cover name rewrites and loader identity
   changes.
3. Set `self._current_group_key = None` so the selection is an agent row, not a collapsed group banner.
4. Set `self.current_idx` to the matched global agent index.
5. If `self._panel_group` exists and the app has panel-key helpers available, compute the matched agent's rendered panel
   key with `_panel_keys_per_agent()` and set `self._panel_group.focused_idx` to that panel's index.
6. Clear `current_attempt_number` when present so the revived live row, not a prior-attempt view, is selected.
7. Refresh with `list_changed=True` when the Agents tab is active. This full refresh is appropriate because panel focus
   may have changed.

The helper should be defensive because the existing revive tests use a minimal fake app that does not initialize the
full panel state. In that harness, selecting by `current_idx` should still work and missing panel-specific attributes
should simply be skipped.

For batch revive, select the first revived top-level agent from the user's selected list that appears after reload. This
keeps behavior deterministic without surprising users by jumping to a child/follow-up that was implicitly restored.

## Files To Change

- `src/sase/ace/tui/actions/agents/_revive.py`
  - Add the panel-aware selection helper.
  - Replace the current inline single-agent auto-select loop with the helper.
  - Call the helper from `_do_revive_agents()` after the single `_load_agents()`.

- `tests/test_agent_revive.py`
  - Extend the fake app only as needed for panel-aware selection tests.
  - Add a regression test showing a revived agent in a non-focused tag panel becomes selected and that panel becomes
    focused.
  - Add a regression test that stale banner focus is cleared on revive.
  - Add a batch revive regression test that the first selected revived parent is selected after reload.

## Verification

Run focused tests first:

```bash
just install
pytest tests/test_agent_revive.py tests/ace/tui/test_agent_panel_first_selection.py tests/ace/tui/test_agent_panel_index_integration.py
```

Because this repo's instructions require it after source edits, run:

```bash
just check
```

## Risks And Mitigations

- **Selection fights `_sync_panel_group()`:** Set the panel focus before the final full refresh so the sync step
  preserves the revived agent's panel rather than snapping back to the previous panel.
- **Minimal test fakes lack panel state:** Keep panel focus updates guarded with `getattr`/`hasattr`, while preserving
  the existing index-only behavior.
- **Identity changes during revive:** Match identity first and raw suffix second, matching the current inline behavior.
- **Collapsed group/banner state:** Explicitly clear `_current_group_key`; selecting a revived agent should not leave
  the UI in a group-focused mode.
