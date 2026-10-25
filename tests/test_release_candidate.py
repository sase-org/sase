"""Seal/verify/observe/evaluate tests for the release_candidate tool.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

import pytest

from tests.test_release_candidate_inventory import (
    test_evidence_binding_mismatches_are_red,
)
from tests.test_release_candidate_inventory import (
    test_failed_reporting_step_cannot_accept_a_partial_pytest_report,
)
from tests.test_release_candidate_inventory import (
    test_inventory_duplicate_json_keys_fail_closed,
)
from tests.test_release_candidate_inventory import (
    test_inventory_invalid_contracts_fail_closed,
)
from tests.test_release_candidate_inventory import (
    test_job_bundle_identity_mismatches_are_red,
)
from tests.test_release_candidate_inventory import (
    test_lint_binding_diagnostics_keep_missing_names,
)
from tests.test_release_candidate_inventory import (
    test_missing_matrix_entry_and_duplicate_job_mapping_are_red,
)
from tests.test_release_candidate_inventory import (
    test_n1_inventory_is_single_versioned_classification,
)
from tests.test_release_candidate_inventory import (
    test_qualification_evaluator_loads_its_focused_helpers,
)
from tests.test_release_candidate_inventory import (
    test_qualification_pass_archives_bound_evidence_and_advisories,
)
from tests.test_release_candidate_inventory import (
    test_required_job_red_classes_are_typed,
)
from tests.test_release_candidate_rerun import (
    test_attempt_two_cannot_hide_first_attempt_harness_failure,
)
from tests.test_release_candidate_rerun import (
    test_bare_pass_observation_is_not_qualification_evidence,
)
from tests.test_release_candidate_rerun import (
    test_changed_carried_forward_success_is_ambiguous_and_red,
)
from tests.test_release_candidate_rerun import (
    test_duplicate_or_unreadable_evidence_file_fails_closed,
)
from tests.test_release_candidate_rerun import (
    test_first_test_only_red_is_rerun_eligible_and_retry_preserves_history,
)
from tests.test_release_candidate_rerun import (
    test_old_generation_evidence_cannot_qualify_new_candidate,
)
from tests.test_release_candidate_rerun import test_old_pass_never_wins_over_a_newer_red
from tests.test_release_candidate_rerun import (
    test_qualify_cli_persists_red_observation_before_refusal,
)
from tests.test_release_candidate_rerun import test_second_red_is_not_rerun_eligible
from tests.test_release_candidate_rerun import (
    test_successful_job_cannot_be_rerun_on_a_failed_only_attempt,
)
from tests.test_release_candidate_rerun import (
    test_unreadable_and_stale_inputs_are_red_with_diagnostics,
)
from tests.test_release_candidate_seal import test_candidate_id_changes_with_generation
from tests.test_release_candidate_seal import (
    test_candidate_id_stable_across_observations,
)
from tests.test_release_candidate_seal import (
    test_cross_check_lock_hashes_catches_mismatch,
)
from tests.test_release_candidate_seal import test_each_identity_mismatch_refuses
from tests.test_release_candidate_seal import test_evaluate_reports_missing_evidence_red
from tests.test_release_candidate_seal import test_evaluate_veto_blocks
from tests.test_release_candidate_seal import test_extra_or_missing_dist_refuses
from tests.test_release_candidate_seal import (
    test_incomplete_core_file_set_refuses_to_seal,
)
from tests.test_release_candidate_seal import test_missing_file_locator_fails_closed
from tests.test_release_candidate_seal import test_observe_reappend_is_idempotent
from tests.test_release_candidate_seal import (
    test_observe_refuses_to_replace_a_conflicting_asset,
)
from tests.test_release_candidate_seal import (
    test_parse_expected_suffixes_reads_block_form,
)
from tests.test_release_candidate_seal import (
    test_parse_expected_suffixes_refuses_duplicate_suffix,
)
from tests.test_release_candidate_seal import (
    test_parse_expected_suffixes_refuses_empty_block,
)
from tests.test_release_candidate_seal import (
    test_parse_expected_suffixes_refuses_missing_block,
)
from tests.test_release_candidate_seal import (
    test_second_stash_generation_must_requalify,
)
from tests.test_release_candidate_seal import test_unknown_observation_kind_refuses
from tests.test_release_candidate_seal import test_unsupported_locator_fails_closed
from tests.test_release_candidate_publish import (
    test_confirm_requires_every_file_and_refuses_extra,
)
from tests.test_release_candidate_publish import (
    test_dist_helpers_still_cover_publish_fixtures,
)
from tests.test_release_candidate_publish import (
    test_publish_plan_accepts_both_pypi_shapes,
)
from tests.test_release_candidate_publish import (
    test_publish_plan_refuses_different_hash,
)
from tests.test_release_candidate_publish import (
    test_publish_plan_refuses_extra_pypi_file,
)
from tests.test_release_candidate_publish import (
    test_publish_plan_refuses_missing_staged_asset,
)
from tests.test_release_candidate_publish import (
    test_publish_plan_resume_after_one_upload,
)
from tests.test_release_candidate_publish import (
    test_publish_plan_uploads_missing_and_skips_identical,
)
from tests.test_release_candidate_seal import (
    test_yanked_only_core_file_set_refuses_to_seal,
)
from tests.test_release_candidate_seal import tool


pytestmark = pytest.mark.contract

__test__ = False

__all__ = [
    "test_attempt_two_cannot_hide_first_attempt_harness_failure",
    "test_bare_pass_observation_is_not_qualification_evidence",
    "test_candidate_id_changes_with_generation",
    "test_candidate_id_stable_across_observations",
    "test_changed_carried_forward_success_is_ambiguous_and_red",
    "test_confirm_requires_every_file_and_refuses_extra",
    "test_cross_check_lock_hashes_catches_mismatch",
    "test_dist_helpers_still_cover_publish_fixtures",
    "test_duplicate_or_unreadable_evidence_file_fails_closed",
    "test_each_identity_mismatch_refuses",
    "test_evaluate_reports_missing_evidence_red",
    "test_evaluate_veto_blocks",
    "test_evidence_binding_mismatches_are_red",
    "test_extra_or_missing_dist_refuses",
    "test_failed_reporting_step_cannot_accept_a_partial_pytest_report",
    "test_first_test_only_red_is_rerun_eligible_and_retry_preserves_history",
    "test_incomplete_core_file_set_refuses_to_seal",
    "test_inventory_duplicate_json_keys_fail_closed",
    "test_inventory_invalid_contracts_fail_closed",
    "test_job_bundle_identity_mismatches_are_red",
    "test_lint_binding_diagnostics_keep_missing_names",
    "test_missing_file_locator_fails_closed",
    "test_missing_matrix_entry_and_duplicate_job_mapping_are_red",
    "test_n1_inventory_is_single_versioned_classification",
    "test_observe_reappend_is_idempotent",
    "test_observe_refuses_to_replace_a_conflicting_asset",
    "test_old_generation_evidence_cannot_qualify_new_candidate",
    "test_old_pass_never_wins_over_a_newer_red",
    "test_parse_expected_suffixes_reads_block_form",
    "test_parse_expected_suffixes_refuses_duplicate_suffix",
    "test_parse_expected_suffixes_refuses_empty_block",
    "test_parse_expected_suffixes_refuses_missing_block",
    "test_publish_plan_accepts_both_pypi_shapes",
    "test_publish_plan_refuses_different_hash",
    "test_publish_plan_refuses_extra_pypi_file",
    "test_publish_plan_refuses_missing_staged_asset",
    "test_publish_plan_resume_after_one_upload",
    "test_publish_plan_uploads_missing_and_skips_identical",
    "test_qualification_evaluator_loads_its_focused_helpers",
    "test_qualification_pass_archives_bound_evidence_and_advisories",
    "test_qualify_cli_persists_red_observation_before_refusal",
    "test_required_job_red_classes_are_typed",
    "test_second_red_is_not_rerun_eligible",
    "test_second_stash_generation_must_requalify",
    "test_successful_job_cannot_be_rerun_on_a_failed_only_attempt",
    "test_unknown_observation_kind_refuses",
    "test_unreadable_and_stale_inputs_are_red_with_diagnostics",
    "test_unsupported_locator_fails_closed",
    "test_yanked_only_core_file_set_refuses_to_seal",
    "tool",
]
