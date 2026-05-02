---
plan: sdd/plans/202604/fix_debounced_detail_shutdown_race.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 
```
=========================== short test summary info ============================
FAILED tests/test_ace_tui_app.py::test_query_edit_modal_invalid_query - textual.css.query.NoMatches: No nodes match '#agent-detail-panel' on Screen(id='_default')
============ 1 failed, 4660 passed, 8 skipped in 114.14s (0:01:54) =============
error: Recipe `test-cov` failed on line 113 with exit code 1
```