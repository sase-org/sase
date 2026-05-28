---
create_time: 2026-05-28 14:00:09
status: done
prompt: sdd/prompts/202605/hook_checks_stale_pidless.md
---
# Diagnose And Fix Stale PID-less `hook_checks` Runs

## Problem

The `hooks / hook_checks` chop appears to be hung in ACE with a run that started on `2026-05-11T20:00:00+00:00` and has
been shown as `running` for hundreds of hours. The live process table does not show a `sase_chop_hook_checks`
subprocess, and the current ACE/Axe processes were started much more recently. Other chops in the `hooks` lumberjack are
still cycling, so the lumberjack itself is not blocked.

The persisted run history under `~/.sase/axe/lumberjacks/hooks/chops/hook_checks/` shows the newest entry:

- run id: `20260511T200000_000001`
- status: `running`
- pid: `null`
- finished_at: `null`
- log: `partial`

The current runner code treats any newest `running` script-chop entry as active. If the entry has a positive PID, the
code validates process liveness and finalizes a stale dead-PID entry. If the entry has no PID, it returns the entry as
active forever because there is no process identity to check. Scheduled lumberjack ticks convert that to
`already_running`, and scheduled `already_running` outcomes are quiet skips. That explains why `hook_checks` no longer
records fresh runs while the other hook chops continue to run.

## Root Cause

The root cause is stale PID-less run metadata poisoning script-chop dedupe. A PID-less `running` entry is a legitimate
short-lived state between `start_chop_run()` and the `stream_chop_script()` PID callback, but it should not be treated
as live indefinitely. If the parent process crashes before the PID is recorded, or old/test state leaks into the run
history, the chop is permanently blocked.

There is already a unit test encoding the problematic behavior:
`test_active_script_chop_run_keeps_pidless_running_entry_conservatively`. That test should be replaced with coverage for
bounded PID-less recovery.

## Desired Behavior

Script-chop dedupe should remain conservative for very recent PID-less `running` entries, but recover old entries
automatically. A PID-less `running` entry older than the configured chop timeout, or a small fallback grace window when
no timeout is configured, should be finalized as a failed stale run so the next scheduled tick can start a fresh run.

For configured `hook_checks`, the lumberjack has `chop_timeout: "90s"`, so a PID-less `running` entry from May 11 should
be finalized on the next dedupe check and should no longer block new runs.

## Implementation Plan

1. Add an age-aware stale check for PID-less script-chop runs in `src/sase/axe/chop_runner.py`.
   - Keep live-PID behavior unchanged.
   - Keep very recent PID-less entries as active to avoid duplicate launches during the brief pre-PID window.
   - Finalize PID-less entries whose `started_at` is older than an effective stale threshold.
   - Use the resolved chop timeout for the threshold when available, with a conservative fallback for chops without a
     timeout.

2. Thread the effective stale threshold into `_active_script_chop_run`.
   - `_run_script_chop_once` already resolves `chop.timeout or chop_timeout_default`; compute that before dedupe and
     pass it into the active-run check.
   - Avoid changing agent-chop dedupe; this issue is specific to script-chop run-history metadata.

3. Reuse the existing finalization path.
   - Extend `_finalize_stale_script_chop_run` to accept an explicit stale reason so the metadata explains whether the
     stale record had a dead PID or no PID after the grace window.
   - Preserve terminal status as `failure`; this is a metadata recovery from an incomplete run, not a successful chop.

4. Update tests.
   - Replace the existing "keeps PID-less forever" test with two focused cases:
     - a recent PID-less running entry remains active and does not call process liveness checks;
     - an old PID-less running entry is finalized and `_active_script_chop_run` returns `None`.
   - Add coverage that `run_configured_chop_once` can recover from an old PID-less head entry and then starts/indexes a
     new run.
   - Keep existing dead-PID and live-PID behavior tests intact.

5. Verify.
   - Run the targeted tests for chop runner/state behavior first.
   - Run `just install` and `just check` because code files changed in the SASE repo.
   - After code verification, inspect or manually trigger `hook_checks` to confirm the stale entry no longer blocks new
     runs. If the installed `sase` currently running ACE uses the global uv-tool install rather than this workspace,
     note that the fix takes effect after reinstall/restart in that environment.

## Risk And Scope

The change is intentionally limited to script-chop run dedupe. The main risk is duplicate script launches if the
PID-less grace window is too short. Using the configured chop timeout, and a nonzero fallback when there is no timeout,
keeps the recovery threshold much longer than the normal subprocess-start window while still preventing permanent
poisoning.
