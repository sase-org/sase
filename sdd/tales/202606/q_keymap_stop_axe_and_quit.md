---
create_time: 2026-06-27 13:32:42
status: done
prompt: sdd/prompts/202606/q_keymap_stop_axe_and_quit.md
---
# Plan: Make the `Q` keymap reliably stop axe **and** quit the TUI

## Problem

In the `sase ace` TUI, the `Q` keymap is bound to the `stop_axe_and_quit` action. It is supposed to do two things: (1)
stop the running `sase axe` daemon, and (2) quit the TUI. In practice it is unreliable — sometimes axe is not actually
stopped, and sometimes the TUI does not quit. The `sase axe stop` CLI command, by contrast, stops axe reliably, so its
mechanism should be the model for the fix.

## Background / Current Behavior

### The `Q` binding and handler

- `Q` is bound to the `stop_axe_and_quit` action in `src/sase/ace/tui/bindings.py` (and configured in
  `src/sase/default_config.yml` under `keymaps`).
- The handler is `AxeMixin.action_stop_axe_and_quit()` in `src/sase/ace/tui/actions/axe.py`. It currently:
  1. If `self.axe_running` is truthy, looks up `get_axe_pid()` and sends a single `os.kill(pid, SIGTERM)` — "fire and
     forget, without waiting" — catching only `ProcessLookupError` / `PermissionError`.
  2. Calls `_kill_all_running_tasks()`.
  3. Calls `_do_quit()`, whose final step is `self.exit()`.

This shape dates to the commit that migrated axe start/stop to background worker threads. Because `_stop_axe()` now runs
in a worker (and the app would exit before that worker finished), the quit path was changed to a direct, un-escalated
SIGTERM instead.

### How `sase axe stop` stops axe (the model to follow)

`sase axe stop` runs `stop_axe_daemon_result()` (in `src/sase/axe/_process_stop.py`, re-exported from
`src/sase/axe/process.py`). That function is dramatically more robust than the TUI quit path:

- **Authoritative PID resolution.** It probes via `probe_orchestrator()` and uses
  `probe.running_pid or probe.lock_holder_pid` — so it still acts when only the lifecycle lock holder PID is known.
  (`get_axe_pid()` returns only `running_pid`, which can be `None` in lock-held-but-unresolved states.)
- **Escalation.** SIGTERM, wait, then escalate to **SIGKILL** on timeout.
- **Process-group kill.** On timeout it signals the process _group_, catching children.
- **Orphan lumberjack sweep.** It terminates live lumberjacks tracked by their per-worker PID files (SIGTERM → SIGKILL
  with their own timeouts).
- **State cleanup.** Removes stale PID files and clears the lock-holder PID.
- It **blocks until shutdown is confirmed** (bounded by its timeouts).

## Root Cause

Two independent defects, both in `action_stop_axe_and_quit`:

1. **The stop is too weak to be reliable.** A single un-escalated SIGTERM to only `get_axe_pid()`:
   - does nothing if the orchestrator ignores/handles SIGTERM slowly (no SIGKILL fallback);
   - leaves orphaned lumberjacks alive (no process-group kill, no lumberjack sweep);
   - sends **no signal at all** when `get_axe_pid()` is `None` but the lifecycle lock is still held;
   - is skipped entirely whenever `self.axe_running` is stale/`False` (e.g. status not yet refreshed, or a start/stop
     worker still in flight). This is why "stopping axe doesn't always work."

2. **The quit is fragile.** The handler is a straight line of operations with no guarantee that `self.exit()` is ever
   reached. The `os.kill` `except` clause is narrow; `_kill_all_running_tasks()` is unguarded; and `_do_quit()` itself
   performs ~8 cleanup steps before `self.exit()`. If any step raises, `self.exit()` never runs and the user is stranded
   in the TUI — which matches the observed "axe got stopped but the TUI stayed open" symptom (the SIGTERM is sent
   _before_ the step that throws).

## Goals

- Pressing `Q` reliably stops axe — orchestrator **and** lumberjacks — using the same proven mechanism as
  `sase axe stop`.
- Pressing `Q` **always** quits the TUI, even if stopping axe or killing background tasks fails.
- No regression to the normal (lowercase) quit path or to the live `X`/`!x` axe start/stop/restart controls, which must
  keep running off the UI thread.

## Proposed Solution

### 1. Stop axe the way `sase axe stop` does

Rewrite `action_stop_axe_and_quit` so that, instead of a single fire-and-forget SIGTERM, it stops axe via the shared
`stop_axe_daemon_result()` facade (the exact function the `sase axe stop` CLI uses). This immediately inherits
PID-resolution-with-lock-fallback, SIGKILL escalation, process-group kill, lumberjack sweep, and state cleanup.

Two further reliability improvements while we are here:

- **Do not gate the stop on `self.axe_running`.** `stop_axe_daemon_result()` probes real state itself and is a cheap
  no-op when nothing is running, so calling it unconditionally closes the "stale `axe_running` skips the stop" gap. (We
  can still read `axe_running` purely to decide whether to bother, but correctness should not depend on it.)
