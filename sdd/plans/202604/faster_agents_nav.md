---
create_time: 2026-04-15 17:09:00
status: done
prompt: sdd/prompts/202604/faster_agents_nav.md
---

# Plan: Make Agents Tab j/k Navigation WAY Faster

## Problem

Profiling data (`ace_profile_20260415_170038.txt`, 24.9s session, 15958 samples) shows that j/k navigation on the Agents
tab feels sluggish due to two root causes:

1. **Auto-refresh blocks the event loop for ~5s per tick** — `_on_auto_refresh()` calls `_load_agents()` synchronously,
   which calls `load_all_agents()` (heavy disk I/O). Profile: `_load_agents` consumed 5.2s, 2.7s, and 2.5s across three
   auto-refresh cycles = **10.4s blocked out of 24.9s (42%)**. Any j/k press during these windows is queued with zero
   visual feedback.

2. **Setting `current_idx` triggers a full screen repaint** — The Textual `reactive` property calls `AceApp.refresh()`
   automatically after every change, marking the entire screen dirty. This forces the compositor to re-render every
   widget including the expensive `AgentPromptPanel` (Rich syntax highlighting = 1.013s total).

Secondary issues:

- `_navigate_agents_panel()` uses `list.index()` (O(n)) instead of existing O(1) maps
- `_update_agents_info_panel()` rebuilds position data from scratch on every j/k press

## Phases

### Phase 1: Move auto-refresh agent loading off the event loop

**Goal**: Eliminate the 5s event-loop blocks that make the TUI completely unresponsive.

**Approach**: Run the heavy I/O portion of `_load_agents()` in a background thread using `asyncio.to_thread()`, then
apply results on the main thread.

**Files**:

- `src/sase/ace/tui/actions/agents/_loading.py` — Split `_load_agents()` into two parts:
  1. `_load_agents_io()` — Pure data loading (no `self` mutation). Returns the loaded agent list and all computed data.
     This runs in a thread.
  2. `_apply_loaded_agents()` — Takes the results and applies them to `self` (panel indices, display refresh, tab bar
     update). This runs on the main thread.
- `src/sase/ace/tui/actions/event_handlers.py` — Change `_on_auto_refresh()` to be `async` and `await` the threaded
  load. Add a guard flag (`_agents_loading`) to prevent concurrent loads. Skip if a load is already in progress.

**Key constraint**: `_load_agents()` is also called synchronously from places like `_refilter_agents()` fallback and
initial load. Keep a synchronous path available; only the auto-refresh timer path needs to be async.

### Phase 2: Eliminate full-screen refresh on `current_idx` change

**Goal**: When j/k moves the highlight, only update the affected widgets — not the entire screen.

**Approach**: Change `current_idx` from a Textual `reactive[int]` to a plain `int` attribute with a manual property
setter that calls `watch_current_idx()` directly. This bypasses the reactive system's automatic `AceApp.refresh()` call.
The watcher already handles all necessary targeted updates via `_refresh_agents_display_debounced()`.

**Files**:

- `src/sase/ace/tui/app.py`:
  - Remove `current_idx` from the `reactive` declarations (line 112)
  - Add a plain `_current_idx: int` attribute initialized in `__init__` or `on_mount`
  - Add a `current_idx` property with getter/setter that calls the watcher manually
  - The setter should only call the watcher when the value actually changes

**Risk**: Other code may depend on `current_idx` being reactive (e.g. Textual CSS bindings). Audit all reads/writes to
`current_idx` across the codebase to verify nothing depends on the reactive machinery beyond the watcher.

### Phase 3: Use O(1) navigation lookup

**Goal**: Replace linear scan with dictionary lookup in the hot navigation path.

**Files**:

- `src/sase/ace/tui/actions/navigation/_basic.py` — In `_navigate_agents_panel()`, replace:

  ```python
  pos = indices.index(self.current_idx)
  ```

  with a lookup using the appropriate panel idx map:

  ```python
  idx_map = self._active_panel_idx_map()
  pos = idx_map.get(self.current_idx)
  ```

  This requires adding an `_active_panel_idx_map()` helper (or inlining the check on `_pinned_panel_focused`).

- `src/sase/ace/tui/actions/agents/_core.py` — Add `_active_panel_idx_map()` method that returns the correct map based
  on `_pinned_panel_focused`.

### Phase 4: Cache position data for the info panel

**Goal**: Avoid rebuilding `non_child_indices` on every j/k press.

**Files**:

- `src/sase/ace/tui/actions/agents/_display.py` — In `_update_agents_info_panel()`, the method currently:
  1. Builds `main_set = set(self._main_panel_indices)` — O(n)
  2. Filters agents for non-children in main panel — O(n)
  3. Counts position with `sum(1 for i in non_child_indices if i <= current_idx)` — O(n)

  Instead, precompute `_non_child_main_indices` (a sorted list) whenever the agent list changes (in `_load_agents` /
  `_refilter_agents`). Then compute position with `bisect_right(self._non_child_main_indices, self.current_idx)` — O(log
  n).

- `src/sase/ace/tui/actions/agents/_loading.py` — Compute and store `_non_child_main_indices` after
  `_build_panel_indices()`.

## Execution Order

Phase 1 first (biggest impact — eliminates 42% event-loop blocking). Phase 2 next (eliminates unnecessary full
repaints). Phases 3-4 are smaller wins but straightforward.

## Testing

- Run `sase ace` and rapidly press j/k on the Agents tab during auto-refresh
- Verify highlight movement is instant even during background data reload
- Verify agent list updates correctly after background load completes
- Verify fold toggle, search filter, and tab switching still work
- Run `just check` to verify type checking and tests pass
