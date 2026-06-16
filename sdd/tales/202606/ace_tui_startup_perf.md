---
create_time: 2026-06-15 21:02:19
status: done
prompt: sdd/prompts/202606/ace_tui_startup_perf.md
---
# Plan: Make `sase ace` Startup Much Faster

## Problem Summary

`sase ace` startup is slow because the first Agents-tab load performs live workspace diff classification for many agent
rows before marking the agents surface loaded. In this workspace, direct timings show:

- `collect_axe_status_data`: ~0.24s
- `find_all_changespecs_cached(include_states="all")`: ~0.01s
- `load_dismissed_agents`: ~0.07s
- `load_agents_from_disk_with_state(full_history=False)`: ~18-20.5s
- Same loader with live file-change hint classification disabled: ~1.36s
- Same loader with the whole diff-badge pass disabled: ~1.39s

cProfile confirms the dominant path:

- `load_agents_from_disk_with_state`
- `load_tiered_agents`
- `_normalize_loaded_agents`
- `apply_status_overrides`
- `_classify_diff_badges`
- `_classify_live_file_change_hint`
- `live_agent_file_change_hint`
- `get_agent_diff`
- repeated `get_vcs_provider` / VCS detection / entry point discovery / `diff_with_untracked`

The loader is using the Tier 1 artifact index (`artifact_source=artifact_index`), so this is not an index-missing or
full-history fallback issue. The regression is that a presentation badge now causes hundreds of live VCS probes during
startup.

## Goals

1. Make first interactive startup dramatically faster, targeting the current loader path dropping from ~18s to ~1-2s.
2. Keep persisted diff badges correct for completed agents.
3. Preserve live workspace edit hints without blocking startup or j/k responsiveness.
4. Add tests that prevent live VCS diff work from re-entering the startup loader path.
5. Use the repo's established TUI performance rule: no synchronous disk/subprocess work on the Textual event loop, and
   no expensive noncritical work in first-load gates.

## Non-Goals

- Do not change artifact index semantics or rebuild strategy; the index is already being used.
- Do not make broad Rust/core changes unless the Python-side fix proves insufficient.
- Do not remove the Deltas/detail-pane live diff behavior.

## Implementation Approach

### 1. Split Persisted Diff Badges From Live Workspace Hints

Refactor `src/sase/ace/tui/models/_agent_status_overrides.py` so the normal status override pass keeps cheap persisted
diff classification but does not run live workspace VCS probes:

- Keep `diff_has_real_edits(agent.diff_path)` for agents with a persisted `diff_path`.
- Leave `agent.live_file_change_hint` as `None` during the main loader pass.
- Rename/split helpers so it is clear which path is cheap and which path can invoke live VCS work.

This should preserve completed-agent pencil badge correctness while removing the startup-critical `get_agent_diff()`
calls.

### 2. Reintroduce Live Hints As Deferred, Coalesced Background Work

Add a post-load live-hint refresh path owned by the Agents TUI code, not the raw loader:

- Schedule it only after the first agents load has applied and the startup stopwatch can end.
- Run the expensive VCS/diff work off-thread.
- Coalesce requests so auto-refresh or artifact watcher bursts do not launch overlapping live-hint scans.
- Scope the first version conservatively:
  - active / non-terminal rows only,
  - rows without persisted `diff_path`,
  - agents with resolvable workspace metadata.
- Apply results on the UI thread by identity, then patch visible rows instead of rebuilding the whole agent list.

If the row patching integration is too invasive for the first pass, use the existing selective refresh helpers already
used by agent list patching and keep the update small.

### 3. Reduce Duplicate VCS Provider Discovery

Add or reuse caching around VCS provider resolution in the live-hint path:

- Avoid repeated `importlib.metadata.entry_points(group="sase_vcs")` scans for every agent.
- Avoid duplicate provider detection for the same workspace within one live-hint batch.
- Prefer a small module-level cache with simple invalidation by environment/config inputs, or a batch-local cache if a
  global cache risks stale provider selection.

This is secondary to deferring live hints, but it will keep the deferred worker from consuming unnecessary CPU and
subprocess time after startup.

### 4. Tests

Add/update focused tests:

- Loader/status override tests:
  - `_apply_status_overrides` must not call `get_vcs_provider` / `get_agent_diff` during the default loader pass for a
    running agent without `diff_path`.
  - persisted `diff_path` classification still sets `diff_has_real_edits`.
- Live-hint tests:
  - direct `live_agent_file_change_hint()` behavior remains unchanged.
  - new deferred/batch live-hint helper computes true/false/none correctly and applies by agent identity.
- Startup regression test:
  - first-load agents path schedules deferred hint work rather than awaiting it before `_agents_first_load_done`.

### 5. Verification

Before source changes, current baseline is:

- normal loader: ~18s
- loader with live hints disabled: ~1.36s

After source changes:

- Re-run the same direct loader timing and confirm normal loader is near the disabled-live-hint baseline.
- Run a real TUI startup with `SASE_TUI_TRACE=1 .venv/bin/sase ace --tmux -x` and verify:
  - `agents.load_from_disk` no longer contains live diff work,
  - first-load startup stopwatch is not gated on live hint classification,
  - deferred live-hint work, if traced, happens after first load.
- Run targeted tests for changed TUI/model/diff code.
- Run `just check` before final response because source files will have changed.

## Expected Result

The Agents first-load path should stop doing hundreds of VCS provider detections and live diffs. Startup should fall
from the reported ~17s range to roughly the current no-live-hints baseline (~1-2s for the agents loader), with any live
workspace pencil badges filled in asynchronously after the TUI is already usable.
