---
plan: sdd/tales/202606/fix_axe_daemon_sigterm_handler_race.md
---
 GitHub Actions is failing with the below error. It looks like this is some kind of timeout. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 
```
=========================== short test summary info ============================
FAILED tests/ace/tui/visual/test_ace_png_snapshots_agents_linked_repos.py::test_agents_commit_messages_panel_png_snapshot - AssertionError: Timed out waiting for commit delta summary
===== 1 failed, 14847 passed, 12 skipped, 8 warnings in 766.29s (0:12:46) ======
error: Recipe `test-cov` failed on line 220 with exit code 1
Error: Process completed with exit code 1.
```