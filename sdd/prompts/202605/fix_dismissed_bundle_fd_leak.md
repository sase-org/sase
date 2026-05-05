---
plan: sdd/tales/202605/fix_dismissed_bundle_fd_leak.md
---
 The `just test` command keeps failing with errors like those shown below. Can you help me diagnose the root
cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 

```
=============================================================================================== short test summary info ================================================================================================
FAILED tests/test_dismissed_agents.py::test_bundle_no_limit - OSError: [Errno 24] Too many open files: '/tmp/pytest-of-bryan/pytest-22/popen-gw7/test_bundle_no_limit0/bundles'
ERROR tests/test_dismissed_agents.py::test_remove_bundle_by_identity - OSError: [Errno 24] Too many open files: '/tmp/pytest-of-bryan/pytest-22/popen-gw7'
ERROR tests/test_dismissed_agents.py::test_remove_bundle_with_child_suffixes - OSError: [Errno 24] Too many open files: '/tmp/pytest-of-bryan/pytest-22/popen-gw7'
========================================================================== 1 failed, 7274 passed, 6 skipped, 11 warnings, 2 errors in 44.49s ===========================================================================
```