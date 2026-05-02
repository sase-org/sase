---
plan: sdd/tales/202604/fix_ace_worker_shutdown_race.md
---
 Can you help me fix the below `just test` failure? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
============================================================================================================== short test summary info ===============================================================================================================
FAILED tests/test_ace_tui_app.py::test_query_edit_modal_invalid_query - textual.worker.WorkerFailed: Worker raised exception: NoMatches("No nodes match '#agent-list-panel' on Screen(id='_default')")
============================================================================================== 1 failed, 4638 passed, 6 skipped, 65 warnings in 49.50s ===============================================================================================
error: Recipe `test` failed on line 96 with exit code 1

```