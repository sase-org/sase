---
create_time: 2026-04-20 19:22:29
status: done
prompt: sdd/prompts/202604/repeat_wait_chain.md
---

# Sequential `%repeat` via `%wait` Chain

## Problem

The `%repeat:N` directive currently spawns all N agents nearly simultaneously (with a 1-second stagger in
`src/sase/agent/repeat_launcher.py:149-186`). This defeats the intent of iterative refinement: each repeat iteration is
supposed to observe the cumulative effect of the prior iteration, but parallel fan-out means iteration K cannot see
iteration K-1's work.

A prior attempt (commit `044fcc6d`, reverted in `263db57d`) solved this by having the launcher itself block between
spawns using a new `wait_for_agent_completion()` helper. The revert suggests the approach was wrong: a blocking launcher
freezes the user's shell/TUI for the full duration of the entire repeat batch, which is bad UX and prevents the user
from interacting with the agents while they run.

## Goal

- All N agents are **spawned up front** (non-blocking launcher, visible immediately in the agent list).
- Agent 1 begins work immediately.
- Agents 2..N each wait for the previous agent to complete before starting their work.
- The wait is delegated to the existing `%wait` directive — no new completion-polling code in the launcher.

## Approach

Modify `spawn_repeat_batch()` so that, when building each spec's prompt, it prepends a `%wait:<previous_name>` line for
every iteration except the first. The launcher stays a simple fire-and-return loop; all coordination happens at the
agent level via the `%wait` machinery that already exists.

### Prompt construction

Currently (in `src/sase/agent/repeat_launcher.py` around line 162):

```python
prompt=f"%n:{base}.{k}\n{prompt_stripped}"
```

New form:

- Iteration 1: `%n:{base}.1\n{prompt_stripped}` (unchanged)
- Iteration K ≥ 2: `%n:{base}.{K}\n%wait:{base}.{K-1}\n{prompt_stripped}`

### Why this works

The follow-up exploration confirmed the `%wait` directive has everything needed:

- `%wait:<name>` polls for the named agent's `done.json` every 2 seconds, via the `wait_checks` lumberjack chop
  (`src/sase/axe/run_agent_phases.py:173-232`). If the agent hasn't been launched yet, it waits for the artifact
  directory to appear.
- It detects PID death, so a crashed or killed previous iteration won't block the chain forever
  (`src/sase/agent/names.py:499-530`, plus the 24-hour hard timeout in `run_agent_phases.py`).
- `%wait` is a `multi_value` directive (`src/sase/xprompt/directives.py:129`), so any pre-existing `%wait` the user put
  in their prompt stacks with the injected one rather than colliding.
- Directive ordering does not matter; `%n:X\n%wait:Y` and `%wait:Y\n%n:X` parse identically.
- A combined `%n:foo\n%wait:bar` prompt is already exercised in `tests/test_directives_types.py`, so we are not
  inventing a new usage pattern.

### What to keep vs. drop

- **Keep** the 1-second `sleep_between` stagger in the launcher. The artifact directory for agent K-1 may not be on disk
  the instant `base_spawn_fn(spec)` returns; the stagger gives it time to register so agent K's `%wait` resolves against
  a known name cleanly. The behavior is still correct without it (the wait chop handles missing names), but the stagger
  reduces noisy "waiting for unknown agent" transitions.
- **Do not** add any `wait_for_agent_completion()` helper or blocking behavior in the launcher. That is exactly what
  commit 044fcc6d did and was reverted for.

## Files to change

- `src/sase/agent/repeat_launcher.py` — in the list comprehension that builds `specs`, derive each spec's prompt so that
  iterations 2..N prepend `%wait:{base}.{k-1}` after the `%n` line. One-place change in `spawn_repeat_batch`.
- `tests/test_repeat_launcher.py` — assert:
  - Iteration 1's prompt contains `%n:{base}.1` and no `%wait:{base}.*`.
  - Iterations 2..N prepend `%wait:{base}.{k-1}` referencing the prior iteration.
  - A pre-existing user `%wait:X` in the prompt is preserved (not clobbered) and appears alongside the injected wait.

## Out of scope

- **Visual indicator for repeat group membership** — tracked by the separate `repeat_agent_visual_indicator` plan.
- **Treating repeat iterations as workflow entries** — tracked by the separate `repeat_agents_as_entries` plan.
- **Re-introducing a blocking launcher variant** — explicitly rejected by the revert of 044fcc6d.
- **Changing the semantics of `%wait` itself** — we are only adding a new caller of the existing behavior.

## Risks and mitigations

- **Risk**: If a middle iteration is killed with SIGKILL before writing any metadata, agent K+1 may sit on `%wait` until
  the 24-hour timeout. **Mitigation**: This is the existing behavior of `%wait` in all other contexts, and the
  `is_process_alive()` PID check in `is_workflow_complete()` catches most dead-process cases well before 24h. No special
  handling needed here.
- **Risk**: A user who intentionally wants parallel fan-out loses that option. **Mitigation**: `%repeat` has never been
  documented as parallel; the 1-second stagger was incidental. If a parallel mode is wanted later, it should be an
  explicit opt-in flag rather than the default.
