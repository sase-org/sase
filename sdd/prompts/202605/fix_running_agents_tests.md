---
plan: sdd/tales/202605/fix_running_agents_tests.md
---
 Can you help me fix our test suite (i.e. the `just test` command)? See the failure output below for context. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
========================================================================================== short test summary info ==========================================================================================
FAILED tests/test_running_agents_snapshot.py::test_list_running_agents_filters_done_and_dead - AssertionError: assert {'20260427140500'} == {'20260427100...260427140500'}
FAILED tests/test_running_agents_snapshot.py::test_list_running_agents_reports_waiting_marker - KeyError: '20260427110000'
FAILED tests/test_running_agents_snapshot.py::test_list_all_agents_includes_done_and_failed - AssertionError: assert {'20260427120...260427140500'} == {'20260427100...260427140500'}
========================================================================= 3 failed, 10211 passed, 6 skipped, 12 warnings in 43.09s ==========================================================================
error: recipe `test` failed on line 189 with exit code 1
```