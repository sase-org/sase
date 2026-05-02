---
create_time: 2026-03-27 17:56:33
status: done
---

# Fix `is_process_alive()` to detect zombie and recycled PIDs

## Problem

The `/list` command shows 4 agents, but only 2 are actually running:

| Agent     | PID     | Status                       | Issue                                         |
| --------- | ------- | ---------------------------- | --------------------------------------------- |
| **b**     | 2475227 | Running (Ss)                 | None                                          |
| **ad**    | 2453295 | Zombie (Zs)                  | `is_process_alive()` doesn't detect zombies   |
| **y**     | 2341354 | Running (Ssl)                | None                                          |
| (unnamed) | 2446474 | PID recycled (Chrome thread) | `is_process_alive()` doesn't detect PID reuse |

## Root Cause

`is_process_alive()` in `src/sase/agent/names.py:498-529` uses only `os.kill(pid, 0)`:

```python
def is_process_alive(meta: dict[str, object], artifact_dir: Path) -> bool:
    ...
    try:
        os.kill(pid, 0)
        return True          # <-- succeeds for zombies AND recycled PIDs
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
```

**Bug 1 — Zombie**: PID 2453295 is a zombie (parent lumberjack PID 1938267 hasn't reaped it). `os.kill(pid, 0)` succeeds
for zombies.

**Bug 2 — PID recycling**: PID 2446474 originally belonged to the unnamed agent (stopped March 20). The PID was recycled
and now belongs to a Chrome renderer thread. `os.kill(pid, 0)` succeeds because a process with that PID exists — it's
just not the agent.

A better `is_process_running()` already exists in `src/sase/ace/hooks/processes.py:36-67` with zombie detection via
`/proc/<pid>/status`, but `is_process_alive()` doesn't use it. Neither function detects PID recycling.

## Plan

### Phase 1: Fix `is_process_alive()` in `src/sase/agent/names.py`

**File**: `src/sase/agent/names.py`

Replace the current `os.kill`-only check with:

1. **Early `stopped_at` check**: If `meta.get("stopped_at")` is set, the agent was explicitly stopped — return `False`
   immediately. This catches both issues without any process inspection.

2. **Delegate to `is_process_running()` from `processes.py`**: This adds zombie detection via `/proc/<pid>/status` State
   check. Catches bug 1.

3. **PID recycling detection**: After confirming the PID is alive and not a zombie, read `/proc/<pid>/cmdline` and
   verify it contains `python` or `sase`. If the cmdline doesn't match (e.g., it's a Chrome thread), the PID was
   recycled — return `False`. Catches bug 2.

### Phase 2: Consolidate duplicate logic

**Files**: `src/sase/agent/names.py`, `src/sase/ace/hooks/processes.py`

- Make `is_process_alive()` import and call `is_process_running()` from `processes.py` instead of reimplementing the
  `os.kill` + zombie check.
- This eliminates the duplicate `os.kill(pid, 0)` pattern and ensures both code paths benefit from future improvements.

### Phase 3: Run `just check`

Run `just install && just check` to verify lint, type-checking, and tests all pass.
