---
create_time: 2026-04-04 13:25:05
status: done
prompt: sdd/prompts/202604/exclude_pinned_from_agent_count.md
---

# Plan: Exclude Pinned Entries from Agent Count

## Problem

The "Agents: X/Y" display in the side panel counts **all** non-workflow-child agents, including those in the pinned
panel. This inflates both the total and position. For example, with 1 main agent and 1 pinned agent, it shows "Agents:
1/2" instead of "Agents: 1/1".

## Root Cause

In `src/sase/ace/tui/actions/agents/_display.py:292-295`, `_update_agents_info_panel()` builds `non_child_indices` from
the full `self._agents` list without filtering out pinned entries:

```python
non_child_indices = [
    i for i, a in enumerate(self._agents) if not a.is_workflow_child
]
```

## Fix

Filter `non_child_indices` to only include agents whose global index is in `self._main_panel_indices`. This naturally
excludes pinned agents and their workflow children (since `_build_panel_indices()` already routes those to
`_pinned_panel_indices`).

### Change in `_display.py:_update_agents_info_panel()`

Replace the `non_child_indices` list comprehension with:

```python
main_set = set(self._main_panel_indices)
non_child_indices = [
    i for i, a in enumerate(self._agents)
    if not a.is_workflow_child and i in main_set
]
```

This is a single-line-level change. The `position` calculation on line 297
(`sum(1 for i in non_child_indices if i <= self.current_idx)`) continues to work correctly because it still uses global
indices.

## Verification

Run `sase ace --agent` with a pinned agent present and confirm the count excludes pinned entries.
