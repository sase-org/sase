---
create_time: 2026-05-01 14:58:48
status: done
prompt: sdd/prompts/202605/single_axe_instance.md
---
# Make `sase axe` Effectively Single-Instance

## Problem

Multiple `sase axe` orchestrators can currently run at the same time. The main race is split across two layers:

- `src/sase/axe/process.py:start_axe_daemon()` checks the PID file before it spawns `sase axe start`, but two callers
  can both observe "not running" and both launch children.
- `src/sase/axe/orchestrator.py:Orchestrator.run()` tries to kill an existing orchestrator after the child process
  starts, but two direct `sase axe start` commands can both see no PID, both write their own PID, and both continue
  supervising lumberjacks.

The existing PID file is useful for status, but it is not a mutual exclusion primitive. The fix should make the
lifecycle atomic at the process boundary, not just improve UI state.

## Goals

- At most one live axe orchestrator per user/state directory.
- Concurrent TUI starts, concurrent CLI starts, and mixed TUI/CLI starts converge on one orchestrator.
- Stale PID files remain self-healing.
- Stop/restart operations do not race with start.
- Existing lumberjack and chop behavior stays unchanged except that duplicate supervisors are prevented.
- Tests cover the race-prone boundaries directly.

## Non-Goals

- Do not prevent multiple individual lumberjack foreground commands (`sase axe lumberjack run <name>`) unless they are
  spawned by duplicate orchestrators. Those are documented foreground subcommands and may still be useful for debugging.
- Do not add a third-party locking dependency. The project already uses `fcntl.flock()` for cross-process locks, and the
  environment is Unix-oriented.
- Do not redesign axe scheduling, runner pools, chop execution, or agent deduplication.

## Proposed Design

### 1. Add a dedicated axe lifecycle lock

Create a small lock API near axe state/process code, likely in `src/sase/axe/process.py` or a new
`src/sase/axe/lock.py`:

- Lock file: `~/.sase/axe/orchestrator.lock`.
- Implementation: `fcntl.flock()` on an open file descriptor.
- Two modes:
  - Blocking exclusive lock for lifecycle operations.
  - Non-blocking acquisition for the orchestrator's lifetime claim.
- The lock file should be created under `AXE_STATE_DIR`, so tests can patch state paths the same way existing axe tests
  do.

This lock, not `orchestrator.pid`, becomes the authoritative "only one startup/control path at a time" gate.

### 2. Make the orchestrator own the lifetime lock

In `Orchestrator.run()`:

- Acquire the lifecycle lock non-blocking at the very beginning, before `_kill_existing_orchestrator()` and before
  writing `orchestrator.pid`.
- If the lock is already held, print a clear message and exit successfully without spawning lumberjacks. This makes
  duplicate direct `sase axe start` invocations harmless.
- Keep the lock file descriptor open for the full duration of the orchestrator loop.
- Release it only in the `finally` block after children have been terminated/reaped and the PID file has been removed.

This makes it impossible for two cooperating `sase axe start` orchestrators to supervise lumberjacks at the same time,
even if they start in the same millisecond.

### 3. Serialize parent-side start/stop/restart operations

In `start_axe_daemon()`:

- Acquire the same lifecycle lock in blocking mode around the parent-side `get_axe_pid()` check and `Popen()`.
- Re-check `get_axe_pid()` after the lock is acquired.
- Spawn the child only if no live orchestrator exists.
- Wait briefly for the child to either:
  - write a live `orchestrator.pid`, or
  - exit because another already-running orchestrator held the lifetime lock.
- Return the live orchestrator PID when one exists, and only return `None` for genuine failures.

Important detail: the parent must not hold the lock indefinitely, because the child needs to acquire it for its
lifetime. The parent holds it only for "decide and spawn"; the child acquires it as the permanent owner immediately
after process start.

In `stop_axe_daemon()`:

- Acquire the lifecycle lock in blocking mode only for PID discovery and signal initiation if practical, or at minimum
  use the same helper to prevent simultaneous start/stop decision races.
- Preserve the existing graceful SIGTERM then SIGKILL behavior.
- After signaling, wait for the PID file and process liveness to clear.

