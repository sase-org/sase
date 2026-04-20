---
create_time: 2026-04-20 18:48:16
status: done
---

# Plan: Fix `%repeat` directive to run agents sequentially

## Problem

The `%repeat:N` (`%r:N`) directive currently spawns N agents nearly simultaneously. Only a 1-second stagger separates
consecutive spawns, and because each agent is launched as a detached subprocess, all N agents end up running
concurrently in the background.

The intended behavior is **sequential**: agent `K+1` should not be started until agent `K` has finished. This lets users
use `%r:N` to iterate — e.g., re-try a workflow, or run a series of independent steps — without flooding the system with
parallel agents.

## Root Cause

`spawn_repeat_batch()` in `src/sase/agent/repeat_launcher.py` (lines 181–184) iterates over the per-slot specs and
invokes the caller-supplied `base_spawn_fn(spec)` in a tight loop with only `time.sleep(sleep_between)` in between:

```python
for i, spec in enumerate(specs):
    if i > 0 and sleep_between > 0:
        time.sleep(sleep_between)   # 1-second stagger — NOT a completion wait
    base_spawn_fn(spec)             # spawns a detached subprocess and returns immediately
```

`base_spawn_fn` (either `_spawn_repeat_slot` in CLI's `launch_agent_from_cwd` or `_spawn_one` in the TUI's
`_launch_repeat_agents`) ultimately calls `spawn_agent_subprocess()`, which fires off
`subprocess.Popen(..., start_new_session=True)` — a detached process — and returns immediately. So the loop is
effectively a fire-and-forget batch spawner with a small stagger, not a sequential runner.

## Approach

Block inside `spawn_repeat_batch()` between spawns, waiting for the just-spawned agent to complete before launching the
next one. Agent completion is already well-defined in this codebase:

- Each agent writes `agent_meta.json` (with its PID) to an artifact directory under
  `~/.sase/projects/<project>/artifacts/ace-run/<timestamp>/` when it starts.
- The agent writes `done.json` to that same directory when it finishes.
- `src/sase/agent/names.py` already has `find_named_agent(name)` (scans for the artifact dir by agent name) and
  `is_process_alive(meta, artifact_dir)` (PID liveness check) — both are reusable.

### Design

Introduce a new helper `wait_for_agent_completion(name, poll_interval=2.0)` in `src/sase/agent/names.py` that:

1. **Locates the agent's artifact dir** by polling `find_named_agent(name)` until it returns a match (the subprocess may
   take a moment to write `agent_meta.json`).
2. **Polls that artifact dir** until either:
   - `done.json` appears (normal completion), OR
   - the recorded PID is no longer alive (crash / killed without writing `done.json`).

Both conditions count as "complete" — the next agent should start regardless of how the previous one exited. We don't
want a crashed agent to block the remainder of the batch forever.

