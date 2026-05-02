---
plan: sdd/plans/202604/fix_interrupt_monitor_test_race.md
---
Python 3.14 tests are failing in GitHub Actions (see below). Can you help me diagnose the root cause of this issue and
fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
=========================== short test summary info ============================
FAILED tests/test_llm_provider_subprocess.py::test_start_interrupt_monitor_missing_message_field - AssertionError: Expected 'terminate' to have been called once. Called 0 times.
====== 1 failed, 4244 passed, 6 skipped, 2 warnings in 122.28s (0:02:02) =======
error: Recipe `test` failed on line 96 with exit code 1
```
