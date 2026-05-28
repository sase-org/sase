---
create_time: 2026-05-28 18:15:37
status: done
prompt: sdd/prompts/202605/agents_refresh_gating.md
---
# Plan: Gate Watcher-Triggered Agents Reloads

## Goal

Implement the prior performance recommendation by preventing artifact watcher events from immediately scheduling full
Agents reloads. The TUI should keep marking Agents data dirty for row-relevant artifact changes, but let the existing
visible-tab auto-refresh gate, debounce floor, tab-switch refresh, and sanity refresh decide when the expensive loader
actually runs.

## Current State

- `_on_artifact_change()` in `src/sase/ace/tui/actions/_event_refresh.py` already maps changed paths to target surfaces
  and marks `_dirty_agents`.
- The auto-refresh path already:
  - skips Agents loads while off the Agents tab unless the sanity floor is due,
  - applies `AGENTS_LOAD_MIN_INTERVAL_SECONDS`,
  - keeps `_dirty_agents` set when a gated load is deferred,
  - clears `_dirty_agents` only after a load consumes it.
- `AceApp.watch_current_tab()` already schedules an Agents refresh when the user switches to the Agents tab and
  `_dirty_agents` is still set.
- The remaining bypass is `_on_artifact_change()` directly calling `_schedule_agents_async_refresh()` whenever an
  agent-affecting path arrives.

## Implementation

1. Change `_on_artifact_change()` so agent-affecting watcher events only mark `_dirty_agents = True`.
2. Keep immediate ChangeSpec scheduling intact for `.gp`, `.sase`, bead, and unknown all-surface events, because this
   task is focused on the expensive Agents loader.
3. Preserve existing prompt-input and j/k navigation deferral behavior before any scheduling decisions.
4. Update nearby comments/docstrings so the code explains that Agents reloads are consumed by auto-refresh/tab-switch
   gates rather than watcher callbacks.

## Tests

1. Update `tests/ace/tui/test_event_handlers_dirty_flags.py` expectations so agent-only artifact changes dirty Agents
   without appending `schedule_agents`.
2. Update mixed/all-surface artifact-change tests to expect only ChangeSpec scheduling where relevant.
3. Update deferred prompt-input tests to preserve deferred-path behavior while confirming resumed agent-only changes do
   not schedule an immediate Agents load.
4. Update `tests/ace/tui/test_event_handlers_nav_gate.py` for the new idle watcher dispatch behavior.
5. Run the focused tests:
   - `pytest tests/ace/tui/test_event_handlers_dirty_flags.py tests/ace/tui/test_event_handlers_nav_gate.py`
6. Because source files changed, run `just check` before finishing, after `just install` if the workspace venv requires
   it.

## Risk And Mitigation

- Main risk: visible Agents updates may wait until the next auto-refresh tick instead of arriving immediately. This is
  intentional for perceived navigation performance, and the existing tab-switch and manual refresh paths still give
  explicit refresh points.
- Main regression risk: tests or callers may depend on watcher-triggered immediate Agents scheduling. Focused tests
  should encode the new contract: watcher events mark dirty; gated refresh paths consume dirty state.
