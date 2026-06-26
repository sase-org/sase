---
plan: sdd/tales/202606/jinja_completion_panel_teardown_guard.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? If this is just a flaky screen shot test, can you fix the flakiness? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  
```
=========================== short test summary info ============================
FAILED tests/ace/tui/widgets/test_prompt_jinja_pair_editing.py::test_forward_delete_padding_strips_both_boundary_spaces - textual.css.query.NoMatches: No nodes match '#prompt-completion' on PromptInputBar(classes='feedback-mode')
===== 1 failed, 14144 passed, 10 skipped, 37 warnings in 376.75s (0:06:16) =====
error: Recipe `test-cov` failed on line 220 with exit code 1
Error: Process completed with exit code 1.
```