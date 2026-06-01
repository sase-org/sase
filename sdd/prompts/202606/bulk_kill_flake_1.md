---
plan: sdd/tales/202606/bulk_kill_flake_1.md
---
 I think we have a flakey test (see the `just test` command's output below). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.

```
========================================================================================== short test summary info ==========================================================================================
FAILED tests/test_agent_kill_bulk.py::test_do_bulk_kill_agents_refreshes_and_schedules_once - assert [111, 222, 222, 111] == [111, 222]
==================================================================== 1 failed, 10183 passed, 6 skipped, 32 warnings in 99.00s (0:01:39) =====================================================================
error: recipe `test-cov` failed on line 216 with exit code 1
```