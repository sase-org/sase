---
plan: sdd/plans/202604/github_actions_llm_override_ci.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
=========================== short test summary info ============================
FAILED tests/llm_provider/test_temporary_override.py::test_set_unknown_bare_model_falls_back_to_default_provider - AssertionError: assert 'gemini' == 'claude'
  
  - claude
  + gemini
FAILED tests/test_temporary_llm_override_phase5.py::test_agent_meta_after_clear_uses_default_provider - AssertionError: assert 'gemini' == 'claude'
  
  - claude
  + gemini
FAILED tests/llm_provider/test_temporary_override_phase2.py::test_get_default_provider_name_falls_through_when_no_override - AssertionError: assert 'gemini' == 'claude'
  
  - claude
  + gemini
FAILED tests/llm_provider/test_temporary_override_phase2.py::test_get_default_provider_name_ignores_expired_override - AssertionError: assert 'gemini' == 'claude'
  
  - claude
  + gemini
====== 4 failed, 6510 passed, 8 skipped, 27 warnings in 114.54s (0:01:54) ======
error: Recipe `test-cov` failed on line 140 with exit code 1
Error: Process completed with exit code 1.
```