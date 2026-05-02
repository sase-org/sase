---
create_time: 2026-04-23 15:36:34
status: done
prompt: sdd/prompts/202604/fix_y_keymap_blocks_tui.md
---

# Plan: Fix `y` keymap blocks TUI navigation during refresh

## Problem

Pressing `y` in the `sase ace` TUI triggers a full refresh. During that refresh the TUI becomes unresponsive — the user
cannot navigate (`j`/`k`, tab-switch, etc.) until the refresh completes. Recent commits
(`ea03d270 Make sase ace TUI refresh feel instant`, `9de3c3cc Make TUI tab switching instant`,
`8b725299 Resolve race condition in TUI j/k navigation during async agent refresh`) addressed similar issues for the
Agents tab and tab switching, but the manual `y` refresh was not fully converted to the async pattern on the other tabs.

## Root Cause

`y` is bound to `action_refresh` in `src/sase/ace/tui/bindings.py:31`. The handler at
`src/sase/ace/tui/actions/base.py:344-353` branches by tab:

```python
def action_refresh(self) -> None:
    if self.current_tab == "agents":
        self._schedule_agents_async_refresh()   # non-blocking
    else:
        self._reload_and_reposition()           # BLOCKS event loop
    self.notify("Refreshed")
```

- **CLs tab.** `_reload_and_reposition` (`src/sase/ace/tui/actions/changespec.py:128-167`) calls
  `find_all_changespecs()` synchronously on the event loop thread. With many `.gp` files this is several seconds of disk
  I/O. Textual cannot dispatch keypresses during that time.
