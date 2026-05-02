---
create_time: 2026-04-28 14:14:48
status: done
prompt: sdd/prompts/202604/instant_planning_status_refresh.md
---

# Instant `PLANNING` status refresh after `sase plan`

## Problem

When an agent calls `sase plan <plan_file>` from inside its workflow, the `sase ace` TUI's "Agents" tab takes **up to 60
seconds** (`FULL_SANITY_REFRESH_SECONDS`) to flip the agent's status to `PLANNING`. The user wants the status to switch
immediately on plan submission.

The user describes this as a cache-invalidation issue, but the root cause is more interesting: the relevant filesystem
events never reach the ACE TUI at all, so the on-disk `load_json_cached` LRU is never asked to reload — it doesn't
matter that the cache is mtime-keyed.

## Background — where the status comes from

There are two paths that assign `PLANNING` to an agent in the ACE TUI:

1. **`enrich_agent_from_meta()`** (`src/sase/ace/tui/models/_loaders/_artifact_loaders.py:184-196`) — fires when
   `agent_meta.json` has `plan: true` and `plan_approved` is falsy. Used for solo `%plan` agents.

2. **`_apply_status_overrides()`** (`src/sase/ace/tui/models/agent_loader.py:337-346`) — fires when a `.plan` workflow
   root has `status == "DONE"` and no follow-up child. Used for the more common workflow path; the real-world
   `agent_meta.json` from `plans/202604/fix_planning_status_after_feedback.md:60-65` does **not** carry `plan: true`, so
   this is the path most users hit.

Both paths require the loader to re-read `agent_meta.json` and `workflow_state.json` from disk. `load_json_cached`
(`src/sase/ace/tui/models/_loaders/_json_cache.py:23-60`) is keyed on `(path, mtime_ns, size)`, so any actual write
naturally invalidates the entry. The cache itself is not the bug.

## Root cause — the watcher misses the event

The `sase plan` handler (`src/sase/main/plan_command_handler.py:60-76`) writes its marker to:

```
$SASE_ARTIFACTS_DIR/.sase_plan_pending
   = ~/.sase/projects/<project>/artifacts/<workflow>/<YYYYMMDDHHMMSS>/.sase_plan_pending
```

The runner side (`src/sase/axe/run_agent_exec_plan.py:174-178`) follow-up writes to:

```
~/.sase/projects/<project>/artifacts/<workflow>/<YYYYMMDDHHMMSS>/agent_meta.json
```

Both writes land **three directory levels below** the deepest watched path. The ACE inotify setup
(`src/sase/ace/tui/actions/startup.py:283-295`) only adds watches for:

- `~/.sase/projects/` direct children (each `<project_dir>`)
- `~/.sase/projects/<project>/artifacts/`

Inotify is **not recursive** (`fs_watcher.py:115-160` adds one `inotify_add_watch` per path, with no descent), so file
events inside `artifacts/<workflow>/<timestamp>/` never wake the UI thread. The 60-second `FULL_SANITY_REFRESH_SECONDS`
in `event_handlers.py:25` is the only mechanism that eventually catches up, which matches the lag the user observes.

## Goal

When `sase plan` is invoked, the agent's row on the Agents tab transitions to `PLANNING` within the same 50 ms coalesce
window the watcher already uses for top-level events — i.e. effectively instant.

## Approach

Two concrete options. I recommend **Option A** for surgical scope; Option B is the broader fix that would also help
every other deep-tree write (done.json appearance, retry handoffs, etc.).

### Option A (recommended): Bump a sentinel at a watched level from `sase plan`

Have `plan_command_handler.handle_plan_command()` perform one extra write at a path the inotify watcher already sees.
Concretely, write/refresh a small marker at:

```
~/.sase/projects/<project>/artifacts/.refresh_pulse
```

This file lives directly in the watched `artifacts/` directory, so `IN_CREATE`/`IN_MODIFY` fires, the 50 ms coalesce
expires, `_on_artifact_change()` flips `_dirty_agents = True`, and `_schedule_agents_async_refresh()` reads the deep
`agent_meta.json` whose mtime did change (so the JSON LRU misses correctly).

The project root for the marker is derivable inside `sase plan` from `SASE_ARTIFACTS_DIR` —
`Path(artifacts_dir).parents[1]` is the `<project>/artifacts/` dir.

Two specific design choices:

1. The pulse file is **content-free** (or contains the timestamp for debugging). It is not consumed by the loader; its
   only job is to fire inotify. This means we don't need to coordinate read/delete with the runner, and stale residue is
   harmless.
