---
plan: sdd/tales/202604/unreadable_artifact_scan.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 
```
=========================== short test summary info ============================
FAILED tests/test_core_agent_scan.py::test_unreadable_artifact_dir_is_counted - PermissionError: [Errno 13] Permission denied: '/tmp/pytest-of-runner/pytest-0/popen-gw0/test_unreadable_artifact_dir_i0/projects/myproj/artifacts/ace-run/20260427120000/done.json'
===== 1 failed, 6107 passed, 10 skipped, 14 warnings in 127.65s (0:02:07) ======
error: Recipe `test-cov` failed on line 118 with exit code 1
Error: Process completed with exit code 1.
```