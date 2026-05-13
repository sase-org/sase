---
create_time: 2026-05-13 01:05:02
status: done
prompt: sdd/prompts/202605/qwen_wait_chain.md
---
# Plan: Fix stalled Qwen wait chain

## Current evidence

- Live status initially showed only two active Qwen phase agents in the `sase-3a` family: `sase-3a.4` and `sase-3a.8`.
- The intended dependency lanes are modulo-three chains:
  - lane 1: `sase-3a.1 -> .4 -> .7 -> ...`
  - lane 2: `sase-3a.2 -> .5 -> .8 -> ...`
  - lane 3: `sase-3a.3 -> .6 -> .9 -> ...`
- `sase-3a.6` had a successful `done.json`, but `sase-3a.9` was still blocked on `waiting.json` for `sase-3a.6`.
- The waits lumberjack process was alive and ticking, but its `wait_checks` chop history head was still `running` from
  `2026-05-13T00:36:44-04:00` with a stale PID. Because `_active_script_chop_run()` treats any head `running` script
  chop as live, scheduled `wait_checks` was skipped on every tick after AXE restarted at `2026-05-13T00:37:51-04:00`.
- A manual `sase_chop_wait_checks` run resolved the live chain by writing `ready.json` for `sase-3a.7` and `sase-3a.9`;
  `sase agents status -j` then showed three Qwen agents running: `.7`, `.8`, and `.9`.

## Implementation plan

1. Add stale script-chop detection to the chop-run dedupe path.
   - Update `_active_script_chop_run()` in `src/sase/axe/chop_runner.py`.
   - If the latest run entry is `running` but carries a `pid` that is no longer alive, it should not block a new
     scheduled run.
   - Prefer finalizing the stale entry as a failure or timeout-like stale state if the existing state helpers support it
     cleanly; otherwise, return `None` so the scheduler can recover. The implementation must preserve the current
     live-run dedupe behavior for actually-live script chops.

2. Add focused tests for the stale-running case.
   - Extend `tests/test_axe_chop_runner.py` near the existing `_active_script_chop_run()` tests.
   - Cover a `running` head with an alive PID still returning the live entry.
   - Cover a `running` head with a dead PID returning `None` so a new run can start.
   - Cover missing/no PID conservatively according to the chosen implementation.

3. Verify the operational fix.
   - Run the focused chop-runner tests.
   - Run `sase_chop_wait_checks --context /home/bryan/.sase/axe/lumberjacks/waits/tick/context.json` if needed to
     confirm it can still resolve ready waits.
   - Re-check `sase agents status -j` and confirm three Qwen agents are RUNNING.

4. Run repository checks.
   - Because this is a repo code change, run `just install` first if needed for this workspace, then `just check` per
     project instructions.
   - If `just check` is too slow or blocked, report the exact blocker and the focused tests that did run.
