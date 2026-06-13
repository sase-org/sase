---
create_time: 2026-06-13 12:27:01
status: done
prompt: sdd/prompts/202606/axe_restart_stuck_indicator.md
---
# Fix: `sase ace --restart-axe` leaves the axe status indicator stuck at "RESTARTING"

## Problem / product context

Running `sase ace --restart-axe` launches the TUI and is supposed to restart the axe daemon on startup, with the
bottom-right status indicator showing `RESTARTING` only transiently before settling to `RUNNING`. In practice the
indicator stays at `RESTARTING` indefinitely, and the user has to manually kill leftover sase processes to recover. The
restart never visibly completes.

This plan diagnoses the root cause and fixes the indicator so it deterministically settles to the true terminal state
(`RUNNING` or `STOPPED`) after a restart, and makes the underlying "daemon is up" detection honest so the TUI and the
process layer agree.

## Root cause (verified by code reading + live inspection)

The `RESTARTING` flag is a _transient operation-in-flight_ flag, but it is only ever **cleared as a side effect of
observing `axe_running == True`** during a status read. There is no code path that clears it when the restart operation
simply _finishes_. Three things combine so that the clearing read never lands:

1. **The transient flags are cleared asymmetrically.** In `src/sase/ace/tui/actions/axe_display/_loaders.py`
   (`_apply_axe_status_data`, lines ~171–178), `STARTING`/`RESTARTING` are cleared **only** when `axe_running` is
   `True`; `STOPPING` is cleared only when `axe_running` is `False`. So if a status read ever observes "not running"
   while `RESTARTING` is set, the flag survives untouched.

2. **The post-restart read happens too early and disagrees with the worker's success.** `_restart_axe_daemon`
   (`src/sase/ace/tui/actions/axe.py:266`) runs `restart_axe_daemon()` in a worker thread; on completion
   `_on_axe_worker_done` (`axe.py:281`) does a single, immediate, synchronous `_load_axe_status()`.
   - The worker reports success based on `start_axe_daemon()` → `_wait_for_daemon_start(process, timeout=3.0)` in
     `src/sase/axe/process.py:142`. That helper waits only **3 seconds** for the orchestrator **PID file**
     (`~/.sase/axe/orchestrator.pid`) to appear, then **falls back to returning the live `process.pid`** even when the
     PID file has not been written yet.
   - A freshly spawned `sase axe start` process must import the whole `sase` package (heavy, frequently > 3s on a cold
     start, especially right as the TUI itself is starting). So the worker routinely returns "success" _before_ the new
     orchestrator has published its PID file.
   - `_on_axe_worker_done` → `_load_axe_status()` → `is_axe_running()` → `get_axe_pid()` reads the **PID file**, which
     is not there yet → `axe_running=False` → per (1), `RESTARTING` is **not** cleared.

   The mismatch is structural: the worker's success predicate (`process.pid` alive) is _not_ the same predicate the
   indicator uses (`get_axe_pid()` / PID file present).

3. **Nothing re-polls axe status promptly afterward.** `_on_auto_refresh`
   (`src/sase/ace/tui/actions/_event_refresh.py:387`) gates the axe-status poll behind `_dirty_axe` whenever the inotify
   watcher is active. The watcher (`startup.py:_start_artifact_watcher`) watches `~/.sase/projects/`, `sdd/beads`, and
   the notifications dir — **never `~/.sase/axe/`** — so the new daemon's PID file appearing never sets `_dirty_axe`.
   The only unconditional re-read is the 60s `FULL_SANITY_REFRESH_SECONDS` reconcile. So even in the benign case the
   indicator is stuck for up to ~60s; and if the restart genuinely fails to bring the daemon back (slow cold start,
   orphaned children — see below), that 60s read still sees "not running" and `RESTARTING` is stuck **forever**.

`--restart-axe` is the _only_ caller of `_restart_axe_daemon` (there is no manual restart keymap; the manual toggle uses
`_start_axe`/`_stop_axe`), which is exactly why the user only sees this via the flag.

**Ruled out:** the lifecycle flock is _not_ held by lumberjack children — verified live via `/proc/<pid>/fd` (only the
orchestrator holds `orchestrator.lock`, fd 11). So lock contention from children does not block the new daemon. The
earlier "lock held by lumberjacks" hypothesis is incorrect.

**Secondary contributor to "manually kill sase acts":** `stop_axe_daemon` SIGTERMs the orchestrator, which forwards
SIGTERM to lumberjacks and force-kills (SIGKILL) any that do not exit within ~10s. A lumberjack mid-agent-run that is
SIGKILLed orphans its agent/hook grandchildren ("acts"), which keep running and must be killed by hand. This is a
related but separable defect from the stuck indicator.

## Design / approach

Two coordinated fixes resolve the root cause; a third is optional hardening.

### Fix 1 — Make daemon-readiness detection honest (`src/sase/axe/process.py`)

Align "the worker reports success" with "the indicator can detect the daemon."

- Rework `_wait_for_daemon_start` so it polls `get_axe_pid()` (the _same_ PID-file-based predicate the
  TUI/`is_axe_running()` uses) until it is non-`None`, with a timeout generous enough for a cold `sase` import (e.g.
  ~15s), and returns `None` if the spawned process dies or the timeout elapses without the PID file appearing.
