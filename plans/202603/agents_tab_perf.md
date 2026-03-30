---
create_time: 2026-03-30 19:59:53
status: done
---

# Plan: Agents Tab Performance Optimization

Pure refactoring to make the Agents tab fast without changing any behavior.

## Problem

`_load_agents()` runs the full `load_all_agents()` pipeline from scratch on every call — every auto-refresh tick, tab
switch, and user action. This pipeline does heavy filesystem I/O: parsing .gp files (including large archives), scanning
artifact directories, reading dozens of JSON files (done.json, workflow*state.json, agent_meta.json, waiting.json,
retry_state.json, prompt_step*\*.json), checking PID liveness, and running 5 dedup passes. With 20+ agents across
multiple projects, this takes 200-500ms+ and blocks the TUI event loop.

## Optimizations

### Phase 1: Filesystem fingerprint cache for `load_all_agents()`

Most auto-refreshes find nothing has changed. Detect this cheaply with stat() calls (~1us each) instead of
reading/parsing files (~1ms each).

**Design:**

- Add an `_AgentCache` class in `agent_loader.py` with a module-level singleton
- During a full load, record every filesystem path accessed and its mtime_ns into a `_FileTracker` context
- Before subsequent loads, re-stat all recorded paths to detect changes
- Also scan parent directories for new entries (new agents starting)
- If nothing changed, return deep-copied cached results (agents are mutable dataclasses)
- Expose a `force` parameter on `load_all_agents()` to bypass the cache

**Cache invalidation triggers:**

- Any recorded file's mtime_ns changed
- Any recorded file was deleted
- Any scanned directory has new entries (detected by checking `set(dir.iterdir())` vs cached entries)

**Files:** `src/sase/ace/tui/models/agent_loader.py`

### Phase 2: Skip archive .gp files in agent loading

`find_all_changespecs()` parses ALL .gp files including `*-archive.gp`. Archives contain completed/submitted CLs and can
be very large. But agent loading only uses changespecs to build `bug_by_cl_name` and `cl_by_cl_name` lookups — active
agents reference active CLs, not archived ones.

**Design:**

- In `_load_agents_from_all_sources()`, replace `find_all_changespecs()` with direct `parse_project_file()` calls on
  just the main .gp files (already available from `project_files = get_all_project_files()`)
- This eliminates parsing archive files entirely

**Files:** `src/sase/ace/tui/models/agent_loader.py`

### Phase 3: Skip widget rebuild when data unchanged

`AgentList.update_list()` always clears and rebuilds the entire OptionList with fresh Rich Text objects. On cache hits
(Phase 1), the data hasn't changed, so this work is wasted.

**Design:**

- After loading and filtering in `_load_agents()`, compute a display fingerprint: tuple of
  `(identity, status, retry_count, hidden, agent_name)` per agent
- Compare with the previous fingerprint stored on the mixin
- If unchanged, call `_refresh_agents_display(list_changed=False)` instead of `list_changed=True`
- This skips the expensive OptionList clear+rebuild and only updates highlight/detail

**Files:** `src/sase/ace/tui/actions/agents/_loading.py`

### Phase 4: Run cache-miss loads in a worker thread

Even with caching, cache misses still block the event loop. Use Textual's `run_worker()` to keep the TUI responsive.

**Design:**

- Extract the pure data-loading work (load_all_agents + retry state enrichment) into a standalone function
  `_load_agents_data()` that returns the raw agent list
- In `_load_agents()`, run `_load_agents_data()` via `run_worker(thread=True)`
- On worker completion, apply results on the main thread (filtering, display update)
- Guard against stale worker results (cancel previous worker if a new load starts)
- For user-initiated loads (dismiss, fold, search), the local-state filtering can run immediately on cached data without
  waiting for the worker

**Files:** `src/sase/ace/tui/actions/agents/_loading.py`
