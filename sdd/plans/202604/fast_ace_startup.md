---
create_time: 2026-04-23 15:13:34
status: done
prompt: sdd/prompts/202604/fast_ace_startup.md
---

# Fast `sase ace` TUI Startup

## Problem

Starting `sase ace` takes **~11.6 seconds** before the first paint. A pyinstrument profile
(`.sase/home/tmp/sase/ace_profile_20260423_150548.txt`) shows **8.22 seconds of blocking work inside `AceApp.on_mount`**
(`src/sase/ace/tui/app.py:462`), dominated almost entirely by agent loading from disk.

### Hot path

```
11.607s  handle_ace_command               main/ace_handler.py:12
  11.607s  AceApp.run                     textual/app.py
    8.221s  AceApp.on_mount               ace/tui/app.py:462
      3.900s  AceApp._load_agents         ← explicit call at app.py:486
      3.665s  reactive.__set__ current_tab → watch_current_tab
        3.644s  AceApp._load_agents       ← triggered by app.py:480
      0.074s  _initialize_agent_tracking
      0.129s  _on_compose                 (widget tree)
```

Inside each `_load_agents` call (~3.6–3.9s):

```
3.5s  load_agents_from_disk
  3.1s  load_all_agents
    1.8s  load_workflow_agent_steps   (ThreadPoolExecutor blocks)
    0.9s  load_done_agents            (ThreadPoolExecutor blocks)
    0.2s  load_workflow_agents
    0.1s  find_all_changespecs
```

## Root Cause

Two independent problems compound:

**1. Double-load bug.** `on_mount` calls `_load_agents()` **twice**:

- When the startup query matches no ChangeSpecs and `_try_startup_fallback()` also fails, `on_mount` assigns
  `self.current_tab = "agents"` (`app.py:480`). That assignment fires the reactive watcher `watch_current_tab`
  (`app.py:549`), which — because `_agents_with_children` is still empty at this point — takes the slow path at
  `app.py:586-587` and calls `self._load_agents()` synchronously.
- Immediately after, `on_mount` itself calls `self._load_agents()` explicitly at `app.py:486` "so the tab bar count is
  populated on startup."

Both calls do identical work and produce identical results. The process-wide JSON LRU cache in `_json_cache.py` helps on
the second pass (files previously read return from memory), but every directory traversal (`iterdir`, `is_dir`,
`exists`) still hits the filesystem, the dedup/sort pipeline still runs, and `find_all_changespecs` still re-parses
every `.gp` file.

**2. Synchronous load blocks first paint.** The load runs on the main thread inside `on_mount`, so the TUI doesn't paint
until all agents have been read. An async variant (`_load_agents_async` at `_loading.py:102`) already exists and is used
when the user switches tabs post-startup (`_schedule_agents_async_refresh` at `_loading.py:276`) — but `on_mount`
doesn't use it.

## Key Insight

The codebase already has the right pattern; we just need to use it at startup. The tab-switch fast path
(`app.py:582-584`) is:

```python
if getattr(self, "_agents_with_children", None):
    self._refilter_agents()                  # in-memory, ~ms
    self._schedule_agents_async_refresh()    # background disk reload
else:
    self._load_agents()                      # cold path
```

If we eliminate the double-load (Phase 1) and then defer the remaining load off the critical path (Phase 2), startup
goes from ~11.6s of black screen to **instant first paint**, with agents populating ~3.5s later in the background.

## Phase 1 — Eliminate the Double-Load

**Goal:** Cut `on_mount` from ~8.2s to ~4.3s with zero UX change. This is the conservative win.

### Approach: `_mounting` guard

The double-load happens because `watch_current_tab` fires while `_agents_with_children` is still empty, so it falls into
the cold path instead of the cheap refilter path. The cleanest fix is an explicit guard: set a `_mounting` flag on the
app while `on_mount` runs, and have `watch_current_tab` short-circuit its load branch when the flag is set — the
explicit call at `app.py:486` will still populate everything.

Why not just reorder `on_mount` to call `_load_agents()` before the tab assignment? Because the tab assignment depends
on `_load_changespecs()` running first (to know whether to fall back to agents), and swapping them would require further
restructuring for no additional benefit. The flag approach is localized and easy to audit.

### File-by-file changes

**`src/sase/ace/tui/app.py`**

- `__init__` (around line 162): add `self._mounting: bool = False` alongside other init state.
- `on_mount` (line 462): wrap the body in `self._mounting = True` / `try…finally: self._mounting = False`. The flag is
  cleared before `on_mount` returns so no downstream reactive changes are affected.
