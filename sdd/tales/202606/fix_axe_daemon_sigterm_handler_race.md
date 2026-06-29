---
create_time: 2026-06-29 12:46:09
status: done
prompt: sdd/prompts/202606/fix_axe_daemon_sigterm_handler_race.md
---
# Fix CI red: `test_stop_axe_daemon_targets_inherited_lock_daemon` SIGTERM-handler race

## TL;DR

The CI failure you pasted (`test_agents_commit_messages_panel_png_snapshot` — "Timed out waiting for commit delta
summary") is **already fixed** and is no longer the blocker. The commit that landed just before this investigation
(`test: make commit snapshot cwd-independent`) resolved that test; the latest CI run confirms it now **passes** (it
shows up only in the slow-durations list at ~7.6s, not in the failures).

CI is still red, but on a **different** test:

```
FAILED tests/test_axe_process.py::test_stop_axe_daemon_targets_inherited_lock_daemon
       - AssertionError: assert -15 == 0
```

This is a **signal-handler-installation race** in the test's helper child process, not a product bug. The fix is a
two-line reorder in the test so the child installs its `SIGTERM` handler **before** it announces readiness — exactly the
ordering the sibling test in the same file already uses.

## Evidence: what is actually failing now

The latest CI run on `master` (the HEAD commit "test: make commit snapshot cwd-independent") fails with a single test:

```
______________ test_stop_axe_daemon_targets_inherited_lock_daemon ______________
...
>           assert proc.wait(timeout=1.0) == 0
E           AssertionError: assert -15 == 0
E            +  where -15 = wait(timeout=1.0)
===== 1 failed, 14847 passed, 12 skipped, 8 warnings in 825.06s ======
```

In that same run, `test_agents_commit_messages_panel_png_snapshot` appears in the slowest-durations report (~7.56s) and
is **not** in the failures — i.e. the commit-delta-summary timeout the prompt referenced is resolved.

Across the recent run history the red CI has alternated between exactly these two single-test failures:

- the commit-delta-summary timeout (older runs, before the cwd fix landed), and
- the `... -15 == 0` axe-daemon failure (the current run).

The commit-delta one is fixed; the axe-daemon one is what keeps CI red now.

## Root cause

`tests/test_axe_process.py::test_stop_axe_daemon_targets_inherited_lock_daemon` spawns a small child process that
impersonates the orchestrator daemon, then calls `stop_axe_daemon_result(...)` and asserts the child exits cleanly with
code `0`.

The child source string runs these steps in this order:

```text
... write its pid into the inherited lock fd ...
print(pid, flush=True)                                     # (A) announces "I'm ready" to the parent
signal.signal(signal.SIGTERM, lambda ...: sys.exit(0))     # (B) installs graceful SIGTERM handler
time.sleep(30)
```

The parent's readiness gate is the printed pid line:

```python
line = proc.stdout.readline().strip()   # waits until (A) has run
...
result = stop_axe_daemon_result(timeout=2.0, kill_timeout=1.0)   # sends SIGTERM to the child
```

`stop_axe_daemon_result` sends **SIGTERM first** for a graceful shutdown and only escalates to SIGKILL after a timeout
(confirmed in `src/sase/axe/_process_stop.py`: SIGTERM at the terminate step, SIGKILL only on `timeout` expiry).

So there is a race window between (A) and (B): once the child has printed its readiness line, the parent is free to
deliver SIGTERM, but the child has **not yet installed its handler**. If SIGTERM arrives in that window, the child dies
under the **default** SIGTERM disposition and `proc.wait()` returns `-15` instead of `0`.

The signature confirms this precisely:

- The exit value is `-15` (SIGTERM), not `-9` (SIGKILL) — so the daemon's _first_ signal killed it, and it never reached
  the SIGKILL escalation. The child simply didn't catch the SIGTERM the daemon legitimately sent.
- The prior assertions in the test (`orchestrator_signaled is True`, `orchestrator_stopped is True`,
  `failed_pids == ()`) all pass — the stop logic worked correctly. Only the child's _exit code_ is wrong, because its
  graceful handler hadn't been installed yet.

This loses the race only under load, which is why it surfaces in the full `test-cov` suite under `xdist` (heavy CPU
contention slows the child between print and handler install) but passes when the test is run in isolation. That makes
it a load-dependent flake that reads as deterministic on the busy CI runner.

### The fix is already demonstrated in the same file

The sibling test `test_stop_axe_daemon_targets_recorded_daemon_not_acquirer` in the same file makes the **same**
`... .wait(timeout=1.0) == 0` assertion and does **not** flake, because its child installs the handler **before**
announcing readiness:

```text
signal.signal(signal.SIGTERM, lambda ...: sys.exit(0))   # handler first
print(os.getpid(), flush=True)                           # readiness after
time.sleep(30)
```

The failing test is simply the only one in the file that emits readiness before installing the handler.

## Proposed fix

In `test_stop_axe_daemon_targets_inherited_lock_daemon`, reorder the child source string so the `SIGTERM` handler is
installed **before** the `print(pid, flush=True)` readiness line. The pid still needs to be written into the inherited
lock fd first (that is what the daemon-targeting logic reads); only the handler-vs-readiness ordering changes:

```text
... write pid into the inherited lock fd, fsync ...
signal.signal(signal.SIGTERM, lambda ...: sys.exit(0))   # MOVED: install handler first
print(pid, flush=True)                                    # readiness now strictly after the handler
time.sleep(30)
```

This guarantees that by the time the parent observes the readiness line and proceeds to send SIGTERM, the handler is
already installed, so the child always exits `0`. It matches the proven, race-free ordering of the sibling test.

This is the whole fix — a reorder of two adjacent lines in the child-process source string. No production code changes.

## Goals / Non-goals

**Goals**

- Make CI green by removing the SIGTERM-handler-install race from `test_stop_axe_daemon_targets_inherited_lock_daemon`.
- Keep the test exercising the real "stop the inherited-lock daemon and verify graceful exit" path; do not weaken the
  `== 0` assertion or relax timeouts.

**Non-goals**

- No production code change. `stop_axe_daemon_result` behaves correctly (graceful SIGTERM, escalate to SIGKILL on
  timeout); the bug is purely in the test child's startup ordering.
- No change to the commit-delta-summary visual test — it is already fixed and passing on the current HEAD.

## Verification plan

1. `just install` (ephemeral workspace requires it before other recipes).
2. Run the targeted test repeatedly to confirm it no longer flakes, including under artificial load, e.g.:
   - `pytest tests/test_axe_process.py::test_stop_axe_daemon_targets_inherited_lock_daemon -p no:randomly` in a loop
     (e.g. 20–50 iterations), ideally with the machine under concurrent CPU load to reproduce the original race window.
   - Confirm the child consistently exits `0` (never `-15`).
3. `just check` (format/lint/test) before completion, per repo policy.
4. The real confirmation is CI: after this lands, the `test-cov` lane should be green (no `-15 == 0`, and the
   commit-delta test continues to pass).

## Risks

- **Low.** Test-only change; production untouched. The reorder strictly widens the window in which the handler is
  installed (it is now installed before readiness is announced), so it can only reduce the race, never introduce one.
  The change mirrors an existing, passing test in the same file.

## Follow-ups (separate, optional)

- Consider a small shared helper for these "graceful-SIGTERM child" source strings so the
  install-handler-before-announce-readiness invariant is encoded once and cannot regress per-test. Low priority; track
  as its own bead if desired.
- The latent test-isolation working-directory issue noted in the prior commit-delta plan (some suite test changing the
  process CWD without restoring it) remains a separate, optional hardening item and is unrelated to this fix.
