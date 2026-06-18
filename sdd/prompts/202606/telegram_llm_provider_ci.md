---
plan: sdd/tales/202606/telegram_llm_provider_ci.md
---
 GitHub Actions for the sase-telegram repo is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

```
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_inbound.py::TestLaunchAgent::test_success_sends_confirmation - RuntimeError: No LLM provider is available. Install a provider plugin or set llm_provider.provider explicitly.
FAILED tests/test_inbound.py::TestLaunchAgent::test_no_auto_name_prepended_when_no_name_directive - RuntimeError: No LLM provider is available. Install a provider plugin or set llm_provider.provider explicitly.
FAILED tests/test_inbound.py::TestLaunchAgent::test_no_auto_name_when_name_directive_present - RuntimeError: No LLM provider is available. Install a provider plugin or set llm_provider.provider explicitly.
FAILED tests/test_inbound.py::TestLaunchAgent::test_no_auto_name_for_repeat_prompt - RuntimeError: No LLM provider is available. Install a provider plugin or set llm_provider.provider explicitly.
FAILED tests/test_inbound.py::TestLaunchAgent::test_launch_uses_result_agent_name_without_polling_meta - RuntimeError: No LLM provider is available. Install a provider plugin or set llm_provider.provider explicitly.
FAILED tests/test_inbound.py::TestLaunchAgent::test_launch_includes_wait_keyboard - RuntimeError: No LLM provider is available. Install a provider plugin or set llm_provider.provider explicitly.
FAILED tests/test_inbound.py::TestLaunchAgent::test_launch_retry_button_replaces_existing_name_directive - RuntimeError: No LLM provider is available. Install a provider plugin or set llm_provider.provider explicitly.
FAILED tests/test_inbound.py::TestLaunchAgent::test_launch_retry_button_uses_callback_for_long_prompt - RuntimeError: No LLM provider is available. Install a provider plugin or set llm_provider.provider explicitly.
FAILED tests/test_inbound.py::TestLaunchAgent::test_launch_wait_keyboard_includes_vcs_tag - RuntimeError: No LLM provider is available. Install a provider plugin or set llm_provider.provider explicitly.
FAILED tests/test_inbound.py::TestLaunchAgent::test_launch_vcs_tag_uses_at_name_when_pr_present - RuntimeError: No LLM provider is available. Install a provider plugin or set llm_provider.provider explicitly.
FAILED tests/test_inbound.py::TestLaunchAgent::test_launch_vcs_tag_unchanged_without_pr - RuntimeError: No LLM provider is available. Install a provider plugin or set llm_provider.provider explicitly.
================= 11 failed, 322 passed, 11 warnings in 2.90s ==================
error: recipe `test` failed on line 24 with exit code 1
Error: Process completed with exit code 1.
```