- `watch_current_tab` (line 549): at the top of the `elif new_tab == "agents":` branch (line 577), before the fast-path
  check, short-circuit when `self._mounting` is True — the explicit `_load_agents()` call in `on_mount` will handle
  population. Keep the view show/hide logic running so the UI state is correct.

### Expected savings

~3.6 seconds (the redundant `_load_agents` triggered by the reactive watcher is eliminated). Profile `on_mount` should
drop from ~8.2s to ~4.3s.

### Rollback

Single commit, <20 LOC. Revert by removing the flag and the guard.

## Phase 2 — Async Load, Instant Paint

**Goal:** Reduce _perceived_ startup from ~4.3s (post-Phase-1) to near-zero. The UI paints immediately; agents populate
in the background.

### Approach

Replace the blocking `self._load_agents()` at `app.py:486` with a scheduled async refresh. The pattern already exists in
`_loading.py:276-305` (`_schedule_agents_async_refresh` → `_run_agents_async_refresh` → `_load_agents_async` using
`asyncio.to_thread(load_agents_from_disk, …)`). We just call it from `on_mount`.

A small wrinkle: before the first async load completes, `_agents_with_children` is empty, so the tab bar shows zero
agent counts for ~3.5s. Two options:

- **(a) Show a loading indicator on the tab bar** until the first load resolves. The tab bar widget already has
  `update_agents_count`; we add a "loading" state.
- **(b) Leave counts blank/zero until loaded.** Simpler; the delta is ~3.5s on first start only.

Prefer **(a)** for polish but **(b)** is acceptable for a first cut.

### Edge case: landing on the agents tab with no data

If the startup query matches no ChangeSpecs and the agents tab becomes the default (`app.py:480`), the agents view will
be empty for ~3.5s. We either (i) show a "Loading agents…" placeholder in the agents view, or (ii) fall back to blocking
load **only** on this one path (and still async on the changespecs-tab path, which is the common case). Placeholder is
cleaner and keeps the paths uniform.

### File-by-file changes

**`src/sase/ace/tui/app.py`**

- `on_mount` (line 486): replace `self._load_agents()` with `self.call_after_refresh(self._run_agents_async_refresh)`
  (or equivalent — e.g. `self._schedule_agents_async_refresh()`). This lets the compose/paint cycle finish before the
  background thread spins up.
- Consider also deferring `_load_axe_status()` (line 489) and the axe start/restart block (lines 492-496) via
  `call_after_refresh` — they're small individually but additive. `_load_axe_status` already has
  `_load_axe_status_async` at `axe_display.py:179`.

**`src/sase/ace/tui/actions/agents/_loading.py`**

- Optional: add a thin `_schedule_agents_initial_load()` helper so the startup path is a named method instead of
  reaching into private coalescing state. Keeps `on_mount` readable.

**`src/sase/ace/tui/widgets/tab_bar.py`** (optional, for option (a))

- Add a "loading" dim-style rendering for the agent count until the first load completes.

**`src/sase/ace/tui/widgets/agents_view.py`** (or wherever the agents pane lives)

- Render a "Loading agents…" placeholder when `_agents_with_children` is `None` (distinguishing "not yet loaded" from
  "loaded, empty"). Requires a small state refactor (likely initialising `_agents_with_children` to `None` instead of
  `[]` and handling the distinction downstream).

### Expected savings

`on_mount` drops from ~4.3s (post-Phase-1) to **~150-300ms**. Total `sase ace` launch-to-first- paint goes from 11.6s to
under 1s. The 3.5s of actual disk work still happens but is invisible — the TUI is interactive immediately.

### Rollback

Phase 2 changes are larger but still localized to the startup path. Each of (i) deferring \_load_agents, (ii) deferring
axe status, (iii) loading-indicator UI is a separate commit and revertable independently.

## Phase 3 — Reduce Redundant Disk Work Inside a Single Load

**Goal:** Shave another ~100-300ms off the one-time cold load. Low priority; skip if Phase 1+2 are enough.

### Observations

- `find_all_changespecs()` is called in both `_load_changespecs()` (changespec.py:58) and
  `_load_agents_from_all_sources()` (agent_loader.py:72). Each call parses every `.gp` file in `~/.sase/projects/`. In
  the profile this is ~89ms × 2.
