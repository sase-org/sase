---
plan: sdd/tales/202607/fix_axe_daemon_stop_sigkill_flake.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? If the issue is a flakey test, fix the flake (i.e. make the test more deterministic). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 
```
=========================== short test summary info ============================
FAILED tests/test_axe_process.py::test_stop_axe_daemon_targets_inherited_lock_daemon - AssertionError: assert -9 == 0
 +  where -9 = wait(timeout=1.0)
 +    where wait = <Popen: returncode: -9 args: ['/home/runner/work/sase/sase/.venv/bin/python'...>.wait
===== 1 failed, 15022 passed, 12 skipped, 42 warnings in 776.40s (0:12:56) =====
error: Recipe `test-cov` failed on line 220 with exit code 1
Error: Process completed with exit code 1.
```