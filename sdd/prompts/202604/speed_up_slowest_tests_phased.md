---
plan: sdd/plans/202604/speed_up_slowest_tests_phased.md
---
 I've listed all of the slowest tests in our test suite below. Can you help me make these faster? This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

  

```
================================================================================================================ slowest 20 durations ================================================================================================================
11.07s call     tests/test_commit_workflow_changespec.py::TestCommitWorkflowChangeSpec::test_creates_changespec_on_pr_success
7.88s call     tests/test_commit_workflow_checkpointing.py::test_run_failure_without_conflict_deletes_checkpoint
7.67s call     tests/test_keymaps_e2e.py::test_remapped_navigation_key
7.63s call     tests/test_ace_tui_app.py::test_query_edit_modal_invalid_query
7.45s call     tests/test_commit_workflow_checkpointing.py::test_run_detects_conflict_and_returns_conflict_code
6.94s call     tests/test_pr_tags.py::TestAppendPrTags::test_bug_tag_from_payload
6.62s call     tests/test_ace_tui_widgets.py::test_tab_bar_integration_tab_key
6.44s call     tests/test_project_pr_prefix.py::TestApplyProjectPrPrefix::test_no_prefix_when_disabled
5.96s call     tests/test_commit_workflow_checkpointing.py::test_dispatch_step_recorded_after_success
5.76s call     tests/test_commit_workflow_dispatch.py::TestCommitWorkflowValidation::test_missing_message_ok_for_pull_request
5.61s call     tests/test_ace_testing.py::test_ace_page_press
5.58s call     tests/test_xprompt_catalog.py::test_build_integration_produces_pdf
5.49s call     tests/test_commit_workflow_changespec.py::TestCommitWorkflowBugId::test_bug_id_from_payload
5.45s call     tests/test_project_pr_prefix.py::TestApplyProjectPrPrefix::test_no_prefix_when_no_project
5.26s call     tests/test_ace_tui_app.py::test_navigation_next_key
5.20s call     tests/test_keymaps_e2e.py::test_default_keys_still_work
4.82s call     tests/test_project_pr_prefix.py::TestApplyProjectPrPrefix::test_sets_prefix_when_enabled
4.47s call     tests/test_pr_tags.py::TestAppendPrTags::test_bug_tag_from_env
4.39s call     tests/test_ace_tui_app.py::test_unmark_navigates_to_next_spec
4.19s call     tests/test_commit_workflow_checkpointing.py::test_run_success_deletes_checkpoint
=================================================================================================== 4491 passed, 6 skipped, 65 warnings in 55.57s ====================================================================================================
```