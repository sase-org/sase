"""Dev execution pipeline: hermetic end-to-end runs plus agreement coverage.

Split facade: the tests now live in ``test_run_dev_flow``,
``test_run_dev_agreement``, ``test_run_dev_prepare``, and
``test_run_dev_render``, with shared fakes in ``_run_dev_harness``. This
module re-exports the public names so the original import path keeps
working. It collects no tests itself.
"""

from __future__ import annotations

from tests.sase_install.test_run_dev_agreement import (
    test_agreement_accepts_mixed_when_allowed,
    test_agreement_fails_on_managed_mode,
    test_agreement_fails_on_published_wheel_core,
    test_agreement_fails_on_unhealthy_reconcile_step,
    test_agreement_mixed_allowed_still_fails_on_published_wheel,
    test_agreement_mixed_without_allow_mixed_still_fails,
    test_agreement_pass_with_behind_upstream_pull_work,
    test_agreement_warns_on_fetch_error,
    test_agreement_warns_without_a_document,
    test_mixed_mode_with_pypi_plugin_passes_dev_verify,
    test_update_disagreement_fails_dev_verify,
    test_update_repair_fails_dev_verify,
    test_update_timeout_warns_only,
)
from tests.sase_install.test_run_dev_flow import (
    test_build_check_failure_blocks_before_swap,
    test_dev_dirty_core_rebuilds,
    test_dev_noop_skipped_when_core_retargeted,
    test_dev_noop_skipped_when_lsp_missing,
    test_dev_noop_skipped_when_stamp_stale,
    test_dev_noop_when_current_and_healthy,
    test_dev_run_reports_shas_in_summary,
    test_dev_run_success_end_to_end,
    test_reapply_failure_prints_restore_and_pypi_core_note,
    test_stamp_mismatch_warns_only,
)
from tests.sase_install.test_run_dev_prepare import (
    test_bindings_failure_blocks_the_install,
    test_dev_run_with_spaces_in_paths,
    test_prepare_clones_a_missing_core,
    test_stale_cargo_lsp_warns_only,
    test_sync_failure_aborts_before_swap,
    test_verify_failure_blocks_the_install,
)
from tests.sase_install.test_run_dev_render import (
    test_dev_dry_run_json_lists_reapply_command,
    test_dev_json_reports_success_with_reapply_command,
    test_ephemeral_checkout_refuses_dev_run,
    test_render_dev_noop_names_shas,
    test_render_dev_success_names_shas_and_pin,
)

__test__ = False

__all__ = [
    "test_agreement_accepts_mixed_when_allowed",
    "test_agreement_fails_on_managed_mode",
    "test_agreement_fails_on_published_wheel_core",
    "test_agreement_fails_on_unhealthy_reconcile_step",
    "test_agreement_mixed_allowed_still_fails_on_published_wheel",
    "test_agreement_mixed_without_allow_mixed_still_fails",
    "test_agreement_pass_with_behind_upstream_pull_work",
    "test_agreement_warns_on_fetch_error",
    "test_agreement_warns_without_a_document",
    "test_bindings_failure_blocks_the_install",
    "test_build_check_failure_blocks_before_swap",
    "test_dev_dirty_core_rebuilds",
    "test_dev_dry_run_json_lists_reapply_command",
    "test_dev_json_reports_success_with_reapply_command",
    "test_dev_noop_skipped_when_core_retargeted",
    "test_dev_noop_skipped_when_lsp_missing",
    "test_dev_noop_skipped_when_stamp_stale",
    "test_dev_noop_when_current_and_healthy",
    "test_dev_run_reports_shas_in_summary",
    "test_dev_run_success_end_to_end",
    "test_dev_run_with_spaces_in_paths",
    "test_ephemeral_checkout_refuses_dev_run",
    "test_mixed_mode_with_pypi_plugin_passes_dev_verify",
    "test_prepare_clones_a_missing_core",
    "test_reapply_failure_prints_restore_and_pypi_core_note",
    "test_render_dev_noop_names_shas",
    "test_render_dev_success_names_shas_and_pin",
    "test_stale_cargo_lsp_warns_only",
    "test_stamp_mismatch_warns_only",
    "test_sync_failure_aborts_before_swap",
    "test_update_disagreement_fails_dev_verify",
    "test_update_repair_fails_dev_verify",
    "test_update_timeout_warns_only",
    "test_verify_failure_blocks_the_install",
]