Modify `spawn_repeat_batch()` to call this helper after each `base_spawn_fn(spec)` call (except, optionally, after the
last one — there's no next agent to gate on). The existing `time.sleep(sleep_between)` stagger is no longer
load-bearing; it can be removed or kept as a small post-completion cushion (preference: keep a short cushion for any
settle-down work like `done.json` write flushes that happen after the process exits).

### Why this location

- `spawn_repeat_batch()` is the one shared entry point exercised by both the CLI (`sase run --daemon`) and the TUI
  (`sase ace`) dispatchers. Fixing it here covers both paths with one change.
- The TUI dispatcher already calls `spawn_repeat_batch()` from inside a daemon `threading.Thread`
  (`src/sase/ace/tui/actions/agent_workflow/_agent_launch.py:488`), so blocking inside `spawn_repeat_batch()` won't
  freeze the TUI.
- The CLI dispatcher calls `spawn_repeat_batch()` from the `sase run` daemon path (`src/sase/agent/launcher.py:280`);
  blocking there is acceptable — the daemon already stays alive to manage the launch lifecycle, and the user explicitly
  asked for the full batch to proceed in order.

### Contrast with the nearest existing pattern

`multi_prompt_launcher.launch_multi_prompt_agents()` and `_launch_multi_model_agents` in the TUI both have a similar
loop with `time.sleep(1)` between spawns but no completion wait — they are explicitly fan-out (every alt prompt runs
concurrently, which is intentional for `%m(opus,sonnet)`). `%repeat` differs in intent: it is meant to be a serial
iteration, not a fan-out. So we do **not** touch the multi-model path — only `%repeat`.

## Changes Summary

| File                                            | Change                                                                                                                                                                                                                                                                                                  |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/agent/names.py`                       | Add `wait_for_agent_completion(name, poll_interval=2.0)` — locates the artifact dir via `find_named_agent`, then polls for `done.json` OR PID death.                                                                                                                                                    |
| `src/sase/agent/repeat_launcher.py`             | In `spawn_repeat_batch()`: after each `base_spawn_fn(spec)`, call `wait_for_agent_completion(spec.name)` before moving to the next spec. Keep the existing stagger as a short post-completion cushion (or drop it entirely — decide during implementation based on how `done.json` write timing looks). |
| `tests/test_repeat_launcher.py`                 | Update the existing stagger-sleep test; add a test verifying that `base_spawn_fn` for slot `k+1` is only called after the completion signal for slot `k`.                                                                                                                                               |
| `tests/test_agent_launch_repeat.py`             | Verify integration behavior with the new wait in the TUI path. May need to stub `wait_for_agent_completion` to return immediately so the test doesn't actually poll real filesystem state.                                                                                                              |
| (new) `tests/test_wait_for_agent_completion.py` | Unit test the new helper: done.json → returns; dead PID → returns; missing artifact dir → polls then returns once dir appears.                                                                                                                                                                          |

## Edge cases / considerations

1. **Agent crashes before writing `agent_meta.json`.** `find_named_agent` will never return a match. Mitigation: cap the
   initial "find the artifact dir" phase with a timeout (e.g., 60 s), after which we log and proceed to the next spawn —
   the first spawn clearly failed to start, but we shouldn't hang forever.
2. **Agent crashes after `agent_meta.json` but before `done.json`.** Handled by the PID-liveness check — when the PID
   dies, we treat it as complete.
3. **User Ctrl-Cs during a wait.** `KeyboardInterrupt` propagates out of `spawn_repeat_batch()` naturally; the remaining
   specs simply never spawn. Acceptable.
4. **`sleep_between` parameter.** Currently defaults to 1.0 and is tested. Options: (a) keep it as a post-completion
   cushion applied after the wait; (b) remove it. Recommendation: keep it but reduce the default (e.g., 0.25 s) since
   its original purpose (rate-limiting the spawn burst) is subsumed by the wait.
5. **Signature compatibility of `base_spawn_fn`.** Unchanged — callers still return `None`. All the waiting logic
   happens by name lookup, not via a handle returned from the callback. This keeps the CLI and TUI dispatchers
   untouched.
6. **Existing callers' return values.** The CLI path returns `slot_results[0]` (the first agent's launch metadata) after
   `spawn_repeat_batch()` returns. That still works — the first agent's metadata is populated well before the batch
   completes, since `slot_results.append(...)` happens inside `_spawn_repeat_slot`, which runs as the first spawn before
   any wait.
7. **`only_done=True` in `find_named_agent`.** The helper currently prefers running agents but can match done ones via
   `only_done=True`. Our new helper should NOT pass `only_done=True` — we want to find the running agent first, then
   watch it. Let the default behavior apply.

## Non-goals

- No change to the `%r:N` / `%repeat:N` parsing syntax.
- No new opt-out flag for concurrent behavior. The user's request is absolute: `%repeat` is sequential. If we later want
  a parallel fan-out we'd introduce a new directive (e.g., `%fan:N`) rather than complicating `%repeat`.
- No change to `%m(...)` multi-model split, `%wait`, or `multi_prompt_launcher` — those remain concurrent fan-outs as
  intended.
- No changes to `spawn_agent_subprocess()`, detached-process semantics, or artifact-dir layout.

## Testing

- `just check` — ruff + mypy + pytest w/ coverage.
- Unit test matrix for `wait_for_agent_completion`:
  - done.json already present → returns immediately
  - done.json appears after a few polls → returns when it does
  - PID dies without done.json → returns
  - artifact dir appears after delay → proceeds to phase-2 polling
  - artifact dir never appears (timeout) → logs and returns (does not hang)
- Unit test for `spawn_repeat_batch` sequential ordering: use a mock `base_spawn_fn` plus a stubbed
  `wait_for_agent_completion` to assert call order is strictly `spawn(1) → wait(1) → spawn(2) → wait(2) → spawn(3)`.
- Existing repeat launcher and TUI launch tests continue to pass (may need small updates to stub the new wait call so
  they don't hit the filesystem).
- Manual smoke test in `sase ace`: fire `%r:3 <some trivial prompt>` and confirm exactly one agent is visible as running
  at a time.
