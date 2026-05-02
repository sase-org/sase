---
plan: sdd/tales/202604/lumberjack_timeout_test_flake.md
---
 `just test` just failed (see output below). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 
```
============================================================================================================== short test summary info ===============================================================================================================
FAILED tests/test_axe_lumberjack.py::test_per_chop_timeout_overrides_lumberjack_default - assert 30 == 10
============================================================================================== 1 failed, 5524 passed, 6 skipped, 65 warnings in 49.33s ===============================================================================================
```