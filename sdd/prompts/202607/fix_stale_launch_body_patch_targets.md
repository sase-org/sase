---
plan: sdd/tales/202607/fix_stale_launch_body_patch_targets.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 
```
=========================== short test summary info ============================
FAILED tests/ace/tui/test_prompt_stack_launch_integration.py::test_whole_stack_submit_routes_manual_multi_prompt_to_multi_prompt_launch - AttributeError: <module 'sase.ace.tui.actions.agent_workflow._launch_body' from '/home/runner/work/sase/sase/src/sase/ace/tui/actions/agent_workflow/_launch_body.py'> does not have the attribute 'record_prompt_file_references'
FAILED tests/ace/tui/test_prompt_stack_launch_integration.py::test_whole_stack_submit_with_multi_agent_xprompt_preserves_invocation - AttributeError: <module 'sase.ace.tui.actions.agent_workflow._launch_body' from '/home/runner/work/sase/sase/src/sase/ace/tui/actions/agent_workflow/_launch_body.py'> does not have the attribute 'record_prompt_file_references'
===== 2 failed, 15014 passed, 12 skipped, 69 warnings in 595.87s (0:09:55) =====
error: Recipe `test-cov` failed on line 220 with exit code 1
Error: Process completed with exit code 1.
```