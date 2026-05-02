---
create_time: 2026-04-29 12:46:36
status: done
prompt: sdd/prompts/202604/bead_work_detach.md
---
# Plan: make `sase bead work` return after launching epic agents

## Problem

`sase bead work <epic_id>` should mark the epic ready, pre-claim its phase beads, launch the phase and land agents,
print the launch summary, and return control to the caller. The command currently appears to keep the calling agent's
command session open until the spawned epic/land work completes.

## Current Findings

- `handle_bead_work()` in `src/sase/bead/cli.py` renders one multi-prompt and calls
  `sase.agent.launcher.launch_agent_from_cwd(query)`.
- Multi-prompt launch is not designed to wait for phase completion. `launch_multi_prompt_agents()` spawns each segment
  as a background subprocess and only polls briefly for `agent_meta.json` names between segments so `%wait` dependencies
  can resolve.
- The more likely hang source is in `spawn_agent_subprocess()` in `src/sase/agent/launcher.py`: it redirects child
  stdout/stderr to the agent output file and uses `start_new_session=True`, but it does not redirect child stdin.
- If `sase bead work` is invoked from an agent shell or another PTY-backed command runner, spawned child agents inherit
  the caller's stdin file descriptor. Even though the parent process exits, the PTY/session may remain open because
  descendants still hold the descriptor. That can make the caller observe the command as running until the final land
  agent exits, which coincides with the epic closing.

## Implementation

1. Update `spawn_agent_subprocess()` to pass `stdin=subprocess.DEVNULL` to `subprocess.Popen`.
   - Keep stdout/stderr behavior unchanged.
   - Keep `start_new_session=True` unchanged.
   - This applies uniformly to all runtime providers and all agent-launch callers, including `sase bead work`, repeat,
     multi-prompt, chop, and retry-spawn launches.

2. Add or update a focused launcher test.
   - Use the existing mocked-`Popen` test coverage in `tests/test_axe_chop_agents.py`.
   - Assert that spawned agents use `stdin=subprocess.DEVNULL`, `start_new_session=True`, and redirected output.
   - This confirms detached subprocesses do not inherit the caller's stdin.

3. Add a regression test around `sase bead work` if the existing mocked launcher tests are not enough.
   - The existing bead tests already assert `handle_bead_work()` calls the launcher once and returns after the mocked
     launch result.
   - If needed, add a narrow test that verifies `sase bead work` uses the normal launcher path rather than adding bead
     specific process handling.

## Verification

1. Run the focused tests:

   ```bash
   pytest tests/test_axe_chop_agents.py tests/test_bead/test_cli_work.py
   ```

2. Run the repo-required check after file changes:

   ```bash
   just install
   just check
   ```

3. If the full check is too slow or blocked by environment issues, report the exact failing command and the relevant
   output, but still run the focused tests first.

## Expected Outcome

`sase bead work <epic_id>` still launches the same multi-agent wave plan, but spawned agents no longer inherit the
caller's stdin. The calling agent should regain control immediately after the launch summary is printed, subject only to
the existing brief per-segment name polling in the multi-prompt launcher.
