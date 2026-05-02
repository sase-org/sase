---
create_time: 2026-05-01 13:50:35
status: done
prompt: sdd/prompts/202605/waiting_agents_stuck_maintenance.md
---
# Plan: Fix WAITING Agents Stuck Behind Stale Axe Maintenance

## Problem

`sase axe` is not starting WAITING agents after their waited-on agents complete. The live state shows the `waits`
lumberjack is running and cycling, but every tick is skipped because axe maintenance mode is active:

- reason: `install_sase_github`
- pid: `1039801`
- started_at: `2026-05-01T13:31:33-04:00`

That PID is no longer running. Because the maintenance marker remains present, the `wait_checks` chop never runs, so it
never writes `ready.json` for dependency-satisfied WAITING agents. The waiting runner subprocesses keep polling forever.

## Root Cause

`src/sase/axe/maintenance.py::clear_stale_maintenance()` only clears markers older than the default age threshold (24
hours). It does not validate whether the marker owner PID is still alive.

This creates a failure mode where a maintenance command, installer, or shell wrapper can die after writing
`~/.sase/axe/maintenance.json` but before clearing it. Axe then treats the marker as active until it ages out, pausing
all lumberjack ticks, including the high-frequency `waits` lumberjack.

## Approach

1. Teach maintenance cleanup to treat a marker as stale when its owner PID is no longer running.
   - Reuse the existing process liveness helper (`sase.ace.hooks.processes.is_process_running`) instead of ad hoc
     `os.kill` handling.
   - Preserve the age-based stale cleanup behavior.
   - Keep malformed timestamp behavior unchanged: clear invalid markers.

2. Make the behavior test-covered.
   - Add a test that a recent marker with a dead PID is cleared immediately.
   - Add a test that a recent marker with a live PID is preserved.
   - Keep existing tests for old-marker cleanup and recent-marker preservation passing.

3. Verify the wait path.
   - Run the maintenance unit tests.
   - Run a targeted lumberjack/wait-related test if available.
   - Because this repo requires it after changes, run `just install` if needed and then `just check`.

4. Operational follow-up after the code fix.
   - The current live marker is already stale by PID, but the running installed `sase` will only pick up the fix after
     the local install/update.
   - To unblock the current WAITING agents immediately, clear maintenance with `sase axe maintenance exit` or let a
     fixed lumberjack tick clear it. Once cleared, the `wait_checks` chop should write `ready.json` for dependencies
     that are already complete.

## Expected Result

If a maintenance owner exits unexpectedly, the next lumberjack tick clears the marker and resumes scheduled chops.
WAITING agents whose dependencies have completed should then receive `ready.json`, clean up `waiting.json`, claim their
real workspace if needed, and start normally.
