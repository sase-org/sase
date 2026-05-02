---
create_time: 2026-04-15 18:18:18
status: done
prompt: sdd/prompts/202604/faster_tab_switching.md
---

# Plan: Faster TUI Tab Switching

## Problem

Tab switching in the TUI is very slow, especially when navigating to the Agents tab.

### Profiling Evidence

From `ace_profile_20260415_181131.txt`, during a session where the user navigated to Agents → AXE → Agents:

| Action            | Target Tab | Blocking Time | Bottleneck                                  |
| ----------------- | ---------- | ------------- | ------------------------------------------- |
| `action_prev_tab` | Agents     | **6.4s**      | `_load_agents()` → synchronous disk I/O     |
| `action_next_tab` | AXE        | **1.1s**      | `_load_axe_status()` → synchronous disk I/O |
| `action_next_tab` | Agents     | **2.7s**      | `_load_agents()` → synchronous disk I/O     |
| **Total**         |            | **~10.3s**    |                                             |

### Root Cause

`watch_current_tab()` in `app.py:547` calls **synchronous** data-loading functions on the main thread:

- Agents tab → `self._load_agents()` (2.7–6.4s of disk I/O)
- AXE tab → `self._load_axe_status()` (~1.1s of disk I/O)

These block the event loop, freezing the entire UI until loading completes.

### Existing Infrastructure (Not Leveraged)

The codebase already has the building blocks for a fast path:

1. **`_load_agents_async()`** (`_loading.py:253`) — does disk I/O in a background thread via `asyncio.to_thread`. Used
   by the auto-refresh timer but **not** by tab switching.
2. **`_refilter_agents()`** (`_loading.py:556`) — lightweight no-I/O refilter from cached `_agents_with_children`. Shows
   stale-but-instant data.
3. **`_agents_loading` flag** (`app.py:250`) — prevents concurrent async loads.
4. **`_agents_with_children` cache** — populated by `_apply_loaded_agents`, reused by `_refilter_agents`.

## Solution: Show Cached Data Immediately, Refresh Async

The strategy is simple: on every tab switch, **immediately display cached/stale data** (instant), then **refresh fresh
data in the background** (non-blocking).

### Phase 1: Agents Tab — Instant Switching

**File: `src/sase/ace/tui/app.py`** — `watch_current_tab()` (line 575-580)

Change the agents tab branch from:

```python
elif new_tab == "agents":
    changespecs_view.add_class("hidden")
    agents_view.remove_class("hidden")
    axe_view.add_class("hidden")
    # Load agents on first access or refresh
    self._load_agents()
```

To:

```python
elif new_tab == "agents":
    changespecs_view.add_class("hidden")
    agents_view.remove_class("hidden")
    axe_view.add_class("hidden")
    # Show cached data immediately if available, then refresh async
    if self._agents_with_children:
        self._refilter_agents()
        self._schedule_agents_async_refresh()
    else:
        # First load ever — must block to populate initial state
        self._load_agents()
```

**File: `src/sase/ace/tui/actions/agents/_loading.py`** — Add new method

Add `_schedule_agents_async_refresh()` that kicks off a background async load:

```python
def _schedule_agents_async_refresh(self) -> None:
    """Schedule an async agent reload without blocking."""
    if self._agents_loading:
        return
    self.call_later(self._run_agents_async_refresh)

async def _run_agents_async_refresh(self) -> None:
    """Run the async agent refresh with loading guard."""
    if self._agents_loading:
        return
    self._agents_loading = True
    try:
        await self._load_agents_async()
    finally:
        self._agents_loading = False
```

This uses Textual's `call_later()` to schedule an async coroutine that will run on the next event-loop iteration, after
the tab UI has already rendered with cached data.

### Phase 2: AXE Tab — Instant Switching

**File: `src/sase/ace/tui/app.py`** — `watch_current_tab()` (line 581-586)

Change the axe tab branch from:

```python
else:  # axe
    changespecs_view.add_class("hidden")
    agents_view.add_class("hidden")
    axe_view.remove_class("hidden")
    # Load axe status
    self._load_axe_status()
```

To:

```python
else:  # axe
    changespecs_view.add_class("hidden")
    agents_view.add_class("hidden")
    axe_view.remove_class("hidden")
    # Show existing state immediately, then refresh async
    self._refresh_axe_display()
    self._schedule_axe_async_refresh()
```

**File: `src/sase/ace/tui/actions/axe_display.py`** — Add async variant and scheduler

```python
async def _load_axe_status_async(self) -> None:
    """Load axe status with disk IO in a background thread."""
    import asyncio

    status_data = await asyncio.to_thread(self._collect_axe_status_data)
    self._apply_axe_status_data(status_data)

def _schedule_axe_async_refresh(self) -> None:
    """Schedule an async axe status reload without blocking."""
    self.call_later(self._load_axe_status_async)
```

This requires splitting `_load_axe_status` into:

1. `_collect_axe_status_data()` — pure I/O, runs in thread (reads process status, metrics, output log, etc.)
2. `_apply_axe_status_data()` — applies results to app state and refreshes widgets (main thread)

### Phase 3: Auto-Refresh Timer — Make AXE Status Async Too

**File: `src/sase/ace/tui/actions/event_handlers.py`** — `_on_auto_refresh()` (line 78)

Currently `_load_axe_status()` is called synchronously in the auto-refresh timer on every tick, blocking the event loop
for ~1s. Change:

```python
# Before
self._load_axe_status()

# After
await self._load_axe_status_async()
```

This makes the periodic auto-refresh fully non-blocking too.

## Expected Impact

| Action                    | Before       | After        | Improvement                 |
| ------------------------- | ------------ | ------------ | --------------------------- |
| Switch to Agents (cached) | 2.7–6.4s     | **<50ms**    | ~100x faster                |
| Switch to AXE (cached)    | ~1.1s        | **<10ms**    | ~100x faster                |
| Switch to ChangeSpecs     | Already fast | No change    | N/A                         |
| Auto-refresh tick         | ~1s blocking | Non-blocking | Event loop stays responsive |

## Files Changed

1. `src/sase/ace/tui/app.py` — `watch_current_tab()`: use cached data + async refresh
2. `src/sase/ace/tui/actions/agents/_loading.py` — Add `_schedule_agents_async_refresh()` and
   `_run_agents_async_refresh()`
3. `src/sase/ace/tui/actions/axe_display.py` — Split `_load_axe_status` into collect/apply, add async variant and
   scheduler
4. `src/sase/ace/tui/actions/event_handlers.py` — Use async axe status in auto-refresh

## Risks and Mitigations

- **Stale data on tab switch**: User sees data from the previous load for a fraction of a second before the async
  refresh updates it. This is the correct tradeoff — instant visual feedback with eventual consistency is far better
  than a multi-second freeze.
- **First-ever load still blocks**: On the very first visit to the agents tab (no cache yet), we still call
  `_load_agents()` synchronously. This is acceptable since app startup already calls `_load_agents()` at line 484 to
  populate tab-bar counts, so the cache will always be warm by the time the user switches tabs manually.
- **Race conditions**: The existing `_agents_loading` flag already handles concurrent load prevention. The AXE tab
  doesn't have this flag yet, but its loads are fast enough (~1s) that races are unlikely; we can add a flag if needed.
