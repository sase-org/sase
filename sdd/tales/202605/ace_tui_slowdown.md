---
create_time: 2026-05-15 16:55:05
status: done
prompt: sdd/prompts/202605/ace_tui_slowdown.md
---
# Plan: Diagnose and fix `sase ace` TUI slowdown over long sessions

## Problem statement

`sase ace` (the Textual-based TUI) becomes progressively sluggish during a single session, especially after the user
launches one or more agents. Quitting with `q` and re-running `sase ace` restores responsiveness — confirming the
slowdown is _intra-process state growth_ rather than a regression in cold-start cost or a system-level resource issue.
The symptom (instant after restart, slow over time) is the classic signature of one or more in-memory structures growing
unbounded and/or async tasks/watches accumulating.

The goal is to (a) identify which structures are leaking, and (b) bound them — without changing user-visible TUI
behaviour or breaking the refresh / inotify / search pipelines that already coalesce.

## Why the slowdown correlates with launching agents (not just elapsed time)

Several in-memory structures are keyed by _agent identity_ or _artifact paths_. Each launched agent:

- Creates a new artifact directory tree (→ new inotify watches).
- Adds entries to per-agent caches (artifact pages, content-search haystacks).
- Triggers refresh fan-out (timers, async tasks, refilter passes).
- Becomes a permanent member of `_dismissed_agent_objects` once killed/dismissed.

Idle sessions still slowly grow (auto-refresh ticks every `refresh_interval` seconds keep poking the same machinery),
but the per-launch growth is the dominant accelerant the user is reporting.

## Suspected root causes (ranked)

Each entry below has been verified by reading the source. Files cited are under `src/sase/ace/tui/`.

### 1. **Artifact page cache grows unbounded** (HIGH confidence, HIGH impact)

`actions/_state_init.py:238` initializes `self._agent_artifact_page_cache: dict[tuple[Any, ...], list[Any]] = {}`,
populated by `actions/agents/_panel_artifacts.py:_run_agent_artifact_discovery` (line ~315) whenever the user navigates
onto an agent row that has artifacts.

The cache key (`_agent_artifact_cache_key`, line ~352) folds in `agent.identity`, `status`, `diff_path`,
`response_path`, and a tuple of `(mtime_ns, size)` for marker files (`done.json`, `agent_meta.json`, …). This means:

- **Every distinct agent** the user inspects gets a permanent entry.
- **Every status transition** for that agent creates a _new_ key (the old keyed entry is never evicted).
- After hundreds of agent inspections / state transitions, this dict is megabytes large and hot-paths through it on
  every selection change.

There is **no eviction policy**, no `popitem`, no LRU bound.

### 2. **Inotify watches accumulate forever** (HIGH confidence, MEDIUM impact)

`util/fs_watcher.py` adds new watches via `_add_watch_tree` (line 244) when the kernel reports a new directory created
or moved under a watched root (line 287, inside `_collect_relevant_events`). Each launched agent's artifact directory
tree triggers fresh `inotify_add_watch` calls (one per subdirectory: `artifacts/<workflow>/<ts>/...`).

There is **no `inotify_rm_watch` call anywhere** — verified via grep. `_watch_paths_by_wd` only clears on
`watcher.stop()` (at quit). Over an 8-hour session with dozens of agents launched, this dict accumulates hundreds of
watches and Python entries; each kernel event then triggers a dispatch path that mutates `_pending_paths` (a set whose
membership work is small but non-zero, and which fans out to multiple full-surface refreshes via `_on_artifact_change`).

The user-visible effect: each filesystem change → larger watcher state to walk → more `Path` objects allocated per flush
→ more downstream `_schedule_*_async_refresh` calls.

### 3. **`_dismissed_agent_objects` is an append-only list of full `Agent` models** (HIGH confidence, MEDIUM impact)

`actions/agents/_dismiss_memory.py:99-102` appends every dismissed/killed agent's _full_ `Agent` object to
`_dismissed_agent_objects`. Each `Agent` carries identity, status, attempt history (which can include reply paths, plan
times, questions times, etc.), and is read on every refresh pass at `_loading_apply.py:87`
(`for agent in self._dismissed_agent_objects: …`).

The list is deduplicated by identity but **never trimmed**: a user who dismisses 200 agents over a long session pays an
`O(N)` scan on every agent refresh, _and_ every refilter pass.

