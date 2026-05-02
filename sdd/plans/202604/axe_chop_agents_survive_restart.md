---
create_time: 2026-04-27 11:10:22
status: done
prompt: sdd/prompts/202604/axe_chop_agents_survive_restart.md
---
# Plan: Make lumberjack-launched agents survive axe restarts

## Problem

Restarting `sase axe` should stop the axe scheduler/orchestrator machinery, but it should not kill or orphan the
long-lived agents/workflows that a lumberjack chop has already launched. This matters for both current configured agent
chops such as:

```yaml
agent: "#gh:sase #sase/pylimit_split %approve"
```

and script chops like the local `~/.config/sase/chops/sase_pylimit_split` pattern that eventually runs `sase run -d` to
launch one or more agents.

The intended ownership boundary is:

- `axe orchestrator` owns lumberjack processes.
- A `lumberjack` owns scheduling and short-lived chop execution.
- Once a chop launches an agent/xprompt workflow, that agent is an independent workflow and must outlive axe
  restart/stop.

## Current findings

The direct Python agent chop path already uses `spawn_agent_subprocess(... start_new_session=True)`, so the final agent
runner is designed to be detached from the lumberjack process. However, axe restart still has two fragile areas:

1. Lumberjack only tracks launched agent PIDs in memory (`self._agent_pids`). Restart loses that state, so the new
   lumberjack cannot know that a previous chop-launched agent is still alive except indirectly through the RUNNING
   field/artifacts.
2. Script chops are just subprocesses of the lumberjack. A script can launch agents via `sase run -d`, but axe has no
   durable ownership metadata for those launches and no standard environment contract tying launched agents back to the
   chop that spawned them.

This means a restart can either actually terminate an in-flight launch path in some shutdown modes, or make the
restarted axe treat the old launch as invisible and start duplicate work. Both violate "these agents/workflows should
live on."

## Design

Make chop-launched agents explicitly detached and durably discoverable.

### 1. Add a durable chop-agent registry

Add a small persistence layer under the axe state directory, probably:

```text
~/.sase/axe/lumberjacks/<lumberjack>/agent_chops.json
```

Each record should include:

- `lumberjack_name`
- `chop_name`
- `prompt_hash` or normalized prompt key
- `pid`
- `project_file`
- `project_name`
- `workspace_num`
- `workflow_name`
- `cl_name`
- `artifacts_timestamp`
- `started_at`

Records are append/update-on-launch and pruned when the PID is no longer running or a `done.json` is present.

### 2. Use the registry for agent chop eligibility

Replace the purely in-memory `_agent_pids` check with a persistent check:

- Load live registry records for the chop.
- Cross-check `is_process_running(pid)`.
- Cross-check RUNNING field/artifacts when registry metadata is present.
- If a live record exists, skip the chop after restart just as the old process would have skipped it before restart.
- Keep the in-memory set only as a fast local cache, not as the source of truth.

This addresses duplicate relaunch and gives axe a restart-safe view of "the previous lumberjack already started this."

### 3. Propagate chop metadata through every launch path

For configured agent chops:

- In `Lumberjack._launch_agent_chop`, pass an env block such as:

```text
SASE_CHOP_LUMBERJACK=<name>
SASE_CHOP_NAME=<chop.name>
SASE_CHOP_RUN_ID=<stable timestamp/uuid>
```

- Ensure `spawn_agent_subprocess` or the runner writes those fields into `agent_meta.json`.
- After `launch_agent_from_cwd()` returns, write the registry record from `AgentLaunchResult`.

For script chops:

- `run_chop_script()` should inject the same `SASE_CHOP_*` environment for the chop subprocess.
- `spawn_agent_subprocess()` should detect those env vars and write a registry record itself. This catches scripts that
  call `sase run -d`, including multi-prompt launchers.
- Also write the chop metadata into `agent_meta.json` so the TUI/debugging surface can explain where the agent came
  from.

### 4. Keep process boundaries explicit

Preserve `start_new_session=True` for actual agent runner processes and add a regression test that asserts it. This is
the important boundary that lets agent runners survive parent/lumberjack termination.

For script chops, do not treat the script process as the long-lived work. If a restart interrupts a script after it has
launched an agent, the launched agent remains authoritative. If the script was still preparing and had not launched
anything yet, it is acceptable for the new lumberjack to retry on the next tick.

### 5. Make restart shutdown semantics intentional

Keep `stop_axe_daemon()` scoped to the orchestrator and lumberjacks. Do not add any cleanup that kills agents whose
metadata says they came from a chop.

Review `Orchestrator._terminate_children()` and the final wait/escalation path. If escalation is needed, it should still
target only lumberjack PIDs, not agent process groups. Add tests around this behavior so future changes do not broaden
SIGTERM/SIGKILL to descendant agent process groups.

## Implementation steps

1. Add a helper module, likely `src/sase/axe/chop_agents.py`, with:
   - record dataclass
   - read/write/prune helpers
   - `record_chop_agent_launch(...)`
   - `get_live_chop_agent_records(...)`

2. Update `Lumberjack`:
   - Inject `SASE_CHOP_*` into script chop env.
   - Pass `SASE_CHOP_*` plus existing auto-dismiss env to configured agent chops.
   - Replace `_is_agent_eligible()` with durable registry-backed eligibility.
   - Record configured agent launches immediately after `launch_agent_from_cwd()` returns.

3. Update `spawn_agent_subprocess()` or the runner metadata phase:
   - Detect `SASE_CHOP_*` env.
   - Add chop metadata to `agent_meta.json`.
   - Record script-launched agents in the durable registry.
   - Ensure multi-prompt and repeat fan-out record every spawned child, not only the first returned result.

4. Add tests:
   - Configured agent chop writes a registry record and skips after a simulated lumberjack restart while PID is live.
   - Dead PID records are pruned and allow a later launch.
   - Script chop env includes `SASE_CHOP_*`.
   - `spawn_agent_subprocess()` records a launch when called under `SASE_CHOP_*`.
   - Multi-prompt script launches record each child.
   - Orchestrator stop/restart does not call `killpg()` or otherwise target agent PIDs.

5. Manual verification:
   - Start axe.
   - Trigger a chop-launched long-running agent.
   - Restart axe from the TUI or `sase axe stop && sase axe start`.
   - Confirm the original agent PID remains alive, remains visible in Agents, and the new lumberjack skips relaunching
     that chop until the agent exits.

## Validation

Run:

```bash
just install
just check
```

If the implementation touches chezmoi config or moves the local `chops/sase_pylimit_split` script into managed chezmoi
state, also run `just check` in `~/.local/share/chezmoi/` and then `chezmoi apply`.
