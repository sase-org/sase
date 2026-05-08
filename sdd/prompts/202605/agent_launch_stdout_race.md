---
plan: sdd/tales/202605/agent_launch_stdout_race.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
=========================== short test summary info ============================
FAILED tests/test_core_agent_launch_wire.py::test_spawn_prepared_agent_process_redirects_output_and_env - AssertionError: assert 'env-ok' in 'stderr-line\n'
====== 1 failed, 7797 passed, 8 skipped, 47 warnings in 131.44s (0:02:11) ======
error: Recipe `test-cov` failed on line 152 with exit code 1
Error: Process completed with exit code 1.
```