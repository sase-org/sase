---
plan: sdd/plans/202604/fix_keymaps_e2e_flake.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
=========================== short test summary info ============================
FAILED tests/test_keymaps_e2e.py::test_default_keys_still_work - AssertionError: expect_state('idx', 1) timed out after 2.0s — last value was 0
============ 1 failed, 5325 passed, 8 skipped in 178.75s (0:02:58) =============
error: Recipe `test-cov` failed on line 113 with exit code 1
Error: Process completed with exit code 1.
```