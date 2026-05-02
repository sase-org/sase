---
plan: sdd/plans/202604/fix_ace_testing_tab_bar_worker_race.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 

```
=========================== short test summary info ============================
FAILED tests/test_ace_testing.py::test_expect_state_passes - textual.worker.WorkerFailed: Worker raised exception: NoMatches("No nodes match '#tab-bar' on Screen(id='_default')")
======= 1 failed, 4576 passed, 6 skipped, 1 warning in 109.99s (0:01:49) =======
error: Recipe `test-cov` failed on line 113 with exit code 1
```