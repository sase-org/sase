---
plan: sdd/tales/202606/fix_flaky_input_modal_error_snapshot.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? If this is a flaky screenshot test, can you help me make it less flaky? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  
```
=========================== short test summary info ============================
FAILED tests/ace/tui/visual/test_ace_png_snapshots_inputs.py::test_input_collection_modal_error_png_snapshot - AssertionError: ACE PNG snapshot mismatch: /home/runner/work/sase/sase/tests/ace/tui/visual/snapshots/png/input_collection_modal_error_120x40.png
Changed pixels: 52945/1520532 (3.482005%); allowed: no pixel cap and 0.100000% ($SASE_VISUAL_PNG_MAX_DIFF_RATIO)
Expected PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_inputs.py__test_input_collection_modal_error_png_snapshot/input_collection_modal_error_120x40/expected.png
Actual PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_inputs.py__test_input_collection_modal_error_png_snapshot/input_collection_modal_error_120x40/actual.png
Diff PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_inputs.py__test_input_collection_modal_error_png_snapshot/input_collection_modal_error_120x40/diff.png
Summary written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_inputs.py__test_input_collection_modal_error_png_snapshot/input_collection_modal_error_120x40/summary.txt
Inspect the artifacts, then re-run with --sase-update-visual-snapshots only for intentional changes.
===== 1 failed, 13309 passed, 10 skipped, 33 warnings in 489.40s (0:08:09) =====
error: Recipe `test-cov` failed on line 219 with exit code 1
Error: Process completed with exit code 1.
```