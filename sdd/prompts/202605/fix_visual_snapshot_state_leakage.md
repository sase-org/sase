---
plan: sdd/tales/202605/fix_visual_snapshot_state_leakage.md
---
 #resume:li.r1 GitHub Actions is still failing. Please fix this!: Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


```
(11 durations < 0.005s hidden.  Use -vv to show these durations.)
=========================== short test summary info ============================
FAILED tests/ace/tui/visual/test_ace_png_snapshots.py::test_changespec_initial_png_snapshot - AssertionError: ACE PNG snapshot mismatch: /home/runner/work/sase/sase/tests/ace/tui/visual/snapshots/png/changespec_initial_120x40.png
Changed pixels: 98960/1520532 (6.508248%); allowed <= 0 pixels and <= 0.000000%
Expected PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_changespec_initial_png_snapshot/changespec_initial_120x40/expected.png
Actual PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_changespec_initial_png_snapshot/changespec_initial_120x40/actual.png
Diff PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_changespec_initial_png_snapshot/changespec_initial_120x40/diff.png
Summary written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_changespec_initial_png_snapshot/changespec_initial_120x40/summary.txt
Inspect the artifacts, then re-run with --sase-update-visual-snapshots only for intentional changes.
FAILED tests/ace/tui/visual/test_ace_png_snapshots.py::test_changespec_selected_row_png_snapshot - AssertionError: ACE PNG snapshot mismatch: /home/runner/work/sase/sase/tests/ace/tui/visual/snapshots/png/changespec_selected_row_120x40.png
Changed pixels: 100670/1520532 (6.620709%); allowed <= 0 pixels and <= 0.000000%
Expected PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_changespec_selected_row_png_snapshot/changespec_selected_row_120x40/expected.png
Actual PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_changespec_selected_row_png_snapshot/changespec_selected_row_120x40/actual.png
Diff PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_changespec_selected_row_png_snapshot/changespec_selected_row_120x40/diff.png
Summary written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_changespec_selected_row_png_snapshot/changespec_selected_row_120x40/summary.txt
Inspect the artifacts, then re-run with --sase-update-visual-snapshots only for intentional changes.
FAILED tests/ace/tui/visual/test_ace_png_snapshots.py::test_query_edit_modal_png_snapshot - AssertionError: ACE PNG snapshot mismatch: /home/runner/work/sase/sase/tests/ace/tui/visual/snapshots/png/query_edit_modal_120x40.png
Changed pixels: 123343/1520532 (8.111832%); allowed <= 0 pixels and <= 0.000000%
Expected PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_query_edit_modal_png_snapshot/query_edit_modal_120x40/expected.png
Actual PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_query_edit_modal_png_snapshot/query_edit_modal_120x40/actual.png
Diff PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_query_edit_modal_png_snapshot/query_edit_modal_120x40/diff.png
Summary written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_query_edit_modal_png_snapshot/query_edit_modal_120x40/summary.txt
Inspect the artifacts, then re-run with --sase-update-visual-snapshots only for intentional changes.
FAILED tests/ace/tui/visual/test_ace_png_snapshots.py::test_agent_list_png_snapshot - AssertionError: ACE PNG snapshot mismatch: /home/runner/work/sase/sase/tests/ace/tui/visual/snapshots/png/agents_list_120x40.png
Changed pixels: 163448/1520532 (10.749396%); allowed <= 0 pixels and <= 0.000000%
Expected PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_agent_list_png_snapshot/agents_list_120x40/expected.png
Actual PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_agent_list_png_snapshot/agents_list_120x40/actual.png
Diff PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_agent_list_png_snapshot/agents_list_120x40/diff.png
Summary written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_agent_list_png_snapshot/agents_list_120x40/summary.txt
Inspect the artifacts, then re-run with --sase-update-visual-snapshots only for intentional changes.
FAILED tests/ace/tui/visual/test_ace_png_snapshots.py::test_agents_selected_row_png_snapshot - AssertionError: ACE PNG snapshot mismatch: /home/runner/work/sase/sase/tests/ace/tui/visual/snapshots/png/agents_selected_row_120x40.png
Changed pixels: 223078/1520532 (14.671049%); allowed <= 0 pixels and <= 0.000000%
Expected PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_agents_selected_row_png_snapshot/agents_selected_row_120x40/expected.png
Actual PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_agents_selected_row_png_snapshot/agents_selected_row_120x40/actual.png
Diff PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_agents_selected_row_png_snapshot/agents_selected_row_120x40/diff.png
Summary written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_agents_selected_row_png_snapshot/agents_selected_row_120x40/summary.txt
Inspect the artifacts, then re-run with --sase-update-visual-snapshots only for intentional changes.
FAILED tests/ace/tui/visual/test_ace_png_snapshots.py::test_agents_unread_highlight_png_snapshot - AssertionError: ACE PNG snapshot mismatch: /home/runner/work/sase/sase/tests/ace/tui/visual/snapshots/png/agents_unread_highlight_120x40.png
Changed pixels: 193313/1520532 (12.713511%); allowed <= 0 pixels and <= 0.000000%
Expected PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_agents_unread_highlight_png_snapshot/agents_unread_highlight_120x40/expected.png
Actual PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_agents_unread_highlight_png_snapshot/agents_unread_highlight_120x40/actual.png
Diff PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_agents_unread_highlight_png_snapshot/agents_unread_highlight_120x40/diff.png
Summary written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_agents_unread_highlight_png_snapshot/agents_unread_highlight_120x40/summary.txt
Inspect the artifacts, then re-run with --sase-update-visual-snapshots only for intentional changes.
FAILED tests/ace/tui/visual/test_ace_png_snapshots.py::test_axe_selected_row_png_snapshot - AssertionError: ACE PNG snapshot mismatch: /home/runner/work/sase/sase/tests/ace/tui/visual/snapshots/png/axe_selected_row_120x40.png
Changed pixels: 37216/1520532 (2.447564%); allowed <= 0 pixels and <= 0.000000%
Expected PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_axe_selected_row_png_snapshot/axe_selected_row_120x40/expected.png
Actual PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_axe_selected_row_png_snapshot/axe_selected_row_120x40/actual.png
Diff PNG written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_axe_selected_row_png_snapshot/axe_selected_row_120x40/diff.png
Summary written to: .pytest_cache/sase-visual/tests_ace_tui_visual_test_ace_png_snapshots.py__test_axe_selected_row_png_snapshot/axe_selected_row_120x40/summary.txt
Inspect the artifacts, then re-run with --sase-update-visual-snapshots only for intentional changes.
=================== 7 failed, 8 passed, 1 skipped in 37.79s ====================
error: Recipe `test-visual` failed on line 174 with exit code 1
Error: Process completed with exit code 1.
```