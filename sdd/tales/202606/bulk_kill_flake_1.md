---
create_time: 2026-06-01 09:06:31
status: done
prompt: sdd/prompts/202606/bulk_kill_flake_1.md
---
# Plan: Fix Bulk Kill Flake

## Problem

`tests/test_agent_kill_bulk.py::test_do_bulk_kill_agents_refreshes_and_schedules_once` sometimes observes raw
`os.killpg` calls as `[111, 222, 222, 111]` instead of `[111, 222]`.

The failing assertion is racing production behavior rather than exposing a duplicate bulk-kill scheduling bug.
`_do_bulk_kill_agents()` calls `_kill_agent_process_group()`, which delegates to
`request_user_kill(..., wait=False, background=True, killpg=os.killpg)`. The shared user-kill helper sends SIGTERM
immediately, then starts a daemon thread that polls the process group and escalates to SIGKILL after the grace period if
the process still appears alive.

In this test, `os.killpg` is patched with a `MagicMock` that never raises `ProcessLookupError` for liveness checks. If
the test runner stalls after the bulk-kill call but before the assertion, those background threads can append additional
calls to the same mock. That makes the test timing-dependent. The production escalation path is already covered directly
in `tests/test_agent_user_kill.py`, so the bulk-kill unit test should not assert on raw signal calls.

## Approach

1. Replace raw `os.killpg` patching in the affected bulk-kill tests with a mock at the stable TUI boundary:
   `sase.ace.tui.actions.agents._killing.request_user_kill`. Return a simple success object for normal kills.

2. Update the failing assertion to verify one user-kill request per killable agent, in input order, instead of one raw
   `killpg` call per PID. This preserves the behavior the bulk-kill test owns: the bulk path requests each kill once and
   schedules one persistence worker.

3. Update the failed-PID bulk-kill test to drive the permission-denied branch through `request_user_kill` return values
   instead of a raw `killpg` side-effect. This keeps the failure behavior deterministic and avoids background thread
   leakage.

4. Run the focused bulk-kill test module first, then the broader relevant kill tests (`test_agent_kill.py`,
   `test_agent_user_kill.py`, phase 1/2 kill tests) to confirm the mocked boundary still matches the lower-level helper
   contract.

5. Because this repo requires it after source changes, run `just install` if needed and finish with `just check`.

## Expected Outcome

The flaky test no longer depends on daemon-thread timing. The bulk-kill tests continue to prove immediate UI mutation,
single refresh, single persistence task scheduling, and failure handling. The signal escalation behavior remains covered
by the dedicated user-kill helper tests.
