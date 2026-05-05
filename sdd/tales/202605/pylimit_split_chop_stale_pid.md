---
create_time: 2026-05-05 15:26:48
status: done
prompt: sdd/prompts/202605/pylimit_split_chop_stale_pid.md
---
# Plan: Fix stale PID dedup for `sase_pylimit_split` agent chops

## Problem

The live `sase_pylimit_split` chop is configured in chezmoi as:

```yaml
agent: "#gh:sase #!sase/pylimit_split %approve"
run_every: 60m
```

That part looks structurally correct: the chop launches the standalone `sase/pylimit_split` workflow in the SASE repo,
and that workflow discovers over-limit files, builds a `%wait`-chained multi-prompt, and launches one
`#sase/pysplit:<path>` agent per file.

The failure is in lumberjack-side singleton tracking for agent chops. The `run_every` log shows:

- `2026-05-05 12:02:48`: launched `sase_pylimit_split` as PID `2742890`.
- The corresponding workflow artifacts at `~/.sase/projects/sase/artifacts/ace-run/20260505120247/` show `done.json`,
  `workflow_state.status=completed`, and `launch_split_agents.launched=1`.
- The `#sase/pysplit` child at `20260505120254` also completed successfully by `2026-05-05T16:10:05Z` (`12:10:05` EDT).
- Starting at `2026-05-05 13:02:57`, every eligible tick skipped the chop as already running with PID `2742890`,
  continuing until the lumberjack was restarted at `15:17`.

After restart, the same pattern is visible again:

- The new outer workflow PID `3523988` completed immediately with `done.json` and `launch_split_agents.launched=3`.
- `ps` now shows PID `3523988` as a zombie child of the `run_every` lumberjack.
- The durable `agent_chops.json` record was later overwritten by inherited chop metadata from the final live
  `#sase/pysplit` child (`3530278`), while the in-memory `Lumberjack._agent_pids` fallback still remembers only the
  outer workflow PID (`3523988`).

The immediate bug is that `Lumberjack._is_agent_eligible()` prunes `_agent_pids` with raw `os.kill(pid, 0)`. Zombies
make `os.kill(pid, 0)` succeed even though the workflow has exited and written `done.json`. SASE already has
`sase.ace.hooks.processes.is_process_running()`, which checks `/proc/<pid>/status` and returns false for zombies, but
this fallback path does not use it.

## Goal

Make recurring agent chops skip only when a live chop workflow or live chop-launched child agent is actually running.
Completed or zombie outer workflow runner processes must not block the next `run_every` interval.

## Proposed Design

Use one liveness predicate for chop-agent dedup:

1. Keep the durable registry check first. It has the richest context and already treats records with `done.json` as not
   live.
2. Replace the raw `os.kill(pid, 0)` in the in-memory fallback with the zombie-aware `is_process_running(pid)`.
3. Opportunistically reap direct child PIDs that the lumberjack launched and that have exited, using non-blocking
   `os.waitpid(pid, os.WNOHANG)` for PIDs held in `_agent_pids`.

This keeps the current scheduling semantics:

- A live `#sase/pysplit` child that inherited chop metadata can still make `sase_pylimit_split` count as running.
- A completed outer `#!sase/pylimit_split` workflow no longer blocks future runs only because its runner process is a
  zombie.
- No chezmoi change is needed unless later testing shows the applied YAML differs from the source YAML.

## Implementation Steps

1. Update `src/sase/axe/lumberjack.py`:
   - import `is_process_running`;
   - add a small helper to reap exited child PIDs from `_agent_pids`;
   - call the helper before checking `_agent_pids`;
   - use `is_process_running(pid)` instead of raw `os.kill(pid, 0)` in `_is_agent_eligible()`.

2. Add focused tests in `tests/test_axe_lumberjack_agent_chops.py`:
   - a stored in-memory PID that is not live according to `is_process_running()` does not block eligibility;
   - a stored in-memory PID that is live still blocks eligibility;
   - a completed/zombie-like outer workflow PID does not block even when there are no live durable registry records;
   - a live durable `#sase/pysplit` child record still blocks relaunch.

3. Add or adjust a durable-registry test in `tests/test_axe_chop_agents.py` only if needed to pin the current inherited
   chop-env behavior for child agents. The registry should remain able to represent live child work from a chop-launched
   workflow.

4. Run focused verification:

```bash
just install
uv run pytest tests/test_axe_lumberjack_agent_chops.py tests/test_axe_chop_agents.py
```

5. Run required repo verification after code changes:

```bash
just check
```

## Non-Goals

This plan does not change the chezmoi chop definition, the `sase/pylimit_split` workflow prompt shape, or the
`#sase/pysplit` `%wait` fanout. It also does not redesign the durable registry into a full multi-record run graph,
although the current registry replacement-by-`run_id` is worth a separate follow-up if another chop needs exact
visibility into all fanout children at once.

## Validation

The fix is successful when:

- a completed `sase_pylimit_split` outer workflow PID that remains as a zombie no longer causes
  `Skipping agent chop 'sase_pylimit_split': already running`;
- a genuinely live `#sase/pysplit` child still prevents a duplicate pylimit split run;
- restarting axe is no longer required to clear stale in-memory chop PID state;
- focused tests and `just check` pass.
