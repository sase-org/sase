---
plan: sdd/tales/202606/reserved_jinja_globals.md
---
 The `just test` command just failed (see the output below). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 
```
============================================================================= short test summary info ==============================================================================
FAILED tests/ace/tui/widgets/test_local_xprompt_conversion.py::test_infer_known_globals_are_not_inputs - AssertionError: assert [InputArg(nam...ription=None)] == []
FAILED tests/ace/tui/widgets/test_prompt_local_xprompt_convert.py::test_gx_does_not_infer_known_globals_as_inputs - AssertionError: assert [InputArg(nam...ription=None)] == []
======================================================== 2 failed, 14432 passed, 6 skipped, 9 warnings in 67.51s (0:01:07) =========================================================
error: recipe `test` failed on line 193 with exit code 1
```