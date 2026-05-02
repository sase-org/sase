---
create_time: 2026-04-15 18:55:34
status: done
prompt: sdd/prompts/202604/fix_jk_nav_race.md
---

# Plan: Fix race condition in TUI j/k navigation where async agent refresh restores stale selection

## Problem

After making agent navigation faster (commit `6ec0b491`), `j`/`k` navigation sometimes jumps to the wrong entry — either
snapping back to the previous entry (as if `k` was pressed) or jumping to a top entry. This only happens during `j`/`k`
navigation.

## Root Cause

There is a race condition in `_load_agents_async()` (`src/sase/ace/tui/actions/agents/_loading.py:87-103`).

The method captures `selected_identity` (the identity of the currently selected agent) **before** the
`await asyncio.to_thread()` call that performs disk I/O. While the disk I/O runs in a background thread, the event loop
continues processing — including `j`/`k` key events that change `current_idx`. When the await completes and
`_apply_loaded_agents()` runs, it uses the **stale** `selected_identity` to restore the selection, overwriting the
user's navigation.

### Detailed trace

1. Auto-refresh timer fires → `_on_auto_refresh()` calls `_load_agents_async()`
2. `selected_identity = self._agents[self.current_idx].identity` — captures agent at index N
3. `await asyncio.to_thread(load_agents_from_disk, ...)` — yields to event loop
4. User presses `j` → `current_idx` becomes N+1 (now pointing at agent B)
5. Await completes → `_apply_loaded_agents()` called with stale `selected_identity` (agent A at index N)
6. `_finalize_agent_list()` searches for agent A, finds it at index N, sets `current_idx = N`
7. Selection jumps **back** to agent A — user sees it as if `k` was pressed

The same race exists when `_schedule_agents_async_refresh()` triggers after tab switching (which shows cached data +
schedules async refresh per commit `9de3c3cc`).

A secondary (less impactful) race also exists with `on_agents_tab`: if the user switches tabs during the disk I/O, the
stale `on_agents_tab=True` causes `_finalize_agent_list` to write `current_idx` (corrupting the other tab's selection)
instead of writing `_agents_last_idx`.

## Fix

Move the capture of `on_agents_tab` and `selected_identity` from **before** the `await` to **after** it, right before
calling `_apply_loaded_agents()`. The `dismissed_snapshot` stays before the await since it's an immutable snapshot
passed to the thread.

### File: `src/sase/ace/tui/actions/agents/_loading.py`

**Change `_load_agents_async` (lines 87-103):**

Before:

```python
async def _load_agents_async(self) -> None:
    import asyncio

    on_agents_tab = self.current_tab == "agents"

    selected_identity: tuple[AgentType, str, str | None] | None = None
    if on_agents_tab and self._agents and 0 <= self.current_idx < len(self._agents):
        selected_identity = self._agents[self.current_idx].identity

    dismissed_snapshot = set(self._dismissed_agents)
    all_agents, dismissed_from_loader = await asyncio.to_thread(
        load_agents_from_disk, dismissed_snapshot
    )
    self._apply_loaded_agents(
        all_agents, dismissed_from_loader, on_agents_tab, selected_identity
    )
```

After:

```python
async def _load_agents_async(self) -> None:
    import asyncio

    dismissed_snapshot = set(self._dismissed_agents)
    all_agents, dismissed_from_loader = await asyncio.to_thread(
        load_agents_from_disk, dismissed_snapshot
    )

    # Capture current state AFTER the await — the user may have navigated
    # (j/k) or switched tabs while disk I/O was in flight.
    on_agents_tab = self.current_tab == "agents"
    selected_identity: tuple[AgentType, str, str | None] | None = None
    if on_agents_tab and self._agents and 0 <= self.current_idx < len(self._agents):
        selected_identity = self._agents[self.current_idx].identity

    self._apply_loaded_agents(
        all_agents, dismissed_from_loader, on_agents_tab, selected_identity
    )
```

This is a 1-file, ~6-line change. The synchronous `_load_agents()` method does not need changes since it blocks the
event loop (no j/k events can interleave).

## Verification

- `just check` passes
- Manual testing: open TUI with multiple agents, hold `j` to scroll rapidly through the list. With the fix, the
  selection should never jump backwards or to the top during auto-refresh cycles.