- Directory traversal (`iterdir`, `is_dir`, `exists`) is not cached — observable as ~100-200ms of pathlib/stat churn
  across the load.

### File-by-file changes

**`src/sase/ace/tui/models/agent_loader.py`**

- `load_all_agents` (line 435) and `_load_agents_from_all_sources` (line 59): accept an optional
  `changespecs: list[ChangeSpec] | None = None` parameter. If provided, skip the internal `find_all_changespecs()` call
  and reuse the passed-in list.

**`src/sase/ace/tui/actions/agents/_loading_helpers.py`**

- `load_agents_from_disk` (line 117): accept and thread-through the optional `changespecs` arg.

**`src/sase/ace/tui/actions/agents/_loading.py`**

- `_load_agents` (line 88) and `_load_agents_async` (line 102): pass `self._all_changespecs` when it's already populated
  (set by `_load_changespecs` at changespec.py:59). When the agent load is triggered before changespecs are loaded, fall
  back to None → internal `find_all_changespecs` runs as today.

### Expected savings

~100-300ms per cold load. Marginal after Phase 2 (where the user doesn't perceive the load at all), but it reduces
background CPU and makes the auto-refresh interval cheaper.

### Rollback

Parameter-threading-only change, easy revert.

## Test Strategy

Run these checks after each phase. The critical invariant: `just check` must pass and the TUI must look and behave
identically.

### Functional smoke test (manual, after each phase)

1. `sase ace` with a normal query → ChangeSpecs tab loads, agents count appears on tab bar within ~3.5s of first paint
   (Phase 2) or immediately (Phase 1 only).
2. `sase ace '!!!'` forcing no matches → should fall back to agents tab with placeholder/loading indicator, then
   populate.
3. Tab-switch to agents, wait, switch to changespecs, back to agents → still works (`_schedule_agents_async_refresh`
   fast path).
4. Dismiss an agent (`x`) → still fast (this is the existing fast-dismissal path; don't break it).
5. `sase ace --profile` → re-capture a profile. Verify:
   - Phase 1: `_load_agents` called exactly once in `on_mount`.
   - Phase 2: `on_mount` under ~300ms; `load_agents_from_disk` appears on a worker thread, not under `on_mount`.
6. Axe auto-start: launch with axe off, confirm it starts. Launch with `--restart-axe`, confirm it restarts. These must
   still happen even if deferred.
7. Refresh timer: with `--refresh-interval 5`, wait 10s and confirm auto-refresh fires.

### Regression test (automated)

- Run `just test` — existing TUI tests should still pass.
- Add a targeted test: simulate `on_mount` with a mock `_load_agents` and assert it's called exactly once regardless of
  whether the tab-fallback path triggers.

### Perf test

Capture `sase ace --profile` three times per phase, report median `on_mount` duration and total duration. Target:

- Baseline: 11.6s total / 8.2s `on_mount`
- Post-Phase-1: ~8s total / ~4.3s `on_mount`
- Post-Phase-2: ~4s total / ~300ms `on_mount`, with load visible on a worker thread
- Post-Phase-3: ~3.8s total / same `on_mount`, worker load slightly faster

## Don't Do

- **Don't cache `load_all_agents()` results across `on_mount` invocations.** Agents change between runs; a process-wide
  result cache would stale quickly. The per-file `_MTimeJsonCache` is the right granularity.
- **Don't skip `axe auto-start` or `--restart-axe`.** They may be deferred via `call_after_refresh` but must still
  execute.
- **Don't reorder `on_mount` to put `_load_agents` before `_load_changespecs`.** The fallback logic
  (`_try_startup_fallback`) needs changespecs first. Use the `_mounting` flag approach instead.
- **Don't drop the agents tab-bar counts.** Counts must populate as soon as the async load completes. A
  missing-during-startup count is OK; a permanently-missing count is a regression.
- **Don't change `_MTimeJsonCache` semantics.** It's a correct, thread-safe LRU keyed on mtime+size; do not increase or
  decrease its scope.
- **Don't remove the existing async refresh path** (`_schedule_agents_async_refresh` + `_run_agents_async_refresh`).
  Phase 2 reuses it — it's already the hot path post-startup.
- **Don't add a new ThreadPoolExecutor.** The loader module already owns `get_loader_executor()` (`_json_cache.py:79`).
  All parallel I/O should go through it.
- **Don't widen scope to refactor the loader module.** This plan touches startup only; the loader internals (dedup
  pipeline, status overrides) are out of scope.
