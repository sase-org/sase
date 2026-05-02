---
create_time: 2026-03-30 20:19:38
status: done
prompt: sdd/prompts/202603/fix_kill_agent_index_error.md
---

# Fix IndexError in \_do_kill_agent Panel Index Refresh

## Problem

When killing an agent via the TUI's "edit and relaunch" flow, an `IndexError: list index out of range` occurs at
`_display.py:71`:

```python
main_agents = [self._agents[i] for i in self._main_panel_indices]
```

## Root Cause

In `_killing.py:_do_kill_agent()`, after an agent is killed:

1. The killed agent (and its workflow children) are removed from `self._agents` (lines 201-223)
2. `self.current_idx` is clamped to the new list length (lines 227-233)
3. `self._refresh_agents_display(list_changed=True)` is called (line 234)

But `_main_panel_indices` and `_pinned_panel_indices` are **stale** — they were computed from the old `self._agents`
list (before the killed agent was removed). The indices now reference positions that may be out of bounds in the
shortened list.

The method `_build_panel_indices()` (in `_core.py:90`) exists specifically to rebuild these index maps from the current
`self._agents`, but it is never called between the agent removal and the display refresh.

## Fix

Add a single `self._build_panel_indices()` call in `_do_kill_agent` after removing agents from `self._agents` and before
the `on_agents_tab` block that calls `_refresh_agents_display`. This ensures the panel index maps are consistent with
the current agent list.

### File: `src/sase/ace/tui/actions/agents/_killing.py`

Insert `self._build_panel_indices()` at line 225 (after the workflow children removal block, before the `on_agents_tab`
check).
