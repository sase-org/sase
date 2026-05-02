---
plan: sdd/tales/202604/fix_changespec_norow_norefresh_flake.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
=========================== short test summary info ============================
FAILED tests/test_ace_tui_app.py::test_navigation_next_key - textual.css.query.NoMatches: No nodes match '#list-panel' on Screen(id='_default')
====== 1 failed, 5287 passed, 8 skipped, 14 warnings in 127.09s (0:02:07) ======
error: Recipe `test-cov` failed on line 113 with exit code 1
Error: Process completed with exit code 1.
```