---
create_time: 2026-05-01 18:01:22
status: done
prompt: sdd/prompts/202605/fix_ci_python_sleep_mock.md
---
# Plan: Fix CI Python Sleep Mock Flake

## Context

Recent GitHub Actions CI runs on `master` show Python test failures in the matrix:

- `25234828875` (`2026-05-01T21:54:28Z`, commit `3ff4b2ab`) failed in `test (3.13)`.
- `25234739559` (`2026-05-01T21:51:43Z`, commit `fa64587d`) failed in `test (3.12)`.
- The newest run observed during investigation, `25234936935` (`f2a8e5f2`), was still in progress when queried.

The failing test in run `25234828875` is:

`tests/test_multi_prompt_launcher_xprompts_models.py::test_launch_multi_prompt_model_shorthand_uses_local_xprompt_for_naming`

The failure is:

`AssertionError: Expected 'sleep' to not have been called. Called 2261 times. Calls: [call(0.5), ...]`

`act -l` confirms the CI workflow has the expected `test` matrix jobs for Python `3.12`, `3.13`, and `3.14`.
`act -n -j test -W .github/workflows/ci.yml` confirms the local matrix shape, but the installed `act` is version
`0.2.25` and cannot dry-run current `actions/checkout@v4` because it rejects `node20` actions. Therefore, remote run
history/logs must be queried with `gh`, while `act` is useful only for local workflow/job inspection unless upgraded.

## Diagnosis

The failing tests patch `sase.agent.multi_prompt_launcher.time.sleep` and then assert the mock was not called.

`src/sase/agent/multi_prompt_launcher.py` imports the whole stdlib `time` module:

```python
import time
```

Patching `sase.agent.multi_prompt_launcher.time.sleep` mutates the shared `time` module object, so the patch can observe
or intercept unrelated `time.sleep(...)` calls from other code running in the same Python process. That is especially
risky with tests that launch background threads or leave polling loops alive. The failing CI log shows many `sleep(0.5)`
calls, which matches polling-style code rather than the specific tested launch path.

The production launch code already avoids the legacy naming poll for the tested model-fanout path, so this appears to be
a test isolation bug, not a product behavior regression.

## Implementation Plan

1. Keep the production behavior unchanged unless local reproduction shows otherwise.

2. Narrow the affected tests so they do not patch the shared stdlib `time.sleep` function just to prove that the
   multi-prompt path avoided naming waits. The existing `_wait_for_agent_naming` mock and `create_artifacts_directory`
   call-count assertions already prove the path avoided the code that sleeps.

3. Remove the unnecessary `time.sleep` patch and `mock_sleep.assert_not_called()` assertions from tests that only need
   to assert no legacy naming wait occurred:
   - `tests/test_multi_prompt_launcher_launch.py`
   - `tests/test_multi_prompt_launcher_xprompts_models.py`

4. Preserve direct coverage of `_wait_for_agent_naming` in `tests/test_multi_prompt_launcher_naming.py`, where real
   sleeping is part of the function under test and no global mock is needed.

5. Run targeted tests first:

```bash
just install
just test tests/test_multi_prompt_launcher_launch.py tests/test_multi_prompt_launcher_xprompts_models.py tests/test_multi_prompt_launcher_naming.py
```

6. Run the repo-required verification after changes:

```bash
just check
```

7. Re-query the newest GitHub Actions run after the local fix to confirm whether the same failure is still present on
   current `master` or if the failure was already superseded.

## Risk

This is a low-risk test-only fix. The main risk is removing an assertion that was meant to guard against reintroducing a
sleeping timestamp allocation path. That behavior remains covered indirectly by asserting no naming wait/artifact poll
is used and by checking timestamp allocation outputs. If stronger coverage is needed later, add a production-local sleep
adapter and patch that adapter rather than patching the shared stdlib module.
