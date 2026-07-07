---
plan: sdd/tales/202607/fix_marked_install_snapshot_flake.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  
```
=========================== short test summary info ============================
FAILED tests/ace/tui/visual/test_ace_png_snapshots_config_center_plugin_actions.py::test_config_center_plugins_marked_install_png_snapshot - AssertionError: ACE PNG snapshot mismatch: /home/runner/work/sase/sase/tests/ace/tui/visual/snapshots/png/config_center_plugins_marked_install_120x40.png
Changed pixels: 36229/1520532 (2.382653%); allowed: no pixel cap and 1.000000% ($SASE_VISUAL_PNG_MAX_DIFF_RATIO)
Expected PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_config_center_plugin_actions.py__test_config_center_plugins_marked_install_png_snapshot/config_center_plugins_marked_install_120x40/expected.png
Actual PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_config_center_plugin_actions.py__test_config_center_plugins_marked_install_png_snapshot/config_center_plugins_marked_install_120x40/actual.png
Diff PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_config_center_plugin_actions.py__test_config_center_plugins_marked_install_png_snapshot/config_center_plugins_marked_install_120x40/diff.png
Summary written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_config_center_plugin_actions.py__test_config_center_plugins_marked_install_png_snapshot/config_center_plugins_marked_install_120x40/summary.txt
Inspect the artifacts, then re-run with --sase-update-visual-snapshots only for intentional changes.
==== 1 failed, 15570 passed, 13 skipped, 70 warnings in 1689.50s (0:28:09) =====
error: Recipe `test-cov` failed on line 227 with exit code 1
Error: Process completed with exit code 1.
```