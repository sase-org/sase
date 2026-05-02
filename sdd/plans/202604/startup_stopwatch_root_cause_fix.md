---
create_time: 2026-04-24 15:31:36
status: done
prompt: sdd/prompts/202604/startup_stopwatch_root_cause_fix.md
---
# Plan: Diagnose and Fix Startup Stopwatch Freezing at 0.2s

## Problem Statement

The startup stopwatch in `sase ace` still appears frozen at `0.2s` for the entire startup period, then disappears when
startup completes. Prior work moved several startup reads to `asyncio.to_thread`, but the user-visible behavior is still
broken.

## Diagnosis Summary

I re-ran startup with runtime instrumentation (no source edits), wrapping key methods and logging timestamps.

### Observed Timeline (Measured)

- `AceApp.on_mount` starts around `0.205s` and ends around `0.370s` (fast).
- After `on_mount`, startup schedules two callbacks:
  1. `_run_agents_async_refresh`
  2. `_run_axe_startup_init`
- `_run_agents_async_refresh` starts first and takes ~3.8s total (primarily waiting on `_load_agents_async`).
- `_run_axe_startup_init` does **not start until after** `_run_agents_async_refresh` completes.
- `end_startup_stopwatch()` is called from `_apply_axe_status_data`, so it is delayed by the agent refresh ordering.

### Key Finding

Startup callbacks are effectively serialized in current scheduling order. The stopwatch end signal is tied to AXE init,
but AXE init is queued behind the long agents startup refresh. This creates the observed long startup badge behavior and
is the primary root cause path.

## Why Previous Fix Was Insufficient

The earlier fix targeted blocking work inside `on_mount`. That improved mount responsiveness, but it did not address
callback sequencing after mount:

- `call_after_refresh(self._run_agents_async_refresh)` is currently enqueued before AXE init.
- `call_after_refresh(self._run_axe_startup_init)` runs later.
- Because AXE init is delayed, stopwatch termination is delayed.

Additionally, startup behavior now depends on callback ordering rather than explicit concurrency, which is brittle.

## Fix Strategy

### Goal

Decouple AXE startup init from agents refresh so stopwatch progress and completion are not blocked by agent loading.

### Design

1. Introduce a dedicated post-mount startup launcher that starts agents and AXE refresh concurrently (fire-and-forget)
   instead of awaiting one before starting the other.
2. Launch each startup task via Textual workers (preferred) or explicit tasks with exception handling.
3. Ensure startup stopwatch lifecycle remains driven by AXE first-load completion (`_apply_axe_status_data`), but AXE
   task starts immediately after first paint.

### Concrete Code Changes

1. `src/sase/ace/tui/app.py`

- Replace the two direct `call_after_refresh(...)` calls with one bootstrap callback (e.g.
  `_start_post_mount_background_loads`).
- In that bootstrap callback, schedule:
  - agents startup refresh
  - axe startup init concurrently, without serial dependency.
- Preserve existing `_mounting` semantics and startup loading indicators.

2. Optional small guard improvements

- Make startup launcher idempotent (prevent accidental double-scheduling).
- Keep exception paths isolated so one background startup task failing does not suppress the other.

## Test Plan

### New regression tests

1. `tests/ace/tui/test_startup_stopwatch_live_update.py`

- Add a test proving post-mount scheduling launches both startup tasks without serial dependency.
- Validate AXE startup task is scheduled immediately and not gated by agents task completion.

2. Add an async behavior test with controlled delays

- Stub agents startup path to delay significantly.
- Stub AXE startup path to complete quickly and assert `end_startup_stopwatch()` can be reached while agents startup is
  still in progress.

### Existing test coverage to rerun

- `tests/ace/tui/test_startup_stopwatch_live_update.py`
- Relevant TUI suites touching startup, agents, axe
- Full `just check`

## Manual Verification

1. Run `sase ace` with a slow agents load scenario.
2. Confirm stopwatch increments continuously from `0.0s` onward.
3. Confirm AXE status appears as soon as AXE startup init finishes, even if agents are still loading.
4. Confirm no regressions in:

- agents initial loading indicators
- CL selection restoration
- saved-query fallback

## Risks and Mitigations

- Risk: concurrent startup tasks race on shared UI state.
  - Mitigation: keep each apply-path focused to its own tab/state and avoid cross-mutation.
- Risk: unhandled task exceptions become noisy.
  - Mitigation: use Textual worker APIs or explicit exception logging.
- Risk: startup duplication if callback re-fired.
  - Mitigation: add one-shot/idempotent guard for startup task launcher.

## Acceptance Criteria

- Stopwatch no longer appears frozen at `0.2s` during startup.
- AXE startup status transition is no longer delayed by agent startup refresh.
- All checks/tests pass (`just check`) with no regressions in startup behavior.