- Stop returning the bare `process.pid` as a "started" fallback when the PID file is absent — that is the false-positive
  that desynchronizes the worker from the indicator. (If we want to preserve a liveness signal, only treat the process
  as started once `get_axe_pid()` confirms it; otherwise report failure so the TUI can surface it.)

This makes `restart_axe_daemon()`/`start_axe_daemon()` return a PID only when `is_axe_running()` will agree, so the
immediate post-worker read in the TUI lands on `RUNNING`. It also benefits any other caller of these process functions.

### Fix 2 — Clear the transient flag deterministically on operation completion (TUI)

Treat `STARTING`/`RESTARTING`/`STOPPING` as "operation in flight" flags that are cleared when the operation's worker
_completes_, not as a side effect of a particular disk read.

- In `_on_axe_worker_done` (`src/sase/ace/tui/actions/axe.py:281`), once the worker has finished, ensure the transient
  flags are cleared and the indicator reflects the freshly observed `axe_running` (→ `RUNNING` if up, `STOPPED` if not).
  The existing failure `notify(...)` already covers the genuine-failure case; the indicator must no longer be left in
  the intermediate `RESTARTING`/`STARTING` state.
- Add a short, **bounded** re-poll to absorb any residual cold-start lag: if the worker reported success but the first
  read still shows not-running, schedule a few follow-up `_load_axe_status_async()` reads over a few seconds so the
  indicator settles quickly rather than waiting on the 60s sanity reconcile. With Fix 1 this should rarely trigger, but
  it keeps the indicator self-healing and avoids the worst case.

The exact mechanism (clearing inside `_on_axe_worker_done` vs. relaxing the clear condition in `_apply_axe_status_data`
to be symmetric for terminal states) will be chosen during implementation to keep the change minimal and the state model
coherent; the requirement is: **after a restart/start/stop operation finishes, no transient flag persists.**

### Fix 3 (optional hardening) — self-heal the indicator outside the 60s window

Defense-in-depth so a stale transient flag can never linger regardless of Fix 1/2 edge cases: while any axe transient
flag is set, have `_on_auto_refresh` treat axe status as always-due (bypass the `_dirty_axe` gate) until the flag
clears. Cheap, and removes the dependence on the 60s sanity reconcile for this case.

## Scope

In scope:

- `src/sase/axe/process.py` — `_wait_for_daemon_start` (and any caller-contract touch-ups in
  `start_axe_daemon`/`restart_axe_daemon`).
- `src/sase/ace/tui/actions/axe.py` — `_on_axe_worker_done` completion handling.
- `src/sase/ace/tui/actions/axe_display/_loaders.py` — transient-flag clearing in `_apply_axe_status_data` (if the
  symmetric-clear approach is chosen) and/or a bounded re-poll helper.
- Optionally `src/sase/ace/tui/actions/_event_refresh.py` for Fix 3.

Out of scope (recommend tracking separately):

- Orphaned-agent ("sase acts") cleanup on restart — making lumberjacks reliably terminate in-flight agent/hook
  grandchildren on SIGTERM before the orchestrator's SIGKILL escalation. This is a deeper, riskier change touching the
  lumberjack shutdown path and should not be bundled with the indicator fix.

## Testing

- `tests/test_axe_process.py`: add coverage for `_wait_for_daemon_start` where the spawned process is alive but the PID
  file is delayed — assert it waits for `get_axe_pid()` and does not return a premature/false PID, and that it returns
  `None` on timeout/death.
- New TUI test under `tests/ace/tui/` (mirroring `test_axe_live_chop_run.py` / `test_startup_stopwatch_live_update.py`
  harness style): drive `_restart_axe_daemon` → worker completion where the first status read reports not-running, then
  running; assert `RESTARTING` does not persist and the footer settles to the correct terminal state.
- `just check` after implementation (run `just install` first, per the ephemeral-workspace rule). Visual snapshots
  unaffected (no layout change); footer status-string logic is the only display surface touched and is covered by the
  new behavioral test.

## Risks / considerations

- **Startup latency:** Fix 1 lengthens the worst-case wait inside the restart worker (up to ~15s). This runs on a
  background worker thread and does not block the UI; the indicator shows `RESTARTING` meanwhile, which is correct. Keep
  the timeout bounded.
- **Rust core boundary:** axe daemon process control already lives in Python (`src/sase/axe/process.py`) and is not
  mirrored in `sase-core`; this is a refinement of existing behavior, not new cross-frontend domain logic, so no
  `sase-core` change is planned. Flagging in case axe lifecycle is being migrated to core.
- **No false "RUNNING":** the indicator must reflect genuine failure as `STOPPED` (+ the existing error notification),
  not optimistically clear to `RUNNING`. Fix 1 ensures the worker only reports success when the daemon is actually
  detectable.

## Open question

Should the orphaned-process cleanup (lumberjacks killing in-flight agents on restart, the "manually kill sase acts"
pain) be included here, or tracked as a separate follow-up? This plan currently keeps it out of scope to keep the
indicator fix focused and low-risk.
