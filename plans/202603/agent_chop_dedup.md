---
create_time: 2026-03-27 17:21:42
status: done
---

# Plan: Prevent Duplicate Agent Chop Instances

## Problem

Two `sase/refresh_docs` agents are running simultaneously in the `sase ace` TUI. The chop is configured with
`run_every: 60m`, but when the agent takes longer than 60 minutes to complete, the lumberjack launches a second instance
because there is no "already running" guard.

## Root Cause

In `src/sase/axe/lumberjack.py`, `_run_agent_chop()` (line 189):

1. **Cleans up dead PIDs** from `self._agent_pids` and computes a `still_alive` set (lines 197-209)
2. **Never checks `still_alive`** before launching — proceeds unconditionally to `launch_agent_from_cwd()` (line 218)
3. The comment on line 81 says `# Track running agent processes per chop (multiple allowed)` — confirming this was
   deliberately designed without a singleton guard

The `run_every` timer (lines 138-144) gates on elapsed time since last _launch_, not on whether the previous run
_completed_. So once 60 minutes pass, a second agent spawns even though the first is still running.

## Fix

Add a singleton guard in `_run_agent_chop()`: when `still_alive` is non-empty, skip the launch and log a message. This
applies to all agent chops since there's no valid use case for running duplicate instances of the same agent chop
concurrently.

### Changes

#### 1. `src/sase/axe/lumberjack.py`

In `_run_agent_chop()`, after the dead-PID cleanup block (line 209), add:

```python
if still_alive:
    self._log(
        f"Skipping agent chop '{chop.name}': already running (PIDs {still_alive})"
    )
    return False
```

Also update the comment on line 81 from `(multiple allowed)` to reflect the new singleton behavior.

#### 2. `tests/test_axe_lumberjack.py`

Add two tests:

- `test_agent_chop_skips_when_already_running`: Mock `launch_agent_from_cwd`, simulate a still-alive PID in
  `_agent_pids`, verify that the second tick does NOT launch a new agent.
- `test_agent_chop_launches_after_previous_completes`: Same setup but the PID is dead (os.kill raises OSError), verify
  the new agent IS launched.
