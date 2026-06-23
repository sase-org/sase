---
plan: sdd/tales/202606/agy_provider_test_isolation.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

```
=========================== short test summary info ============================
FAILED tests/llm_provider/test_agy_provider_core.py::test_agy_provider_command_construction - AssertionError: assert '/tmp/pytest-...g_in_standal0' == '/home/runner/work/sase/sase'
  
  - /home/runner/work/sase/sase
  + /tmp/pytest-of-runner/pytest-0/popen-gw3/test_chdir_handling_in_standal0
===== 1 failed, 13164 passed, 10 skipped, 34 warnings in 358.83s (0:05:58) =====
error: Recipe `test-cov` failed on line 219 with exit code 1
Error: Process completed with exit code 1.
```