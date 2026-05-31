---
create_time: 2026-05-31 11:35:35
status: done
prompt: sdd/prompts/202605/live_agent_file_panel_diffs.md
---
# Live Agent File Panel Diffs

## Problem

The Agents tab no longer reliably updates the file panel for a selected running agent after the agent edits its
workspace. The live diff fetch itself still works: `AgentFilePanel.refresh_file()` runs `get_agent_diff()` in a
background worker, and the lower diff cache uses a one-second TTL so working-tree edits can surface promptly once a
fetch happens.

The regression is in the refresh trigger. The TUI now relies on an artifact-tree watcher to avoid expensive periodic
Agents-tab reloads. When that watcher is active, `_on_auto_refresh()` skips `_load_agents_async()` unless an artifact
marker under `~/.sase/projects` is dirty or the one-minute sanity floor expires. Plain edits in an agent workspace do
not dirty the artifact tree, so the selected detail panel is not asked to re-fetch its live diff. The file panel's outer
ten-second cache then never gets a chance to age out because `update_display()` is not called at all.

The fix must not restore broad periodic agent scans or add workspace watchers. Those would regress the TUI performance
work that made navigation fast.

## Approach

Add a narrow auto-refresh path for the currently selected active agent only:

- Keep the existing artifact watcher, dirty flags, tab gate, debounce floor, and one-minute sanity refresh behavior for
  the expensive agent loader.
- On an auto-refresh tick where the watcher is active, the current tab is `agents`, and the agent loader is not already
  due, ask the selected `AgentDetail` to refresh only its file panel.
- Use `AgentDetail.refresh_current_file(agent)`, which already routes through `AgentFilePanel.refresh_file()` and starts
  the VCS diff fetch in a Textual background worker.
- Skip the narrow refresh during prompt/hint/accept/jump modes, during j/k navigation, while the full agent loader is
  already running, and when the selected row is not an active agent/workflow status.
- Do not call the artifact loader, do not scan every agent, and do not resolve or materialize workspaces on the UI
  thread.

This restores live diffs for selected running agents while preserving the performance shape: one cheap UI-thread
dispatch per refresh tick, one existing in-flight-deduped background diff for the selected row only, and no broad disk
load on clean watcher ticks.

## Validation

- Add focused tests around `_on_auto_refresh()` showing that clean watcher ticks can refresh the selected active agent's
  file panel without invoking `_load_agents_async()`.
- Keep existing tests proving clean watcher ticks do not run broad background work when no selected active agent needs a
  live diff.
- Cover skip cases for completed agents and collapsed/tools detail modes so the new path stays scoped.
- Run the focused TUI event-handler tests and file-panel diff tests.
- Run `just check` after source changes, per project instructions.
