---
plan: sdd/tales/202606/agy_workspace_dir_leak.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  
```
=========================== short test summary info ============================
FAILED tests/llm_provider/test_agy_trajectory.py::test_agy_provider_extracts_tool_calls_from_trajectory_db - FileNotFoundError: Unable to launch Antigravity CLI executable '/tmp/pytest-of-runner/pytest-0/popen-gw3/test_agy_provider_extracts_too0/agy'. Set SASE_AGY_PATH to the Antigravity (`agy`) binary or ensure 'agy' is discoverable on PATH.
FAILED tests/llm_provider/test_agy_trajectory.py::test_agy_provider_trajectory_failure_is_best_effort - FileNotFoundError: Unable to launch Antigravity CLI executable '/tmp/pytest-of-runner/pytest-0/popen-gw3/test_agy_provider_trajectory_f0/agy'. Set SASE_AGY_PATH to the Antigravity (`agy`) binary or ensure 'agy' is discoverable on PATH.
===== 2 failed, 13180 passed, 10 skipped, 26 warnings in 363.92s (0:06:03) =====
```