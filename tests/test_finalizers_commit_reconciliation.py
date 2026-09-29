"""Commit reconciliation coverage for the finalizer controller.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_finalizers_commit_reconciliation_basic import (
    test_builtin_commit_executes_declared_stitch_without_reprompt,
    test_builtin_commit_refusal_is_rejected_before_running_stitch,
    test_post_submit_cleanup_fails_without_proven_transition,
    test_stale_commit_results_do_not_prove_clean_transition,
)
from tests.test_finalizers_commit_reconciliation_checkpoint import (
    test_pending_checkpoint_refuses_foreign_agent_before_resume,
    test_pending_checkpoint_refuses_foreign_run_before_resume,
    test_pending_checkpoint_refuses_same_subject_different_body,
    test_pending_checkpoint_resumes_before_clean_acceptance,
    test_pending_checkpoint_resumes_when_only_host_footer_tags_differ,
)
from tests.test_finalizers_commit_reconciliation_retry import (
    test_prior_attempt_marker_proves_already_clean_retry,
    test_unpushed_marker_resume_failure_keeps_push_diagnostic,
    test_unpushed_marker_resumes_already_clean_retry,
)

__test__ = False

__all__ = [
    "test_builtin_commit_executes_declared_stitch_without_reprompt",
    "test_builtin_commit_refusal_is_rejected_before_running_stitch",
    "test_pending_checkpoint_refuses_foreign_agent_before_resume",
    "test_pending_checkpoint_refuses_foreign_run_before_resume",
    "test_pending_checkpoint_refuses_same_subject_different_body",
    "test_pending_checkpoint_resumes_before_clean_acceptance",
    "test_pending_checkpoint_resumes_when_only_host_footer_tags_differ",
    "test_post_submit_cleanup_fails_without_proven_transition",
    "test_prior_attempt_marker_proves_already_clean_retry",
    "test_stale_commit_results_do_not_prove_clean_transition",
    "test_unpushed_marker_resume_failure_keeps_push_diagnostic",
    "test_unpushed_marker_resumes_already_clean_retry",
]
