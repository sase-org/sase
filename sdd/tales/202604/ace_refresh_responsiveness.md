---
create_time: 2026-04-23 14:24:34
status: done
---

# Plan: Make `sase ace` TUI refresh feel instant

## Problem

Pressing the `y` keymap in the `sase ace` TUI can freeze the UI for several seconds. The problem is especially bad right
after launching one or more agents. Pyinstrument profile (`~/tmp/ace_profile_20260423_133927.txt`, 34.3 s total, 19,271
samples) makes the cause unambiguous:

- `AceApp._load_agents` (sync) at `src/sase/ace/tui/actions/agents/_loading.py:79` — **7.193 s on the event-loop
  thread**, split across:
  - `action_refresh` (`y` keymap) at `src/sase/ace/tui/actions/base.py:344` — 4.794 s
  - A post-launch / post-notification `call_later(self._load_agents)` — 2.858 s
- Inside each load, `load_agents_from_disk` → `_load_agents_from_all_sources` dominates: `load_workflow_agent_steps`
  (2.544 s + 1.062 s + 0.998 s across three calls), `load_done_agents` (1.329 s + 0.492 s), `load_dismissed_bundles`
  (1.861 s + 0.644 s + 0.561 s), and `enrich_agent_from_meta` (~0.93 s). All of this is JSON file I/O on the main
  thread.

There is already an async variant (`_load_agents_async` / `_schedule_agents_async_refresh`) used by the auto-refresh
timer and tab switching. The `y` keymap and every post-action refresh site still use the sync version, so they block the
UI. The async wrapper also drops concurrent requests (returns early when `_agents_loading` is True), so even if we swap
over, coalesced requests could leave a stale list on screen.

## Goals

1. `y` (and any UI-thread-triggered refresh) must return control to the user immediately — under ~20 ms before the toast
   shows. Data updates the moment the background thread returns.
2. Launching one or many agents must not regress UI responsiveness. Each launch issues a refresh; many refreshes must
   coalesce cleanly without losing the final state.
3. The underlying `load_agents_from_disk` wall-clock should drop far enough that even cold refreshes are sub-second.
   Warm refreshes (nothing changed on disk) should be essentially free.

## Non-goals

- Restructuring the agent/ChangeSpec model.
- Changing how disk artifacts are laid out (`~/.sase/projects/...`).
- Eliminating all synchronous callers — a few (initial `on_mount`, revive flows that immediately inspect `self._agents`)
  must stay sync.

## In-scope steps

The plan is layered. Steps 1–3 are the cheap wins that address the user's immediate pain; steps 4–5 are the structural
fix for the underlying I/O cost. We do all of them in this change unless otherwise noted.

### Step 1 — Route `y` (and similar) through the async path

- Change `action_refresh` in `src/sase/ace/tui/actions/base.py:344` so the agents-tab branch calls
  `self._schedule_agents_async_refresh()` instead of `self._load_agents()` and fires the "Refreshed" notify immediately.
- `self._refresh_agent_file()` in that same method reads the file panel for the currently selected agent — it is fast
  today, but once the list is refreshed asynchronously, the file-panel refresh should happen after the async load
  completes (hook off the post-apply path, or call it again after `_apply_loaded_agents`). A simple approach: trigger
  `_refresh_agent_file` from the final step of `_apply_loaded_agents` when on the agents tab, which already runs on the
  main thread.

### Step 2 — Coalesce refresh requests correctly

- In `_loading.py:259-273`, extend `_schedule_agents_async_refresh` to track a `_agents_refresh_pending` flag. If a
  refresh is requested while `_agents_loading` is True, set the flag instead of dropping; when the in-flight refresh
  finishes in `_run_agents_async_refresh`, if the flag is set, clear it and schedule one more refresh.
- This gives strict "last request wins" semantics: a stampede of 10 `call_later` refreshes produces at most two full
  loads (the one already running plus one follow-up), and the final UI state reflects whatever was on disk after the
  last trigger.

### Step 3 — Convert post-action refreshes to the async path

- Replace `self.call_later(self._load_agents)` with `self._schedule_agents_async_refresh()` in the following
  fire-and-forget sites (the caller only wants the list to refresh, never inspects the result synchronously):
  - `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py` lines 216, 291, 375, 472, 519, 521, 537, 618.
  - `src/sase/ace/tui/actions/agents/_killing.py:128`.
  - `src/sase/ace/tui/actions/agents/_workflow_hitl.py:175`.
- Audit the remaining sync callers and leave them alone where a same-tick inspection follows: `on_mount` initial load,
  the `_notifications.py` branches that read `self._agents` right after (lines 188/200/212/283/292),
  `_revive.py:187/257`, `_core.py:201/298`, `_prompt_bar.py:374`, and the `_agents_with_children`-missing fallback in
  `_refilter_agents`. These are already on the main thread at points where a brief block is acceptable and often
  necessary.
- As a follow-up polish, several of these "sync then inspect" sites can be rewritten as
  `await self._load_agents_async()` inside existing async handlers, but that is not required to hit the goal.

### Step 4 — Cache immutable artifact reads (mtime-keyed)

