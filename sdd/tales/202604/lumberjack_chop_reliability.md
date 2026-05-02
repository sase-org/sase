---
create_time: 2026-04-08 18:41:40
status: done
prompt: sdd/prompts/202604/lumberjack_chop_reliability.md
---

# Plan: Lumberjack Chop Execution Reliability

## Problem

The user reports that when the cumulative runtime of all chop scripts exceeds the lumberjack interval, chops at the end
of the list get skipped.

### Analysis

After reading the code, `_run_tick()` (lumberjack.py:107-194) iterates through ALL chops in a sequential for loop with
no time-based early exit. The `schedule` library also does not interrupt running jobs. So chops are **not being skipped
within a single tick** today.

However, there is a real robustness problem: `run_chop_script()` (chop_script_runner.py:53-81) calls `subprocess.run()`
with **no timeout** by default, meaning a hanging chop script blocks all subsequent chops **indefinitely**. This is
likely the actual failure mode the user is observing -- a slow or stuck chop prevents later chops from running.

Additionally, when cumulative runtime exceeds the interval, the `schedule` library fires the next tick immediately after
the current one finishes, causing ticks to run back-to-back with no gaps.

## Design

### Phase 1: Per-chop timeout with graceful degradation

**Config changes** (`config.py`):

- Add a `timeout` field to `ChopConfig` (parsed as a duration string like `run_every`, e.g. `"30s"`, `"2m"`).
- Add a `chop_timeout` field to `LumberjackConfig` as a default timeout for all chops in that lumberjack. Individual
  chop `timeout` values override this default.

**Execution changes** (`lumberjack.py`):

- In `_run_tick()`, pass the resolved timeout to `run_chop_script()`.
- Catch `subprocess.TimeoutExpired` alongside the existing `Exception` handler -- record it as an error via
  `_handle_error()` and continue to the next chop.

**Default config** (`default_config.yml`):

- No per-chop timeouts by default (keep current behavior unless user configures them).
- But DO set a `chop_timeout` on the `hooks` lumberjack (e.g. `"30s"`) since it runs every 5s and has 7 chops.

### Phase 2: Tick overrun warning

After the chop loop completes, check if `time.monotonic() - _tick_start` exceeds `self.config.interval`. If so, log a
warning with the tick duration and interval. This is observability-only -- the system still runs all chops.

### Phase 3: Tests

- Test that `subprocess.TimeoutExpired` is caught and recorded as an error without stopping subsequent chops.
- Test that the tick overrun warning is logged when cumulative duration exceeds the interval.
- Test that per-chop `timeout` overrides the lumberjack-level `chop_timeout`.
