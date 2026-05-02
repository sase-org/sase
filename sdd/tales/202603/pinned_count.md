---
create_time: 2026-03-31 09:45:27
status: done
prompt: sdd/prompts/202603/pinned_count.md
---

# Plan: Exclude Workflow Steps from Agent/Pinned Panel Counts

## Problem

Two count displays in the `sase ace` TUI incorrectly include workflow child steps (the indented `└─` entries) alongside
main agent/workflow entries:

1. **Pinned panel title** — `📌 Pinned (7)` counts all 7 rows (1 parent + 6 child steps). Should show `Pinned (1)`.
2. **Agents header** — `Agents: 5/11` counts all 11 flat entries (agents + workflow steps). Both position and total
   should only reflect non-workflow-child entries.

The tab bar counts (`Agents (1 x4)`) already correctly exclude workflow children via `not a.is_workflow_child` checks in
`_loading.py`.

## Changes

### 1. Fix Pinned panel title count (`_display.py`)

**File:** `src/sase/ace/tui/actions/agents/_display.py` (line ~215-233)

Currently `pinned_count = len(self._pinned_panel_indices)` counts every entry including workflow steps.

**Fix:** Count only entries where `not agent.is_workflow_child`:

```python
pinned_count = sum(
    1 for i in self._pinned_panel_indices
    if not self._agents[i].is_workflow_child
)
```

Use this filtered count for the border title. Keep the full `len(self._pinned_panel_indices)` for display visibility and
height sizing (since workflow steps still take up visual space).

### 2. Fix Agents header count (`_display.py`)

**File:** `src/sase/ace/tui/actions/agents/_display.py` (line ~259-260)

Currently `position = self.current_idx + 1` and `total = len(self._agents)` count all entries.

**Fix:** Compute position and total only among non-workflow-child entries:

```python
non_child_indices = [i for i, a in enumerate(self._agents) if not a.is_workflow_child]
total = len(non_child_indices)
# Find position: if current selection is a workflow child, map to its parent's position
if self._agents:
    # Find the nearest non-child entry at or before current_idx
    position = sum(1 for i in non_child_indices if i <= self.current_idx)
else:
    position = 0
```

This ensures the position counter only ticks when moving between top-level agents/workflows, and the total reflects only
those entries.
