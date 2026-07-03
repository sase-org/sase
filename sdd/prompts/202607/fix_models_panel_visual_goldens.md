---
plan: sdd/tales/202607/fix_models_panel_visual_goldens.md
---
 #fork:s.w1 Can you help me fix the pre-existing screenshot test failures that the previous agent ran into? Here is what I am seeing in GitHub Actions:
```
=========================== short test summary info ============================
FAILED tests/ace/tui/visual/test_ace_png_snapshots_models_panel.py::test_models_panel_default_png_snapshot - AssertionError: ACE PNG snapshot mismatch: /home/runner/work/sase/sase/tests/ace/tui/visual/snapshots/png/models_panel_default_120x40.png
Changed pixels: 197690/1520532 (13.001371%); allowed: no pixel cap and 3.000000% (explicit)
Expected PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_models_panel.py__test_models_panel_default_png_snapshot/models_panel_default_120x40/expected.png
Actual PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_models_panel.py__test_models_panel_default_png_snapshot/models_panel_default_120x40/actual.png
Diff PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_models_panel.py__test_models_panel_default_png_snapshot/models_panel_default_120x40/diff.png
Summary written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_models_panel.py__test_models_panel_default_png_snapshot/models_panel_default_120x40/summary.txt
Inspect the artifacts, then re-run with --sase-update-visual-snapshots only for intentional changes.
FAILED tests/ace/tui/visual/test_ace_png_snapshots_models_panel.py::test_models_panel_overrides_png_snapshot - AssertionError: ACE PNG snapshot mismatch: /home/runner/work/sase/sase/tests/ace/tui/visual/snapshots/png/models_panel_overrides_120x40.png
Changed pixels: 200341/1520532 (13.175717%); allowed: no pixel cap and 3.000000% (explicit)
Expected PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_models_panel.py__test_models_panel_overrides_png_snapshot/models_panel_overrides_120x40/expected.png
Actual PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_models_panel.py__test_models_panel_overrides_png_snapshot/models_panel_overrides_120x40/actual.png
Diff PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_models_panel.py__test_models_panel_overrides_png_snapshot/models_panel_overrides_120x40/diff.png
Summary written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_models_panel.py__test_models_panel_overrides_png_snapshot/models_panel_overrides_120x40/summary.txt
Inspect the artifacts, then re-run with --sase-update-visual-snapshots only for intentional changes.
FAILED tests/ace/tui/visual/test_ace_png_snapshots_models_panel_edit.py::test_models_panel_edit_preview_png_snapshot - AssertionError: ACE PNG snapshot mismatch: /home/runner/work/sase/sase/tests/ace/tui/visual/snapshots/png/models_panel_edit_preview_120x40.png
Changed pixels: 164550/1520532 (10.821870%); allowed: no pixel cap and 3.000000% (explicit)
Expected PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_models_panel_edit.py__test_models_panel_edit_preview_png_snapshot/models_panel_edit_preview_120x40/expected.png
Actual PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_models_panel_edit.py__test_models_panel_edit_preview_png_snapshot/models_panel_edit_preview_120x40/actual.png
Diff PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_models_panel_edit.py__test_models_panel_edit_preview_png_snapshot/models_panel_edit_preview_120x40/diff.png
Summary written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots_models_panel_edit.py__test_models_panel_edit_preview_png_snapshot/models_panel_edit_preview_120x40/summary.txt
Inspect the artifacts, then re-run with --sase-update-visual-snapshots only for intentional changes.
============= 3 failed, 129 passed, 1 skipped in 284.83s (0:04:44) =============
error: Recipe `test-visual` failed on line 206 with exit code 1
Error: Process completed with exit code 1.
```

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 