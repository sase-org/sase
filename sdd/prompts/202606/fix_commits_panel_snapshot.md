---
plan: sdd/tales/202606/fix_commits_panel_snapshot.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? If this is a flaky screenshot test, can you help me make it not flaky? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  
```
=========================== short test summary info ============================
FAILED tests/ace/tui/visual/test_ace_png_snapshots_agents_linked_repos.py::test_agents_commit_messages_panel_png_snapshot - AssertionError
============== 1 failed, 87 passed, 1 skipped in 91.51s (0:01:31) ==============
error: Recipe `test-visual` failed on line 205 with exit code 1
Error: Process completed with exit code 1.
```