2. We write before the SIGTERM in `plan_command_handler.py` so the watcher fires regardless of whether the subsequent
   runner-side `update_meta_field` writes complete promptly.

This is ~15 lines of code, no schema or contract changes.

### Option B: Make `ArtifactWatcher` recursive

Walk the artifacts tree at startup and `inotify_add_watch` every subdirectory; on `IN_CREATE` for a directory, add a
watch for the new dir; on `IN_DELETE_SELF` / `IN_MOVED_FROM` clean up. This fixes the underlying gap (deep writes are
silently invisible today) but:

- Touches `fs_watcher.py` substantially (state for wd→path mapping, race handling, watch-limit tuning — Linux defaults
  `max_user_watches` to 8192, and per-agent timestamp dirs accumulate).
- Has knock-on test surface (the existing watcher tests assume a flat path list).
- Is out of scope for the stated request, which is specifically the plan-submission lag.

Worth filing as a follow-up; not part of this change.

## Out of scope

- Reworking `_apply_status_overrides()` semantics — the existing logic is correct once the loader actually re-reads
  `agent_meta.json` / `workflow_state.json`.
- Eliminating the LRU in `_json_cache.py` — it's mtime-correct; the bug is upstream of it.
- Cross-process IPC (POSIX signals, sockets) — heavier than needed when a one-byte file write wakes the watcher already
  in place.

## Files to change

### 1. `src/sase/main/plan_command_handler.py`

After the existing `.sase_plan_pending` write at `plan_command_handler.py:67-70` and before `kill_agent_runner_group()`
at line 76, write a refresh-pulse file in the parent `artifacts/` dir so the ACE inotify watcher (which only sees direct
children of `artifacts/`) wakes immediately.

Sketch:

```python
artifacts_root = Path(artifacts_dir).parents[1]  # …/<project>/artifacts/
pulse_path = artifacts_root / ".ace_refresh_pulse"
try:
    pulse_path.write_text(str(time.time()), encoding="utf-8")
except OSError:
    pass  # Pulse failure must not break plan submission
```

The write is best-effort: if it fails (read-only fs, races), the SIGTERM + 60 s sanity refresh still delivers correct
state — we just lose the fast path.

### 2. `src/sase/ace/tui/actions/startup.py`

No change needed if `artifacts_dir` is already in the watch set (it is, line 290-292). The pulse file lands as a direct
child, so the existing watch fires.

Optionally: filter out `.ace_refresh_pulse` from any tab-display logic so the file never shows in agent listings. The
current loaders only enumerate workflow subdirs / `.gp` files, so this should be a no-op — verify during implementation.

### 3. Tests

- `tests/test_plan_command_handler.py` (new or extend existing): assert the pulse file is written in the `artifacts/`
  dir when `sase plan` runs, and that the file's mtime advances on repeat invocations.
- `tests/test_fs_watcher.py` (existing — confirm coverage): no changes required; the existing test that a direct-child
  write triggers `on_change` already exercises the integration.
- Add a small integration test (or smoke check via the existing ACE TUI test fixture, if any) that verifies a write to
  `<artifacts>/.ace_refresh_pulse` triggers `_on_artifact_change()` within the coalesce window.

### 4. Documentation

Add a short note to `memory/short/gotchas.md` (or create one if appropriate) documenting that `ArtifactWatcher` is
non-recursive, and that any code path needing fast UI refresh from a deep write must also pulse a file at a watched
level. This prevents future "why is my new feature laggy?" debugging.

## Verification plan

1. `just install` then `just check` to clear lint/type/tests.
2. Manual: open `sase ace`, launch a workflow with `%plan`, watch the Agents tab. Have the agent invoke
   `sase plan some_plan.md`. Confirm the row flips to `PLANNING` within ~100 ms (50 ms coalesce + a UI tick), not after
   the next sanity-refresh tick.
3. Edge case: simulate a missing `artifacts/` directory (e.g. fresh project with no agents yet). The pulse write should
   silently no-op without breaking the plan handler.
4. Regression: confirm existing inotify behavior for `.gp` writes (the project-dir watch) is unchanged.

## Risks

- **Disk churn**: the pulse file is rewritten every time `sase plan` runs, which is rare (one per plan submission).
  Negligible.
- **Stale pulse file**: harmless — it's never read.
- **Permission issues**: if the artifacts dir is read-only for some reason, the pulse write fails; we swallow the error
  and fall back to the existing 60 s path.
- **Watcher unavailable** (non-Linux, no inotify): the pulse is moot; the existing 60 s sanity refresh is the only path.
  No regression vs today.
