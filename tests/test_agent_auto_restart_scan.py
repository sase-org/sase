"""Tests for the update-skew witness-scan phase (read-only replay).

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_agent_auto_restart_scan_history import (
    test_collect_failed_candidates_filters_and_dedups,
    test_collect_failed_candidates_keeps_unknown_time,
    test_failure_facts_wire_round_trip,
    test_handle_scan_empty_corpus,
    test_handle_scan_json_emits_verdict_wires,
    test_handle_scan_missing_binding,
    test_handle_scan_rejects_bad_flags,
    test_parse_local_stamp_variants,
    test_parse_since_and_limit,
    test_recovery_verdict_wire_to_dict,
)
from tests.test_agent_auto_restart_scan_inputs import (
    test_assemble_bundle_input,
    test_assemble_done_row_legacy_without_facts,
    test_assemble_done_row_pending_markers,
    test_assemble_done_row_with_structured_facts,
    test_find_runner_log_by_timestamp_suffix,
    test_find_runner_log_prefers_output_path,
    test_read_log_tail_last_200_lines,
)
from tests.test_agent_auto_restart_scan_proof import (
    test_code_identity_digest_detects_drift,
    test_code_identity_digest_none_without_roots,
    test_code_identity_digest_prefers_commit_over_version,
    test_code_identity_digest_stable_without_drift,
    test_extract_proof_target_from_attribute_error,
    test_extract_proof_target_from_error_text,
    test_extract_proof_target_from_structured_facts,
    test_extract_proof_target_unknown,
    test_parse_refresh_log_line,
    test_parse_refresh_log_line_missing,
    test_select_proof_root,
)
from tests.test_agent_auto_restart_scan_witnesses import (
    test_collect_file_proof_addition_names_culprit,
    test_collect_file_proof_removal_names_culprit,
    test_collect_file_proof_unknown_module,
    test_collect_journal_updates_bundle_window,
    test_collect_journal_updates_missing_file,
    test_collect_journal_updates_needs_launch_bound,
    test_collect_journal_updates_uses_artifacts_timestamp,
    test_collect_journal_updates_window,
    test_collect_witnesses_w1_and_refresh_line,
    test_witness_file_proof_disabled_flag,
    test_witness_file_proof_gated_on_prefilter,
)

__test__ = False

__all__ = [
    "test_assemble_bundle_input",
    "test_assemble_done_row_legacy_without_facts",
    "test_assemble_done_row_pending_markers",
    "test_assemble_done_row_with_structured_facts",
    "test_code_identity_digest_detects_drift",
    "test_code_identity_digest_none_without_roots",
    "test_code_identity_digest_prefers_commit_over_version",
    "test_code_identity_digest_stable_without_drift",
    "test_collect_failed_candidates_filters_and_dedups",
    "test_collect_failed_candidates_keeps_unknown_time",
    "test_collect_file_proof_addition_names_culprit",
    "test_collect_file_proof_removal_names_culprit",
    "test_collect_file_proof_unknown_module",
    "test_collect_journal_updates_bundle_window",
    "test_collect_journal_updates_missing_file",
    "test_collect_journal_updates_needs_launch_bound",
    "test_collect_journal_updates_uses_artifacts_timestamp",
    "test_collect_journal_updates_window",
    "test_collect_witnesses_w1_and_refresh_line",
    "test_extract_proof_target_from_attribute_error",
    "test_extract_proof_target_from_error_text",
    "test_extract_proof_target_from_structured_facts",
    "test_extract_proof_target_unknown",
    "test_failure_facts_wire_round_trip",
    "test_find_runner_log_by_timestamp_suffix",
    "test_find_runner_log_prefers_output_path",
    "test_handle_scan_empty_corpus",
    "test_handle_scan_json_emits_verdict_wires",
    "test_handle_scan_missing_binding",
    "test_handle_scan_rejects_bad_flags",
    "test_parse_local_stamp_variants",
    "test_parse_refresh_log_line",
    "test_parse_refresh_log_line_missing",
    "test_parse_since_and_limit",
    "test_read_log_tail_last_200_lines",
    "test_recovery_verdict_wire_to_dict",
    "test_select_proof_root",
    "test_witness_file_proof_disabled_flag",
    "test_witness_file_proof_gated_on_prefilter",
]