### 4. **Content-search refresh tasks not cancelled** (MEDIUM confidence, MEDIUM impact, but only when `/`-search is active)

`actions/agents/_loading_filter.py:_schedule_agent_content_search_index_refresh` (line 77) creates a new asyncio task on
every refresh via `loop.create_task(...)` and overwrites `self._agent_content_search_refresh_task` _without cancelling
the previous one_ (line 112).

The generation guard (line 130) ensures only the latest result is applied, but **all in-flight tasks still run to
completion** — each one performs `worker_cache.build_index(agents)` over the full agent list off-thread. With a
content-search filter active during a launch storm, several builds stack up and contend for the GIL on merge.

Mitigating factor: only triggers when a `/`-search query is active.

### 5. **Auto-refresh poll always reads the notification store from disk** (LOW-MEDIUM confidence)

`_event_refresh.py:_on_auto_refresh` unconditionally calls `await self._poll_agent_completions()` every
`refresh_interval`. That reads the entire notification snapshot from disk on a worker thread, even when nothing changed
and even when the inotify watcher is the canonical signal. As the notification store grows over a session, this disk
read gets slower.

The dirty-flag guard exists for agent/changespec/axe surfaces (line 144) but **not** for notification polling.

## Diagnostic plan (do this first, before any fix)

Adding instrumentation is cheap and pays for itself in confirming which suspect is dominant in _this_ user's workflow.
Two diagnostic surfaces:

### D1. Periodic structural snapshot logging

Add a small debug helper (gated behind an env var like `SASE_ACE_DEBUG_LEAKS=1`) that periodically logs the sizes of the
suspect structures:

- `len(self._agent_artifact_page_cache)` and total bytes (approximate via `sys.getsizeof`).
- `len(watcher._watch_paths_by_wd)` and current kernel `/proc/self/fd` count (cheap proxy for kernel handle pressure).
- `len(self._dismissed_agent_objects)`.
- Number of pending asyncio tasks (`len([t for t in asyncio.all_tasks() if not t.done()])`).
- `len(self._agents_with_children)` (sanity check).

Fire from the existing auto-refresh timer (after the main work) so we don't add a new timer. Log via the existing
`logging` machinery to the file `~/.sase/logs/ace.log` (or wherever ACE already logs).

### D2. One-shot snapshot keybind

Add a developer keymap (e.g. `Ctrl+Shift+D`, behind the same env var) that dumps the same snapshot synchronously and
shows the user a textual notification with the headline numbers. This lets the user reproduce the symptom and grab a
single snapshot when things are slow without having to wait for the next periodic log line.

### D3. Validation criterion

The user reproduces the slowdown, then captures `sase ace.log` covering ~5 minutes of usage at "fresh start" and ~5
minutes at "slow". Compare the snapshot numbers. The suspect whose count grows monotonically and whose growth tracks the
user's perceived slowdown is the dominant root cause. We may find multiple compounding causes — that's fine, fix each
one.

## Fix plan

The fixes are small and orthogonal — they can be applied independently as the diagnostic numbers come back. I'd land
them in this order so each lands a clear win:

### F1. Bound `_agent_artifact_page_cache` (addresses suspect #1)

Replace `dict` with an `OrderedDict` and reuse the existing `_bounded_lru_put` / `_bounded_lru_get` helpers from
`widgets/_agent_list_render_cache.py` (or copy the pattern). Cap at ~256 entries (covers normal browsing well beyond the
visible list). Touchpoints:

- `actions/_state_init.py:238` — change type and initial construction.
- `actions/agents/_panel_artifacts.py` — every `cache[row_key] = ...` and `cache.get(row_key)` call site uses the
  bounded helpers.

No public-API change. Existing tests should pass unchanged.

### F2. Track-and-remove inotify watches (addresses suspect #2)

In `util/fs_watcher.py`:

- Add `_remove_watch(libc, fd, wd)` that calls `libc.inotify_rm_watch(fd, wd)` and pops from `_watch_paths_by_wd`.
- When `_collect_relevant_events` sees `IN_DELETE_SELF` / `IN_MOVE_SELF` / `IN_IGNORED` on a watched directory, remove
  the corresponding watch.
- Optional but cheap: cap the total watch count at a reasonable ceiling (e.g. 4096) and log a one-shot warning if
  exceeded — defends against pathological cases.

