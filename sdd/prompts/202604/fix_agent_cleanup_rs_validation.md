---
plan: sdd/plans/202604/fix_agent_cleanup_rs_validation.md
---
 Can you help me fix the below test failure (output from the `just test` command)? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


```
=============================================================================================== short test summary info ================================================================================================
FAILED tests/test_core_facade/test_agent_cleanup_execution.py::test_release_workspace_content_helper_matches_running_field_semantics - assert None is not None
FAILED tests/test_core_facade/test_agent_cleanup_execution.py::test_rust_kill_marking_matches_python_helpers - AssertionError: assert None == [HookEntry(command='pytest', status_lines=[HookStatusLine(commit_entry_num='1', timestamp='20260430010203', status='RUNNING', duration=None, suffix='agent-123-20260430010203', suff...
=============================================================================== 2 failed, 6571 passed, 14 skipped, 74 warnings in 38.79s ===============================================================================
```