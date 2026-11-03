"""Facade preserving the historic ``test_monitor_host_completion_controller`` import path.

The real-controller host completion tests now live in
:mod:`test_monitor_host_completion_controller_success` and
:mod:`test_monitor_host_completion_controller_recovery`; this module re-exports
their public test functions so existing import paths keep working. Shared
builders live in :mod:`_host_completion_controller`.
"""

from __future__ import annotations

# Tests live in the split modules below; keep this facade out of pytest
# collection so each test runs once while the import path keeps working.
__test__ = False

from .test_monitor_host_completion_controller_recovery import (
    test_stale_or_missing_checks_use_one_recovery,
    test_tree_drift_after_finalizers_uses_one_recovery,
    test_two_repository_partial_crash_retains_receipts_and_does_not_complete,
    test_unsupported_finalizer_uses_one_recovery,
)
from .test_monitor_host_completion_controller_success import (
    test_bead_action_is_required_when_context_has_assigned_bead,
    test_finalizer_process_binding_preserves_existing_nonce,
    test_real_controller_success_uses_zero_model_calls,
    test_real_declaration_submit_is_not_stubbed_on_success_path,
)

__all__ = [
    "test_bead_action_is_required_when_context_has_assigned_bead",
    "test_finalizer_process_binding_preserves_existing_nonce",
    "test_real_controller_success_uses_zero_model_calls",
    "test_real_declaration_submit_is_not_stubbed_on_success_path",
    "test_stale_or_missing_checks_use_one_recovery",
    "test_tree_drift_after_finalizers_uses_one_recovery",
    "test_two_repository_partial_crash_retains_receipts_and_does_not_complete",
    "test_unsupported_finalizer_uses_one_recovery",
]