Most of the per-refresh cost comes from re-parsing JSON files that never change once written. Add a lightweight
in-process cache keyed by `(path, stat.st_mtime_ns, stat.st_size)` with the parsed payload as the value. The cache lives
in module-level dicts in the loader modules; the ace TUI is a single long-lived process, so a simple dict is fine.

Targets (highest payoff first):

1. `done.json` in `load_done_agents` (`src/sase/ace/tui/models/_loaders/_artifact_loaders.py:322`). Once `outcome` is
   written, this file is immutable. Cache the **derived Agent bundle** (not the raw dict), keyed by artifact dir +
   mtime.
2. Completed `workflow_state.json` in `load_workflow_states` (`_workflow_loaders.py:71`). Only cache when `status` is in
   `{completed, failed}`. Active workflows must keep re-reading.
3. `prompt_step_*.json` in `load_workflow_agent_steps` (`_workflow_loaders.py:322`). These are immutable once the step
   finishes; cache the parsed dict per path + mtime.
4. `agent_meta.json` used by `enrich_agent_from_meta` (`_artifact_loaders.py:33`). Once the agent's status is
   DONE/FAILED, the meta file stops changing. Safest is to always use the mtime cache — it invalidates automatically
   when writes happen.
5. Dismissed bundle files in `load_dismissed_bundles` (`src/sase/ace/dismissed_agents.py:116`). These are write-once
   JSON; cache the parsed Agent by path + mtime.

Cache invariants:

- Keyed on `stat_result` (mtime_ns + size). If the stat call fails (file deleted), the entry is removed and the caller
  falls back to the existing error path.
- Bounded by LRU with a generous cap (e.g. 4,096 entries). Most users will stay well under this.
- Never cache **directory listings** at this stage — only file contents. Directory traversal is already amortized via
  `_get_workflow_timestamp_dirs`.
- `RUNNING` agents whose artifact files mutate during a refresh are automatically handled because mtime changes bust the
  cache entry.

### Step 5 — Parallelize residual disk reads

After Step 4, the first refresh after startup still pays the cost of parsing every file once. Use a bounded
`ThreadPoolExecutor` (`max_workers=min(8, os.cpu_count() or 4)`) to read the per-timestamp-dir JSON bundles concurrently
inside:

- `load_workflow_agent_steps` — parallelize the per-timestamp-dir processing.
- `load_done_agents` — parallelize the per-artifact-dir scanning.
- `load_dismissed_bundles` — parallelize the bundle file reads.

Because the expensive work is tiny JSON blobs, IO-bound threads give a near-linear speedup on machines with many
artifact dirs. The executor can be a module-level singleton reused across refreshes.

### Step 6 — Verify and instrument

- Add a debug-level log around `_load_agents_async` that records wall-clock (`time.perf_counter`) for the disk portion
  plus a count of agents loaded. Gated behind the existing sase logger; never spammy.
- Re-run the profile scenario manually: open `sase ace` with the same fixture state, press `y` repeatedly, launch a
  handful of agents, and confirm no frame-level blocking. Capture a follow-up pyinstrument trace for the PR description.

## Out-of-scope / deferred

- Moving `_load_changespecs` / `find_all_changespecs` to a background thread. The profile shows `_load_changespecs` at
  ~1.4 s cumulative but it is only triggered on startup and ChangeSpec-tab refreshes, which were not the user's reported
  pain point. Worth revisiting if it shows up again after these fixes land.
- Splitting the agent loaders into a streaming / incremental architecture (delta reloads). Caching + parallelization
  should take the steady-state cost low enough that full reloads are cheap; incremental loading adds significant
  complexity for marginal gain today.

## Risks & how we handle them

1. **Stale UI from coalesced refreshes.** Handled by Step 2's pending flag — at most one follow-up refresh is scheduled,
   so the final disk state is always loaded. Worst case is a single extra full reload, which is acceptable.
2. **Cache returning stale data for RUNNING agents.** Handled because the cache key includes mtime/size. Every artifact
   write updates mtime, which invalidates the cached entry. As a belt-and-suspenders check, we can additionally bypass
   the cache for entries whose parsed status is `RUNNING` / `WAITING INPUT` / `PLANNING`, so an anomalous
   mtime-no-change still pulls fresh data.
3. **Sync callers that inspect `self._agents` right after `_load_agents`.** We keep the sync entry point available; only
   the fire-and-forget sites migrate to async. The list of untouched sync callers is explicit in Step 3.
4. **Thread-pool contention with other background work (`_load_axe_status_async`, notification polling).** The executor
   lives in the loader modules and is small; async handlers already run disk work via `asyncio.to_thread`. No shared
   state beyond the cache dicts, which are read-mostly and guarded per-key by mtime compares.
5. **Cache growth over a long session.** Cap each LRU at ~4k entries. Artifact dirs accumulate over weeks; if this
   matters in practice, a periodic prune during `_on_auto_refresh` based on access time is a cheap follow-up.

## Success criteria

- Pressing `y` returns control in a single frame (<50 ms) on the profiled hardware.
- Launching a batch of 5 agents in quick succession never blocks the UI for more than one frame; the final agent list
  reflects all five.
- New pyinstrument trace for the same scenario shows `_load_agents`-cluster total cumulative CPU on the event-loop
  thread reduced by >90 %. Most of that work moves to background threads, and warm refreshes drop to near-zero thanks to
  the mtime cache.
