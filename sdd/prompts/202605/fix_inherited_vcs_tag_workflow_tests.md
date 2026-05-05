---
plan: sdd/tales/202605/fix_inherited_vcs_tag_workflow_tests.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
=========================== short test summary info ============================
FAILED tests/test_workflow_executor.py::TestShouldHitl::test_inherited_vcs_tag_prefixes_bare_prompt_step - AssertionError: assert '#gh:sase Fix it' == '#gh:sase Fix it\n'
  
  - #gh:sase Fix it
  ?                -
  + #gh:sase Fix it
FAILED tests/test_workflow_executor.py::TestShouldHitl::test_inherited_vcs_tag_preserves_directives_and_segments - sase.xprompt.workflow_models.WorkflowExecutionError: Step 's1' failed: Bare '%wait' directive found but no previously named agent exists
FAILED tests/test_workflow_executor.py::TestShouldHitl::test_inherited_vcs_tag_does_not_override_explicit_step_ref - AssertionError: assert '#git:other Fix it' == '#git:other Fix it\n'
  
  - #git:other Fix it
  ?                  -
  + #git:other Fix it
====== 3 failed, 7287 passed, 8 skipped, 34 warnings in 121.66s (0:02:01) ======
error: Recipe `test-cov` failed on line 150 with exit code 1
Error: Process completed with exit code 1.
```