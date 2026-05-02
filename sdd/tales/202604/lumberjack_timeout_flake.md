---
create_time: 2026-04-27 16:49:42
status: wip
prompt: sdd/prompts/202604/lumberjack_timeout_flake.md
---
# Plan: Diagnose and Fix Lumberjack Per-Chop Timeout Test Failure

## Problem

`tests/test_axe_lumberjack.py::test_per_chop_timeout_overrides_lumberjack_default` failed with `assert 30 == 10`. The
test expects the first mocked `run_chop_script` call to correspond to the `custom_timeout` chop and therefore to receive
`timeout=10`.

Initial inspection shows the production code already resolves script chop timeouts as
`chop.timeout or self.config.chop_timeout`, so a positive per-chop timeout should override the lumberjack default.
However, `_run_tick` submits eligible chops to a `ThreadPoolExecutor`, and the order in which mocked `run_chop_script`
invocations are recorded can vary by thread scheduling. That means the test is asserting call order for code that
intentionally executes chops concurrently.

## Root Cause Hypothesis

The failure is a flaky test assertion, not a timeout precedence bug:

- `custom_timeout` is configured with `timeout=10`.
- `default_timeout` falls back to the lumberjack `chop_timeout=30`.
- Either chop can reach the mocked `run_chop_script` first because they run in worker threads.
- When `default_timeout` records first, `call_args_list[0].kwargs["timeout"]` is `30`, producing the observed failure.

## Implementation Plan

1. Reproduce the focused failure if possible with the single test and, if useful, repeated focused runs to confirm
   nondeterministic ordering.
2. Update the test so it asserts timeout behavior by chop identity rather than by call position. The existing launch
   environment includes `SASE_CHOP_NAME`, so build a mapping from each mock call's env to its timeout and assert:
   - `custom_timeout` received `10`
   - `default_timeout` received `30`
3. Keep production code unchanged unless reproduction reveals a real behavior bug. If a production issue appears, fix
   the narrow timeout resolution path and add or adjust focused coverage.
4. Run the focused lumberjack timeout test, the lumberjack test module, and then the repo-required `just check` after
   edits.

## Expected Outcome

The test will continue to verify the actual contract, that per-chop timeouts override lumberjack defaults, without
depending on thread scheduling order.