In `_restart_axe_daemon()` / TUI restart:

- Prefer a single process-layer `restart_axe_daemon()` helper that holds lifecycle coordination across stop then start,
  instead of composing two independently-racy calls in the TUI.

### 4. Strengthen process identity checks

Keep the PID file, but harden what "running" means:

- `get_axe_pid()` should continue cleaning stale PID files.
- Consider validating that the PID's command line still looks like `sase axe start` before treating it as an axe
  orchestrator, at least on Linux via `/proc/<pid>/cmdline`.
- If command-line validation is too invasive, document it as a follow-up; the lock is the main correctness barrier.

The priority is eliminating duplicate starts. PID identity validation is defense-in-depth against PID reuse.

### 5. Clean up legacy duplicate behavior

Replace `_kill_existing_orchestrator()` with a narrower stale/legacy cleanup path:

- The normal duplicate path should be "lock held, exit without spawning" rather than "kill whatever is in the PID file".
- Keep stale PID cleanup for dead PIDs.
- Avoid killing a valid running orchestrator just because another `sase axe start` was invoked. A start command should
  be idempotent.

This changes startup semantics from "new start wins" to "existing daemon wins", which is safer for a scheduler daemon.

### 6. Improve user-facing results

- `sase axe start` should report when axe is already running and include the PID.
- TUI `_start_axe()` should treat "already running" as success or neutral, not "Failed to start axe".
- Stop should remain clear when there is no running daemon.

The UI should stop encouraging repeated start attempts when the daemon is already active.

## Test Plan

Add focused tests before broad integration:

- `tests/test_axe_lock.py` or expanded `tests/test_axe_process.py`:
  - lock acquisition is exclusive across two file descriptors;
  - stale lock file presence alone does not block acquisition once no process holds the `flock`.
- `tests/test_axe_orchestrator.py`:
  - when lifetime lock acquisition fails, `Orchestrator.run()` exits without spawning lumberjacks or overwriting the
    live PID;
  - when lock acquisition succeeds, PID is written and lock is held until shutdown/finally;
  - stale PID cleanup does not kill a process when the lock says another orchestrator is active.
- `tests/test_axe_process.py`:
  - concurrent or repeated `start_axe_daemon()` calls do not call `Popen()` more than once when a live PID appears;
  - `start_axe_daemon()` returns an existing PID as neutral success when another orchestrator wins the race;
  - `stop_axe_daemon()` still sends SIGTERM and cleans stale PID files.
- Optional higher-confidence race test:
  - use multiprocessing/threading with a temporary state dir and mocked spawn boundary to prove that only one contender
    gets to the spawn decision.

Run:

- Targeted tests: `just test tests/test_axe_process.py tests/test_axe_orchestrator.py`
- Full required verification after edits: `just check`

Because repo memory says this workspace may have a stale virtualenv, run `just install` first if the check target needs
dependencies.

## Implementation Order

1. Add the lock helper and unit tests for exclusive behavior.
2. Wire `Orchestrator.run()` to acquire and hold the lifetime lock before PID writes or child spawning.
3. Change `start_axe_daemon()` to serialize its check/spawn path and return existing/live PID as idempotent success.
4. Adjust `stop_axe_daemon()` and restart behavior so lifecycle operations do not interleave poorly.
5. Update user-facing messages/tests for "already running" semantics.
6. Run targeted tests, then `just check`.

## Risks and Mitigations

- Advisory locks only work if all code paths cooperate. This plan covers the real `sase axe start` entry point and the
  TUI `start_axe_daemon()` path; direct foreground lumberjack commands remain intentionally outside the singleton
  contract.
- A parent-side blocking lock cannot be held while the child runs, or the child would be unable to become the lifetime
  owner. The implementation must keep parent and child lock scopes separate.
- PID reuse can still confuse a PID-only status check. The lock prevents duplicate starts, and `/proc/<pid>/cmdline`
  validation can reduce this remaining edge on Linux.
- Tests that patch `AXE_STATE_DIR` must also patch the lock path if it is a module constant. Prefer deriving the lock
  path dynamically from `axe_state.AXE_STATE_DIR` to keep tests simple and avoid stale constants.
