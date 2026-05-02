---
create_time: 2026-04-24 15:53:52
status: wip
prompt: sdd/prompts/202604/fix_ace_testing_tab_bar_worker_race.md
---
# Fix Flaky `test_expect_state_passes` Worker Failure (`#tab-bar` NoMatches)

## Problem Statement

GitHub Actions intermittently fails `tests/test_ace_testing.py::test_expect_state_passes` with:

- `textual.worker.WorkerFailed`
- inner exception: `NoMatches("No nodes match '#tab-bar' on Screen(id='_default')")`

The failure occurs in a background worker path, not in the test assertion itself.

## Root Cause Hypothesis

`AceApp` schedules post-mount background refresh workers. During fast test teardown (or other transient lifecycle
windows), worker code in `AgentLoadingMixin._apply_loaded_agents()` unconditionally executes:

- `self.query_one("#tab-bar", TabBar)`
- `tab_bar.update_agents_count(...)`

Unlike other tab-bar update paths in the codebase, this call is not wrapped in a defensive guard. If the screen has
already transitioned to Textual's default screen during shutdown, `#tab-bar` is absent and `NoMatches` escapes, causing
the worker to fail and flake the test run.

## Design Goals

1. Eliminate lifecycle-race worker crashes in the agent async loader.
2. Keep normal tab-count updates unchanged when widgets exist.
3. Match existing defensive style used in other tab-bar update helpers.
4. Keep the fix narrow and low-risk.

## Proposed Implementation

1. Update `src/sase/ace/tui/actions/agents/_loading.py` inside `_apply_loaded_agents()`:
   - wrap the tab bar lookup/update block in a `try/except Exception` guard.
   - no-op when widgets are unavailable (shutdown/unmounted timing).
2. Add a brief comment explaining this guard is for teardown/lifecycle races in async worker completion.
3. Do not change count computation logic or refresh behavior.

## Validation Strategy

1. Run the targeted test file:
   - `just test tests/test_ace_testing.py -vv`
2. Run full CI-equivalent suite:
   - `just test-cov`
3. Run repo quality gate required by project memory:
   - `just check`

## Risks and Mitigations

- Risk: catching broad exceptions could hide real bugs.
  - Mitigation: scope the guard tightly to tab-bar lookup/update only; keep all upstream logic intact.
- Risk: counts may skip one update during teardown.
  - Mitigation: acceptable because app is shutting down and no UI interaction remains.

## Expected Outcome

`test_expect_state_passes` no longer flakes due to background worker `NoMatches('#tab-bar')`, and CI remains stable
without behavioral changes in normal runtime UI updates.
