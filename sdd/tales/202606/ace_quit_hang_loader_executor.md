---
create_time: 2026-06-17 10:56:03
status: done
prompt: sdd/prompts/202606/ace_quit_hang_loader_executor.md
---
# Fix `sase ace` hanging for a long time after quitting with `q`

## Problem

When the user quits the `sase ace` TUI with the `q` keymap, the terminal **sometimes** hangs for a long time (multiple
seconds, occasionally much longer) before the shell prompt returns. The TUI visually disappears immediately, but the
process does not actually exit for a while.

## Root cause (confirmed)

The hang happens _after_ the Textual app has torn down — between `app.run()` returning and the process actually exiting
— during **Python interpreter shutdown**.

The culprit is the shared, process-wide JSON loader thread pool introduced recently in commit `ea03d2701` ("feat: Make
`sase ace` TUI refresh feel instant"):

- `src/sase/ace/tui/models/_loaders/_json_cache.py` defines `get_loader_executor()`, a lazily-created
  `ThreadPoolExecutor` (`thread_name_prefix="sase-loader"`, up to 8 workers). Its docstring explicitly says callers
  "should ... never shut it down — it lives for the life of the process."
- Heavy artifact refreshes fan out across this pool with `executor.map(...)`:
  - `_done_loaders.py:238` — `load_done_agents` (`done.json` markers across every project/workflow dir)
  - `_workflow_step_loaders.py:250` — `load_workflow_agent_steps`
  - `dismissed_agents_bundles.py:332` — dismissed-bundle loads
- These loaders run **off the UI thread** during startup and on every agents-tab refresh (e.g. `_loading_disk.py:282`
  calls them via `asyncio.to_thread(...)`), and refreshes are also triggered by the auto-refresh timer and by the
  inotify artifact watcher.

`ThreadPoolExecutor` worker threads are **non-daemon**, and `concurrent.futures` registers an interpreter-exit hook
(`_python_exit`, installed via `threading._register_atexit`). At shutdown that hook **appends a sentinel to each
worker's queue and then `join()`s every worker** — which means it first **drains the entire backlog of already-queued
work items** before any worker can exit. So if a heavy refresh has queued/in-flight JSON reads at the moment `q` is
pressed, the process cannot exit until _every one of those reads completes_.

This explains both observations:

- **"Sometimes"** — only hangs when a refresh's reads happen to be queued/in-flight at quit time.
- **"A really long time"** — the delay is proportional to the queued backlog. Long sessions with many agents/projects
  mean thousands of artifact JSON files; a cold cache (or freshly-bumped mtimes) makes each read non-trivial, so the
  drain can take many seconds.

### Empirical confirmation

A minimal reproduction (non-daemon `ThreadPoolExecutor`, 40 queued tasks, only a couple consumed before calling
`sys.exit(0)`) measured wall-clock from start to actual process exit:

| Scenario                                                         | Time to actually exit                                                   |
| ---------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Never shut down (today's behavior)                               | **10.24 s** — interpreter-exit hook drained the whole backlog           |
| `executor.shutdown(wait=False, cancel_futures=True)` before exit | **2.21 s** — only the in-flight batch finished; the rest were cancelled |

In the real TUI each task is a fast JSON read rather than a 1 s sleep, so cancelling the pending backlog makes quit
effectively instant.

## Why this is the right layer to fix

Per `memory/short/rust_core_backend_boundary.md`, this is presentation/process-lifecycle glue specific to the Python TUI
process (the loader pool exists only in this repo's TUI), not shared domain behavior. The fix belongs here in the Python
TUI quit path, not in `sase-core`.

## Goal

Quitting `sase ace` with `q` returns to the shell prompt promptly and deterministically, regardless of how much
artifact-loading work is in flight, without losing the refresh-performance win that the shared loader pool provides
during a session.

## Proposed approach

Cancel the loader pool's _pending_ (not-yet-started) work at quit so the interpreter-exit hook only has to wait for the
≤8 already-running reads (near-instant), instead of draining the whole backlog.

### 1. Add an explicit shutdown entry point to the loader pool

In `src/sase/ace/tui/models/_loaders/_json_cache.py`, add a `shutdown_loader_executor()` helper that, under the existing
`_EXECUTOR_LOCK`, snapshots and clears the global `_LOADER_EXECUTOR`, then calls
`executor.shutdown(wait=False, cancel_futures=True)`:

- `cancel_futures=True` (available on Python 3.9+; this repo runs 3.10) drops every queued-but-not-started task — this
  is what eliminates the long drain.
- `wait=False` ensures the quit path itself never blocks on the join.
- Clearing the global makes the call idempotent and avoids reusing a shut-down executor.
- Update the existing "never shut it down" docstring note to point at this new lifecycle hook.

### 2. Call the shutdown from the TUI quit/teardown path

In `src/sase/ace/tui/actions/lifecycle.py`, invoke `shutdown_loader_executor()` from both quit paths so it runs no
matter how the app exits:

- `_do_quit()` (the `q` keymap and the "kill background tasks and quit" confirmation path), and
- `on_unmount()` (Textual's teardown hook — covers any other exit, e.g. Ctrl+C / programmatic exit).

Place it alongside the existing watcher-stop / discovery-cancel cleanup. Use the same defensive, import-local style
already used in that file so a loader-pool that was never created (executor is `None`) is a no-op.

### 3. Make the in-flight loader consumers tolerate a mid-flight shutdown

Cancelling pending futures while a refresh is concurrently consuming `executor.map(...)` will surface a
`concurrent.futures.CancelledError` (and a post-shutdown `submit()` would raise `RuntimeError`) inside the off-thread
refresh that is being abandoned anyway. To avoid a stray error/toast on quit, make the three `executor.map(...)`
consumers (`_done_loaders.load_done_agents`, `_workflow_step_loaders.load_workflow_agent_steps`,
`dismissed_agents_bundles.load_dismissed_bundles`) treat a shutdown-in-progress as "return what we have / empty,"
catching `CancelledError`/`RuntimeError` around the map consumption. (The results are discarded during teardown
regardless.)

## Out of scope / secondary follow-ups (note, do not fix here)

- **Axe worker on quit** (`src/sase/ace/tui/actions/axe.py`): `_start_axe`/`_stop_axe`/`_restart_axe_daemon` run
  blocking work via `run_worker(thread=True)` on Textual's own (also non-daemon) worker pool. A quit _while an axe
  start/stop is shelling out_ could block exit by the same interpreter-join mechanism. This is rare (only during an
  explicit axe operation), so it does not match the "sometimes on normal quit" report. Worth a follow-up if it ever
  bites, but not part of this fix.
- The `fs_watcher` thread is a **daemon** thread joined with a 1 s timeout in `stop()`; it is bounded and not the source
  of the long hang.

## Testing

- **Unit / regression test** for `shutdown_loader_executor()`: after submitting slow tasks to the loader executor and
  calling the shutdown helper, assert pending futures are cancelled and the call returns promptly without draining the
  backlog (assert `wait=False` / `cancel_futures` semantics via a small timing or cancellation assertion); assert a
  subsequent `get_loader_executor()` returns a fresh, usable executor; assert calling the helper when no executor exists
  is a no-op.
- **Lifecycle test**: assert `_do_quit()` and `on_unmount()` call the loader shutdown (mock/spy), in addition to the
  existing watcher/discovery cleanup, and that the existing quit behavior is preserved.
- **Consumer resilience test**: assert `load_done_agents` / `load_workflow_agent_steps` / `load_dismissed_bundles`
  return gracefully (empty/partial, no raised `CancelledError`/`RuntimeError`) when the loader executor is shut down
  mid-iteration.
- Run `just check` (per `memory/short/build_and_run.md`; remember `just install` first in this ephemeral workspace).

## Acceptance criteria

- Quitting `sase ace` with `q` returns to the shell prompt promptly even immediately after a heavy agents-tab refresh /
  on a large multi-project artifact tree.
- No new error toasts or tracebacks appear on quit when a refresh was in flight.
- In-session refresh performance is unchanged (the shared loader pool still parallelizes reads during normal operation;
  it is only torn down at quit).
- `just check` passes.