- **Axe tab.** The `else` branch falls through to the same `_reload_and_reposition` (wrong function for that tab —
  nominally harmless because it just rebuilds the CLs list the user can't see, but it still blocks). The correct
  `_load_axe_status` is also synchronous disk I/O.
- **Agents tab.** Already non-blocking via `_schedule_agents_async_refresh`
  (`src/sase/ace/tui/actions/agents/_loading.py:276-305`).

The same blocking pattern exists in the timer-driven path: `_on_auto_refresh` at
`src/sase/ace/tui/actions/event_handlers.py:107` calls the sync `_reload_and_reposition()` after awaiting the async
agent load, so timer-triggered refreshes also briefly freeze the event loop once every `refresh_interval` seconds.

## Prior Art

The codebase already has the exact async pattern we need — twice:

**Agents** (`src/sase/ace/tui/actions/agents/_loading.py`):

- `_schedule_agents_async_refresh()` (276-289): returns immediately via `self.call_later(...)`, with `_agents_loading` /
  `_agents_refresh_pending` flags for last-request-wins semantics (stampedes collapse to at most one in-flight load +
  one follow-up).
- `_run_agents_async_refresh()` (291-305): async runner guarded by the flags.
- `_load_agents_async()` (102-128): pushes `load_agents_from_disk` to `asyncio.to_thread`, then re-captures UI state
  (`current_tab`, `selected_identity`) **after** the await so the load survives user navigation in flight.

**Axe** (`src/sase/ace/tui/actions/axe_display.py`):

- `_load_axe_status_async()` (179-184) and `_schedule_axe_async_refresh()` (186-188) — simpler, no in-flight guard, but
  same `asyncio.to_thread` pattern. Already used by auto-refresh and startup.

The fix is to introduce the same pattern for changespecs and re-route all refresh entry points through the async
schedulers.

## Changes

### 1. Add async changespec refresh infrastructure

**File:** `src/sase/ace/tui/actions/changespec.py`

Add alongside the existing synchronous `_reload_and_reposition` (do not modify or remove it):

- `async def _reload_and_reposition_async(self, current_name: str | None = None) -> None` — mirror of the sync version,
  but `all_changespecs = await asyncio.to_thread(find_all_changespecs)`. Re-capture `current_name` and `current_idx`
  **after** the await (user may have moved selection during the load), following the pattern at
  `agents/_loading.py:119-124`.
- `def _schedule_changespecs_async_refresh(self) -> None` — returns immediately via
  `self.call_later(self._run_changespecs_async_refresh)`, with `_changespecs_loading` / `_changespecs_refresh_pending`
  flags for last-request-wins semantics.
- `async def _run_changespecs_async_refresh(self) -> None` — async runner that sets the loading flag, awaits
  `_reload_and_reposition_async()`, and reschedules itself if a pending request arrived mid-flight.

Initialize `_changespecs_loading: bool = False` and `_changespecs_refresh_pending: bool = False` in the app `__init__`
(`src/sase/ace/tui/app.py`) next to the existing `_agents_loading` / `_agents_refresh_pending` attributes.

### 2. Route `action_refresh` through the async schedulers for every tab

**File:** `src/sase/ace/tui/actions/base.py`

Rewrite `action_refresh` (344-353):

```python
def action_refresh(self) -> None:
    if self.current_tab == "agents":
        self._schedule_agents_async_refresh()
    elif self.current_tab == "changespecs":
        self._schedule_changespecs_async_refresh()
    else:  # axe
        self._schedule_axe_async_refresh()
    self.notify("Refreshed")
```

The "Refreshed" toast fires immediately; the I/O happens off-thread. No branch blocks the event loop.

### 3. Make auto-refresh non-blocking on the CLs tab

**File:** `src/sase/ace/tui/actions/event_handlers.py`

In `_on_auto_refresh` at line 107, replace the sync `self._reload_and_reposition()` with
`await self._reload_and_reposition_async()`. This fixes the same freeze on the timer-driven path.

### 4. Keep the synchronous `_reload_and_reposition`

The sync helper has ~20 other callers across `marking.py`, `changespec.py`, `agent_workflow/`, `hints/`,
`proposal_rebase.py`, `rename.py`, `status.py`, `task_actions.py`, and `axe.py` (enumerated in the grep output during
investigation). Each of them runs right after a user-triggered state mutation and wants a synchronous repaint.
Converting them all is not in scope; they are not the reported pain point, and doing so would balloon the diff with risk
of subtle ordering regressions. The async variant is introduced **solely** for refresh entry points that must keep the
event loop responsive.

## Tests

**Add:** `tests/ace/tui/test_y_keymap_non_blocking.py` (or a section in an existing test file under `tests/ace/tui/` if
one fits — inspect `tests/ace/tui/test_file_panel_selection_preserved.py` for the preferred Textual `run_test()` harness
style). The test should:

1. Stub `find_all_changespecs` to sleep briefly (enough to be observable) before returning.
2. Press `y` on the CLs tab.
3. Before the stub returns, send `j` and assert that `current_idx` changed — i.e. the event loop was responsive during
   the load. On the current sync implementation the `j` would queue up behind the disk I/O; on the async implementation
   it is processed immediately.
4. After the stub returns, assert the changespec list reflects the stubbed data.

A parallel test for the Axe tab is worthwhile if the existing harness supports it; otherwise cover axe and agents via
manual verification (their async paths are already exercised by existing tests).

Existing `tests/ace/tui/test_reload_and_reposition.py` continues to cover the sync path unchanged.

## Files

- **Modify:** `src/sase/ace/tui/actions/changespec.py` (add async methods, ~40 lines)
- **Modify:** `src/sase/ace/tui/actions/base.py` (rewrite `action_refresh`, ~8 lines)
- **Modify:** `src/sase/ace/tui/actions/event_handlers.py` (one-line swap at line 107)
- **Modify:** `src/sase/ace/tui/app.py` (two new instance attributes in `__init__`)
- **Add:** `tests/ace/tui/test_y_keymap_non_blocking.py` (or extend an adjacent test file)

## Out of Scope

- Converting the ~20 other callers of `_reload_and_reposition` to async. They are post-mutation repaints, not refresh
  entry points, and the user report is specifically about `y`.
- Footer / help-modal text. Per `src/sase/ace/AGENTS.md`, `y` is a global keymap shown only in the help modal, and its
  user-visible behavior (press `y` to refresh) is unchanged — only responsiveness during the refresh changes.
- Any change to the refresh interval, dedup semantics, or what constitutes a "stale" agent.
- Unifying the agents/axe/changespec scheduler helpers behind a common base — three copies of a small pattern is
  acceptable; an abstraction here would be speculative.

## Validation

- `just install` in the ephemeral workspace (dependencies may be stale), then `just check` (ruff + mypy + pytest).
- Manual: open `sase ace` in a project with many `.gp` files, press `y` on each tab, confirm `j`/`k`/tab-switch work
  immediately — before the "Refreshed" data settles.
- Manual: let auto-refresh fire (default 10s) on the CLs tab while holding `j`; confirm no stutter.
