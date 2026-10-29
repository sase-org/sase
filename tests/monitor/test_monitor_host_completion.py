"""Facade preserving the historic ``test_monitor_host_completion`` import path.

Host completion tests now live in :mod:`test_monitor_host_completion_eligibility`,
:mod:`test_monitor_host_completion_settle`,
:mod:`test_monitor_host_completion_receipts`, and
:mod:`test_monitor_host_completion_no_model`; this module re-exports their
public test functions so existing import paths keep working.
"""

from __future__ import annotations

# Tests live in the split modules below; keep this facade out of pytest
# collection so each test runs once while the import path keeps working.
__test__ = False

from .test_monitor_host_completion_eligibility import (
    test_unrelated_prompt_archive_commit_does_not_stale_prepared_completion,
)
from .test_monitor_host_completion_no_model import (
    test_no_model_controller_refuses_missing_declaration,
)
from .test_monitor_host_completion_receipts import (
    test_completed_receipt_does_not_rerun_commit,
    test_partial_repository_receipt_does_not_complete,
    test_production_sha_receipt_completes_without_recovery,
)
from .test_monitor_host_completion_settle import (
    test_eligible_success_invokes_no_model_finalizers_and_zero_llm,
    test_ineligible_success_launches_one_recovery_with_production_kwargs,
    test_non_complete_policy_falls_through,
    test_two_argument_recovery_callback_is_rejected,
)

__all__ = [
    "test_completed_receipt_does_not_rerun_commit",
    "test_eligible_success_invokes_no_model_finalizers_and_zero_llm",
    "test_ineligible_success_launches_one_recovery_with_production_kwargs",
    "test_no_model_controller_refuses_missing_declaration",
    "test_non_complete_policy_falls_through",
    "test_partial_repository_receipt_does_not_complete",
    "test_production_sha_receipt_completes_without_recovery",
    "test_two_argument_recovery_callback_is_rejected",
    "test_unrelated_prompt_archive_commit_does_not_stale_prepared_completion",
]