- **Wrap the stop in `try/except`** so that _no_ failure while stopping axe can prevent the subsequent quit.

### 2. Synchronous vs. worker — design decision

`stop_axe_daemon_result()` blocks until shutdown is confirmed (bounded by its timeouts). There are two viable shapes;
this plan recommends the first:

- **Recommended: synchronous stop in the quit path, with bounded timeouts.** During quit the TUI is tearing down anyway,
  so a brief, bounded block immediately before `self.exit()` is acceptable and is by far the simplest correct design. It
  matches `sase axe stop` exactly. Use modest timeouts (e.g. ~5s SIGTERM wait / ~2s SIGKILL wait) rather than the CLI
  defaults so a wedged daemon cannot make the TUI feel hung. To avoid a spurious event-loop-stall alert during the
  block, stop the stall watchdog **before** the synchronous stop (the watchdog is already stopped inside `_do_quit()`;
  hoist/duplicate that step so it precedes the blocking call).

- **Alternative: worker-based "stop, then quit on completion."** Run the robust stop in a worker thread and call
  `_do_quit()` from `_on_axe_worker_done` once it settles (guarded by a `quit-after-stop` flag), so the UI never blocks.
  This is more faithful to the existing worker architecture but adds real complexity: re-entrancy, the "a start/restart
  worker was already in flight" edge case, and a guard against re-issuing the stop forever if axe is truly wedged.
  Recommend adopting this only if the brief synchronous block proves unacceptable in practice.

### 3. Make the quit bulletproof

Independent of which step (stopping axe, killing tasks, or a cleanup step) might throw, pressing `Q` must end in
`self.exit()`:

- Guard `_kill_all_running_tasks()` in the handler so a failure there cannot block the quit.
- Harden `_do_quit()` so `self.exit()` is guaranteed even if an earlier cleanup step raises (e.g. run the best-effort
  cleanup chain under a `try/finally` whose `finally` calls `self.exit()`, or make each best-effort step individually
  non-fatal). This also hardens the normal lowercase-quit path, which shares `_do_quit()`.

### Resulting `Q` behavior

`Q` → kill running background tasks (guarded) → robustly stop axe + lumberjacks via the `sase axe stop` mechanism
(guarded, bounded) → run quit cleanup → `self.exit()`, with `self.exit()` reached unconditionally.

## Files Likely Touched

- `src/sase/ace/tui/actions/axe.py` — rewrite `action_stop_axe_and_quit` to use `stop_axe_daemon_result()`, drop the
  `axe_running` gate as a correctness dependency, guard task-killing, and ensure the quit always proceeds. Stop the
  stall watchdog before the synchronous stop.
- `src/sase/ace/tui/actions/lifecycle.py` — harden `_do_quit()` so `self.exit()` is guaranteed.
- Tests (see below).

No keymap/config, help-modal, or footer changes are expected — the binding, its label, and its documented meaning ("Stop
axe and quit") are unchanged; only its implementation is fixed. (If the help text is reworded, update the `?` help modal
entries that mention `stop_axe_and_quit` to stay in sync, per the ace AGENTS.md help-popup rule.)

## Testing

- Add/extend unit tests for `action_stop_axe_and_quit` (mirroring the style of
  `tests/ace/tui/actions/test_lifecycle_quit_confirm.py`) asserting:
  - it stops axe via the robust `stop_axe_daemon_result()` path (not a single `os.kill`);
  - `self.exit()` is called even when stopping axe raises;
  - `self.exit()` is called even when `_kill_all_running_tasks()` raises;
  - the stop is attempted even when `axe_running` is stale/`False`.
- Confirm the existing quit-confirm and quit visual-snapshot suites still pass
  (`tests/ace/tui/actions/test_lifecycle_quit_confirm.py`,
  `tests/ace/tui/visual/test_ace_png_snapshots_quit_confirm.py`).
- Manual: with axe running (and again with orphaned lumberjacks present), press `Q` and confirm the TUI exits and that
  `sase axe status` afterward reports nothing running.
- Run `just check` (lint + mypy + tests) before completion, after `just install`.

## Out of Scope

- Changing the live `X` / `!x` axe start/stop/restart controls — those must keep running off the UI thread.
- Changing the lowercase quit's running-task confirmation modal behavior (beyond the shared `_do_quit()` hardening,
  which only makes it strictly more reliable).
- Reworking the underlying `stop_axe_daemon_result()` implementation itself — it already works; this plan only routes
  the `Q` keymap through it.

## Risks / Considerations

- **Brief UI block during quit (recommended approach).** Bounded by the chosen timeouts and occurring only in the
  wedged-daemon case; mitigated by modest timeouts and by stopping the stall watchdog first. Acceptable because it
  happens at the moment of exit.
- **Re-entrancy / in-flight axe worker.** If a start/stop/restart worker is mid-flight when `Q` is pressed, the
  synchronous `stop_axe_daemon_result()` simply probes current state and acts idempotently; the in-flight worker will
  find axe already stopped. No special handling required for the recommended approach.