This requires checking the mask bits already handled and extending the relevant-event filter to admit the deletion
masks. `_mask` may need to include `IN_DELETE_SELF | IN_MOVE_SELF`.

### F3. Trim `_dismissed_agent_objects` (addresses suspect #3)

This list exists to keep dismissed agents visible until the user has navigated past them and to feed the refresh
pipeline. After an agent is fully _applied as dismissed_ (i.e. it appears in the current `_agents` list as dismissed and
any pending UI work has flushed), it can drop out of the in-memory list — the on-disk `dismissed_agents` registry is the
source of truth for cross-session persistence.

Concretely: in `actions/agents/_loading_apply.py` (around line 327 where the list is rewritten from
`prep.dismissed_agent_objects`), filter the list to only entries still present in the _current_ agents source (i.e. ones
still relevant for hide/dismiss decisions in this load). Anything no longer in the source tree can be dropped because
the on-disk dismissed-id registry alone is enough to keep them hidden on the next load.

Add a hard cap as a safety net (e.g. keep at most 500 most-recent dismissed objects, by dismissal time) for edge-cases
where the agent tree is huge.

### F4. Cancel the prior content-search refresh task (addresses suspect #4)

In `actions/agents/_loading_filter.py:_schedule_agent_content_search_index_refresh`, before assigning the new task to
`self._agent_content_search_refresh_task`, `.cancel()` the previous task if it exists and is not done. The generation
guard already protects correctness; cancellation removes the wasted CPU.

### F5. Gate notification polling on the same dirty-flag mechanism (addresses suspect #5)

In `_event_refresh.py:_on_auto_refresh`, only call `_poll_agent_completions` when:

- The inotify watcher is inactive (current behaviour), OR
- A "notifications dirty" flag is set, OR
- The sanity-refresh window has elapsed.

Add a `_dirty_notifications` flag wired alongside `_dirty_agents` in `_dirty_surfaces_for_paths`, set when watched paths
under `~/.sase/notifications/` change. Most refresh ticks then become a no-op for notification polling, which is the
right outcome.

### F6. Cleanup at quit (defensive)

Ensure `_cancel_pending_artifact_discovery` and a new `_cancel_pending_content_search_refresh` are both invoked from the
lifecycle teardown path so we don't leak tasks past app exit. Already partially handled.

## Non-goals / explicit out-of-scope

- **No architectural rewrite** of the refresh pipeline. The existing debounce / dirty-flag / loading-gate machinery is
  sound; we are bounding things it already produces.
- **No change to TUI keybindings or visible behaviour**. The only user-visible artifact is the optional
  `SASE_ACE_DEBUG_LEAKS=1` instrumentation, which is off by default.
- **No removal of caches** — they exist for good reason (avoid redoing disk reads on every keypress). Each fix bounds
  growth, not eliminates the cache.
- **No fix for the Rust-core boundary** (per `memory/short/rust_core_backend_boundary.md`); all of this is
  presentation-layer Python state.

## Validation

For each fix that lands:

1. Run `just check` (lint + mypy + tests).
2. Manual smoke: open `sase ace`, launch a multi-agent xprompt that spawns ~10 agents, dismiss them, repeat 3-5 cycles.
   With `SASE_ACE_DEBUG_LEAKS=1` confirm the relevant counter no longer grows monotonically across cycles.
3. Re-verify the originally-reported symptom: a long session (target: 60+ minutes with ~30 agent launches) stays
   responsive, with `j`/`k` navigation latency unchanged from a fresh start.

A regression test for F1/F3/F4 can live as a unit test that drives the cache/list through N synthetic agents and asserts
a bounded size.

## Risks

- **F2 (inotify removal)** has the highest risk of breaking the refresh signal — a wrongly-removed watch causes a silent
  stale TUI until the sanity-refresh window elapses. The fix should only remove watches on explicit deletion/move events
  the kernel reports, not on speculative cleanup.
- **F3 (dismissed-agent trimming)** could surface dismissed-then-revealed agents incorrectly if the disk registry and
  in-memory list disagree. Mitigated by keeping the on-disk registry as the source of truth and only trimming agents the
  loader no longer references.
- **F5 (notification gating)** could miss a notification in the rare case where neither inotify nor the sanity tick
  fires before the user looks. The 60-second sanity floor caps that.

All other fixes are conservative bounds and have negligible behavioural risk.
