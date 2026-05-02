---
create_time: 2026-04-08 18:54:24
status: wip
prompt: sdd/prompts/202604/concurrent_chops.md
---

# Plan: Run Lumberjack Chops Concurrently

## Problem

In `_run_tick()` (`src/sase/axe/lumberjack.py:108-209`), chops execute **sequentially** — each `run_chop_script()` call
blocks on `subprocess.run()` until the chop finishes or times out. For the hooks lumberjack (5s interval, 7 chops, 30s
chop_timeout), the worst-case tick duration is 210s. Chops near the end of the list run at a degraded frequency, and in
practice this caused a chop to appear "skipped" — requiring it to be moved to its own lumberjack as a workaround.

**Root cause:** Sequential execution means tick duration = `sum(all_chop_times)`, so any slow chop delays every chop
after it.

## Solution

Run all chop scripts concurrently within each tick using `concurrent.futures.ThreadPoolExecutor`. Since chops are
already external subprocesses (via `subprocess.run()`), threading is safe — threads are just waiting on I/O. This
changes tick duration from `sum(all_chop_times)` to `max(all_chop_times)`.

## Design

### Phase 1: Extract per-chop execution into a method

Refactor the body of the chop for-loop (lines 142-192) into a `_run_single_chop(chop, context_file, now)` method that:

- Dispatches to `_run_agent_chop()` for agent chops
- Discovers and runs script chops with timeout
- Catches `TimeoutExpired` and generic `Exception`
- Returns a result dataclass indicating: whether the chop ran, whether it succeeded, and whether `run_every` timestamp
  should be updated

### Phase 2: Concurrent execution with ThreadPoolExecutor

In `_run_tick()`, replace the sequential for-loop with:

1. Filter chops eligible to run (apply `run_every` checks upfront)
2. Submit all eligible chops to a `ThreadPoolExecutor`
3. Collect results after all futures complete
4. Aggregate metrics and timestamps from results

**Thread safety:** Rather than adding locks to `_metrics` and `_chop_timestamps`, each chop execution returns a result
dataclass. The main thread aggregates results after all futures complete. This keeps the concurrent part pure and
side-effect-free (except for the subprocess itself and logging).

**Result dataclass:**

```python
@dataclass
class _ChopResult:
    chop_name: str
    executed: bool       # True if the chop actually ran (not skipped)
    success: bool
    update_timestamp: bool  # Whether to update run_every timestamp
    log_lines: list[str]    # Captured log output
    error: Exception | None = None
```

**Logging:** Buffer log lines in each thread and flush them sequentially after all chops complete. This keeps output
readable and avoids interleaved log lines.

### Phase 3: Update tests

- Existing tests should continue to pass since the observable behavior (all chops run, errors recorded, timeouts caught)
  is preserved
- Add a test verifying that chops run concurrently (e.g., two chops each sleeping 1s complete in ~1s total, not ~2s)
- Add a test verifying that one chop's failure doesn't prevent others from running under concurrency

## Files to modify

| File                           | Change                                                                                                        |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| `src/sase/axe/lumberjack.py`   | Add `_ChopResult` dataclass, extract `_run_single_chop()`, refactor `_run_tick()` to use `ThreadPoolExecutor` |
| `tests/test_axe_lumberjack.py` | Add concurrency test, verify existing tests still pass                                                        |

## Risks and mitigations

- **Log interleaving:** Mitigated by buffering log lines per-chop and flushing sequentially after completion
- **Thread safety of `_run_agent_chop()`:** The `_agent_pids` dict is read/written from the main thread only (agent
  chops return results, main thread updates pids). Need to verify `launch_agent_from_cwd` is safe to call from a thread
  — since it just spawns a subprocess, it should be fine.
- **`os.environ` mutation in agent chops:** The current code sets/unsets `SASE_AGENT_AUTO_DISMISS` globally, which is
  not thread-safe. Fix: pass env vars to the subprocess directly instead of mutating `os.environ`.
