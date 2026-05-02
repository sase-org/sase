---
create_time: 2026-04-04 10:33:03
status: done
prompt: sdd/prompts/202604/agents_tab_pinned_indicator_1.md
---

# Plan: Agents Tab Pinned (`+N`) Indicator

## Problem

The Agents tab title currently shows `Agents (x1)` where `x` is the dismiss keybinding and the count represents
dismissable (done/failed) agents. This doesn't distinguish between pinned and non-pinned dismissable agents.

The user wants the tab title to show `+<N>` for pinned agents — e.g., `Agents (+1)` when there's 1 pinned agent. The
`x<N>` indicator should still appear for non-pinned dismissable agents.

**Example scenarios:**

- 1 pinned, 0 dismissable: `Agents (+1)`
- 0 pinned, 2 dismissable: `Agents (x2)`
- 1 pinned, 2 dismissable: `Agents (x2 +1)`
- 2 running, 1 pinned, 1 dismissable: `Agents (2 x1 +1)`
- 0 of anything: `Agents`

## Design

The `+` prefix is not a keybinding — it's a fixed indicator for pinned count. The cleanest approach is to treat `+` as
another key-count entry in the existing `key_counts` list, keeping the rendering logic uniform.

### Data Flow Changes

1. **`_loading.py`**: Split the current `done_visible` count into two: `pinned_count` (pinned agents in
   DISMISSABLE_STATUSES) and `done_visible` (non-pinned agents in DISMISSABLE_STATUSES). Pass both to
   `update_agents_count()`.

2. **`tab_bar.py`**: Add `pinned_count` parameter to `update_agents_count()`. Store as `_agents_pinned_count`. In
   `_build_content()`, append a `("+", pinned_count)` entry to the `agents_key_counts` list (after the dismiss key
   entry).

## Changes

### 1. `src/sase/ace/tui/actions/agents/_loading.py` (~lines 407-420)

Split the `done_visible` sum into two counts:

```python
pinned_visible = sum(
    1
    for a in self._agents
    if a.status in DISMISSABLE_STATUSES
    and not a.is_workflow_child
    and a.identity in self._pinned_agents
)
done_visible = sum(
    1
    for a in self._agents
    if a.status in DISMISSABLE_STATUSES
    and not a.is_workflow_child
    and a.identity not in self._pinned_agents
)
```

Pass `pinned_count=pinned_visible` to `tab_bar.update_agents_count()`.

### 2. `src/sase/ace/tui/widgets/tab_bar.py`

- Add `_agents_pinned_count: int = 0` field in `__init__`.
- Add `pinned_count: int = 0` parameter to `update_agents_count()`.
- Store and dirty-check `_agents_pinned_count` alongside the other counts.
- In `_build_content()`, append `("+", self._agents_pinned_count)` to `agents_key_counts` after the dismiss key entry.

### 3. Tests

Update or add tests validating:

- Tab shows `+1` when 1 pinned agent exists
- Tab shows `x2` when 2 non-pinned dismissable agents exist
- Tab shows `x1 +1` when both exist
- Tab shows nothing extra when neither exists
