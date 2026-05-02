---
plan: sdd/tales/202604/fix_ci_file_not_found_sase.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


```
=========================== short test summary info ============================
FAILED tests/test_pr_tags.py::TestAppendPrTags::test_tags_appended_to_message - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_pr_tags.py::TestAppendPrTags::test_tags_flow_into_pr_body - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_pr_tags.py::TestAppendPrTags::test_bug_tag_from_env - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_pr_tags.py::TestAppendPrTags::test_bug_tag_from_payload - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_pr_tags.py::TestAppendPrTags::test_bug_tag_payload_overrides_env - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_pr_tags.py::TestAppendPrTags::test_bug_tag_zero_skipped - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_pr_tags.py::TestAppendPrTags::test_bug_tag_unset_skipped - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_pr_tags.py::TestAppendPrTags::test_bug_tag_alongside_config_tags - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_pr_tags.py::TestAppendPrTags::test_bug_tag_env_overrides_static_config - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_pr_tags.py::TestAppendPrTags::test_no_tags_no_change - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_pr_tags.py::TestInheritParentPrTags::test_parent_tags_inherited - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_pr_tags.py::TestInheritParentPrTags::test_config_tags_override_parent - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_pr_tags.py::TestInheritParentPrTags::test_bug_tag_overrides_parent - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_pr_tags.py::TestInheritParentPrTags::test_graceful_noop_when_no_parent_tags - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_commit_workflow_changespec.py::TestCommitWorkflowChangeSpec::test_creates_changespec_on_pr_success - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_commit_workflow_changespec.py::TestCommitWorkflowChangeSpec::test_uses_checkout_target_from_payload - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_commit_workflow_changespec.py::TestCommitWorkflowChangeSpec::test_skips_changespec_when_no_project - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_commit_workflow_changespec.py::TestCommitWorkflowChangeSpec::test_no_changespec_for_create_commit - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_commit_workflow_changespec.py::TestCommitWorkflowBugId::test_bug_id_propagated_to_changespec - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_commit_workflow_changespec.py::TestCommitWorkflowBugId::test_bug_id_from_payload - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_commit_workflow_changespec.py::TestCommitWorkflowBugId::test_bug_id_payload_overrides_env - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_commit_workflow_changespec.py::TestCommitWorkflowBugId::test_bug_id_not_set_passes_none - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_commit_workflow_changespec.py::TestCommitWorkflowBugId::test_bug_id_zero_passes_none - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_commit_workflow_changespec.py::TestCommitWorkflowChangeSpecErrorHandling::test_changespec_exception_does_not_fail_workflow - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
FAILED tests/test_commit_workflow_changespec.py::TestCommitWorkflowChangeSpecErrorHandling::test_name_present_for_pull_request_passes_validation - FileNotFoundError: [Errno 2] No such file or directory: 'sase'
======= 25 failed, 4460 passed, 7 skipped, 1 warning in 89.84s (0:01:29) =======
``` 