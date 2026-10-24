"""Tests for agent-hood publication after CommitWorkflow dispatch.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_commit_workflow_publication_outcomes import (
    test_agent_session_member_commit_uses_metadata_for_footer_and_publication,
    test_commit_publishes_post_commit_revision_not_pre_dispatch_head,
    test_deferred_prompt_archive_rides_the_durable_agent_publication,
    test_publication_failure_with_durable_outbox_keeps_primary_successful,
    test_publication_raising_fails_the_commit_with_a_resume_hint,
    test_publication_warning_names_drop_command_for_retired_backlog,
    test_publication_warning_names_quarantined_backlog,
    test_publication_without_target_warns_but_keeps_primary_successful,
    test_unqueueable_prompt_archive_fails_the_commit_with_a_resume_hint,
    test_unqueueable_publication_fails_the_commit_with_a_resume_hint,
)
from tests.test_commit_workflow_publication_step import (
    test_commit_publishes_every_sidecar_inline_in_order,
    test_fully_tagged_commit_and_resume_publish_each_sidecar_once,
    test_legacy_checkpoint_without_prompt_archive_publishes_commit_sha,
    test_publication_step_records_release_evidence_for_this_run,
    test_resumed_legacy_checkpoint_keeps_prompt_archive_revision_for_hood,
)

__test__ = False

__all__ = [
    "test_agent_session_member_commit_uses_metadata_for_footer_and_publication",
    "test_commit_publishes_every_sidecar_inline_in_order",
    "test_commit_publishes_post_commit_revision_not_pre_dispatch_head",
    "test_deferred_prompt_archive_rides_the_durable_agent_publication",
    "test_fully_tagged_commit_and_resume_publish_each_sidecar_once",
    "test_legacy_checkpoint_without_prompt_archive_publishes_commit_sha",
    "test_publication_failure_with_durable_outbox_keeps_primary_successful",
    "test_publication_raising_fails_the_commit_with_a_resume_hint",
    "test_publication_step_records_release_evidence_for_this_run",
    "test_publication_warning_names_drop_command_for_retired_backlog",
    "test_publication_warning_names_quarantined_backlog",
    "test_publication_without_target_warns_but_keeps_primary_successful",
    "test_resumed_legacy_checkpoint_keeps_prompt_archive_revision_for_hood",
    "test_unqueueable_prompt_archive_fails_the_commit_with_a_resume_hint",
    "test_unqueueable_publication_fails_the_commit_with_a_resume_hint",
]
