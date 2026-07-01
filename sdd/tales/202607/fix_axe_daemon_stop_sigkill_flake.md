---
create_time: 2026-07-01 15:56:43
status: done
prompt: sdd/prompts/202607/fix_axe_daemon_stop_sigkill_flake.md
---
# Fix CI red: `test_stop_axe_daemon_targets_inherited_lock_daemon` SIGKILL (`-9`) flake

## TL;DR

CI `test-cov` is red on a single test:

```
FAILED tests/test_axe_process.py::test_stop_axe_daemon_targets_inherited_lock_daemon
       - AssertionError: assert -9 == 0
 +  where -9 = wait(timeout=1.0)
===== 1 failed, 15022 passed, 12 skipped, 42 warnings in 776.40s (0:12:56) =====
```

This is a **load-dependent test flake**, not a product bug. It is the _next stage_ of a race that was already partially
fixed in commit `98d5df888` ("test: install axe SIGTERM handler before readiness"). The earlier fix closed the `-15`
(uncaught-SIGTERM) window; this failure is the `-9` (SIGKILL escalation) window that the prior plan explicitly
predicted.

The fix is **test-only**: make the impersonating child exit instantly on SIGTERM (`os._exit(0)` instead of
`sys.exit(0)`) and give the SIGTERM grace period realistic headroom (raise the test's artificially-tight `timeout=2.0`).
No production code changes.

## Evidence

- The failing assertion is `assert proc.wait(timeout=1.0) == 0`, and the actual value is **`-9`** (SIGKILL), not `-15`
  (SIGTERM). `-9` means the daemon's _first_ signal (SIGTERM) did **not** kill the child — the child caught it — but the
  child did not finish exiting before the stop logic escalated to SIGKILL.
- The other assertions in the test (`orchestrator_pid == child_pid`, `orchestrator_signaled is True`,
  `orchestrator_stopped is True`, `failed_pids == ()`) are **not** the failure — the stop/targeting logic works
  correctly. Only the child's _exit code_ is wrong.
- The failure appears only in the full `test-cov` suite under `xdist` (776 s wall time, heavy CPU contention) and not in
  isolated runs — the signature of a scheduling/timing flake that reads as deterministic on a busy CI runner.
- Git history: `98d5df888` reordered the child so the SIGTERM handler is installed **before** the readiness `print`,
  fixing the `-15` variant. Its plan (`sdd/tales/202606/fix_axe_daemon_sigterm_handler_race.md`) explicitly
  distinguishes `-15` (uncaught SIGTERM) from `-9` (SIGKILL escalation). We have now hit the `-9` path.

## Root cause

`test_stop_axe_daemon_targets_inherited_lock_daemon` spawns a small child process that impersonates the orchestrator
(inherits the lifecycle-lock fd, writes its own PID into the lock file), installs a graceful SIGTERM handler, prints its
PID as a readiness signal, then `time.sleep(30)`. The parent then calls:

```python
result = stop_axe_daemon_result(timeout=2.0, kill_timeout=1.0)
```

`stop_axe_daemon_result` → `_terminate_process` (`src/sase/axe/_process_stop.py`) sends **SIGTERM first**, waits up to
`timeout` seconds for the process to disappear (`_wait_for_exit`, which polls `is_process_running` every 0.1 s and
correctly treats a zombie as dead), and escalates to **SIGKILL** only after `timeout` expires.

The child's handler is `lambda _signum, _frame: sys.exit(0)`. On SIGTERM the child must, all within the **2.0 s**
wall-clock grace:

1. be scheduled to wake from `time.sleep(30)` (EINTR),
2. run the Python-level signal handler,
3. execute `sys.exit(0)` → raise `SystemExit` → run full interpreter shutdown, and
4. actually terminate (become a reapable zombie).

Under the fully-loaded `xdist` suite, CPU starvation can delay steps 1–3 past the 2.0 s deadline. `_wait_for_exit`'s
deadline is wall-clock, so it expires regardless of how starved the _child_ is; the stop logic then sends SIGKILL and
the child's exit code becomes `-9` instead of `0`.

This is purely a consequence of the test's **artificially-tight** `timeout=2.0`. The production defaults are `15.0` /
`5.0` (`stop_axe_daemon`/`stop_axe_daemon_result` signatures), which give a well-behaved daemon ample room; production
is not affected.

### Why the sibling test matters

`test_stop_axe_daemon_targets_recorded_daemon_not_acquirer` (same file) carries the **identical** latent flake: same
`lambda: sys.exit(0)` handler, same `stop_axe_daemon_result(timeout=2.0, kill_timeout=1.0)`, same
`... .wait(timeout=1.0) == 0` assertion. CI history shows these two tests alternating red. Fixing only the currently-red
one would leave the sibling to flip red later.

## Proposed fix (test-only)

Apply two changes to **both** affected tests in `tests/test_axe_process.py`
(`test_stop_axe_daemon_targets_inherited_lock_daemon` and `test_stop_axe_daemon_targets_recorded_daemon_not_acquirer`):

1. **Deterministic, instant child exit.** Change the SIGTERM handler from `sys.exit(0)` to `os._exit(0)`:

   ```text
   signal.signal(signal.SIGTERM, lambda _signum, _frame: os._exit(0))
   ```

   `os._exit(0)` terminates immediately with status `0`, skipping interpreter shutdown (steps 3–4 above collapse to a
   single syscall). This removes the shutdown-latency portion of the race window. Both children already `import os` and
   already `print(..., flush=True)` before installing the handler, so nothing that needs flushing is lost.

2. **Realistic SIGTERM grace headroom.** Raise the SIGTERM grace from `timeout=2.0` to `timeout=10.0` (keep
   `kill_timeout=1.0`):

   ```python
   result = stop_axe_daemon_result(timeout=10.0, kill_timeout=1.0)
   ```

   `_wait_for_exit` polls and returns the instant the child is gone, so a larger `timeout` costs **nothing** on the
   happy path — it only widens the window before SIGKILL escalation, absorbing signal-delivery/scheduling latency under
   a starved runner. This moves the test's grace toward the production default (15 s) rather than masking a real hang:
   the handler-ordering bug is already fixed, so a correctly-behaving child simply needs enough scheduling headroom.

Together these make the test effectively deterministic: `os._exit(0)` guarantees the exit is instantaneous once the
handler runs, and the larger grace guarantees the handler has time to run before escalation.

## Goals / Non-goals

**Goals**

- Make CI `test-cov` green by removing the SIGKILL-escalation (`-9`) flake from
  `test_stop_axe_daemon_targets_inherited_lock_daemon`.
- Harden the sibling `test_stop_axe_daemon_targets_recorded_daemon_not_acquirer` against the identical latent flake.
- Keep both tests exercising the real "stop the daemon and verify **graceful** exit" path — the `== 0` assertion stays
  and remains meaningful (a genuine failure-to-catch-SIGTERM would still surface as a non-zero code).

**Non-goals**

- No production code change. `stop_axe_daemon_result` is correct (graceful SIGTERM, escalate to SIGKILL on timeout); its
  real defaults already provide ample grace.
- No weakening of the assertions. We are not making the test accept `-9`; we are ensuring a correct child always reaches
  `0`.

## Verification plan

1. `just install` (ephemeral workspace requires it before other recipes).
2. Run both targeted tests in a loop to confirm no flake, ideally under concurrent CPU load to reproduce the original
   starvation window, e.g.:
   - `pytest tests/test_axe_process.py::test_stop_axe_daemon_targets_inherited_lock_daemon tests/test_axe_process.py::test_stop_axe_daemon_targets_recorded_daemon_not_acquirer -p no:randomly`
     in a 30–50x loop while the machine is busy; confirm exit code is consistently `0`, never `-9`/`-15`.
3. `just check` (format/lint/test) before completion, per repo policy.
4. Real confirmation is CI: the `test-cov` lane should be green with no `-9 == 0` (and no regression of the sibling
   test).

## Risks

- **Low.** Test-only change; production untouched. `os._exit(0)` is safe here because all required output is already
  flushed before the handler is installed. Raising `timeout` can only _reduce_ premature SIGKILL escalation, never
  introduce a race. If a real regression ever made the child fail to catch SIGTERM, it would still be caught (the exit
  code would be non-zero).

## Follow-ups (optional, separate)

- The prior plan already suggested a shared helper for these "graceful-SIGTERM child" source strings so the
  install-handler-before-readiness + instant-exit invariants are encoded once and cannot regress per-test. Still low
  priority; track as its own bead if desired.
