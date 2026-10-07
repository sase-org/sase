"""CLI coverage for bead design-reference diagnosis and repair.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_bead.test_cli_doctor_design_refs import (
    test_confirmation_requires_interactive_yes,
    test_confirmed_fix_uses_update_events_and_one_aggregate_commit,
    test_doctor_omits_prefix_warning_for_correctly_prefixed_store,
    test_doctor_root_discovery_degrades_to_explicit_unavailable,
    test_doctor_warns_about_leaked_key_prefix,
    test_fix_issue_prefix_rewrites_config_and_preserves_existing_ids,
    test_fix_issue_prefix_with_nothing_to_repair,
    test_fix_preview_cancellation_never_opens_mutation,
    test_plain_doctor_forwards_roots_without_planning_or_writing,
    test_stale_preview_performs_no_updates_or_commit,
)
from tests.test_bead.test_cli_doctor_parser import (
    test_doctor_parser_accepts_fix_aliases_and_documents_help,
    test_doctor_parser_accepts_fix_issue_prefix_alias_and_documents_help,
    test_doctor_parser_accepts_fix_plan_archive_alias_and_documents_help,
    test_doctor_parser_accepts_projection_repair_and_yes_aliases,
    test_doctor_parser_accepts_verify_cache_alias_and_documents_help,
)
from tests.test_bead.test_cli_doctor_projection import (
    test_fix_projection_refuses_row_set_drift,
    test_fix_projection_repairs_expected_drift_and_second_run_is_noop,
    test_projection_repair_guard_refuses_unexpected_shapes,
)
from tests.test_bead.test_cli_doctor_status import (
    test_doctor_renders_fresh_read_model_status_line,
    test_doctor_renders_seal_watch_ok_lines,
    test_doctor_renders_seal_watch_unavailable,
    test_doctor_renders_seal_watch_warn_with_design_pointer,
    test_doctor_reports_read_model_status_without_git_backed_cache,
    test_doctor_reports_seal_watch_triggers,
    test_doctor_verify_cache_reports_drift,
    test_doctor_verify_cache_reports_match,
)

__test__ = False

__all__ = [
    "test_confirmation_requires_interactive_yes",
    "test_confirmed_fix_uses_update_events_and_one_aggregate_commit",
    "test_doctor_omits_prefix_warning_for_correctly_prefixed_store",
    "test_doctor_parser_accepts_fix_aliases_and_documents_help",
    "test_doctor_parser_accepts_fix_issue_prefix_alias_and_documents_help",
    "test_doctor_parser_accepts_fix_plan_archive_alias_and_documents_help",
    "test_doctor_parser_accepts_projection_repair_and_yes_aliases",
    "test_doctor_parser_accepts_verify_cache_alias_and_documents_help",
    "test_doctor_renders_fresh_read_model_status_line",
    "test_doctor_renders_seal_watch_ok_lines",
    "test_doctor_renders_seal_watch_unavailable",
    "test_doctor_renders_seal_watch_warn_with_design_pointer",
    "test_doctor_reports_read_model_status_without_git_backed_cache",
    "test_doctor_reports_seal_watch_triggers",
    "test_doctor_root_discovery_degrades_to_explicit_unavailable",
    "test_doctor_verify_cache_reports_drift",
    "test_doctor_verify_cache_reports_match",
    "test_doctor_warns_about_leaked_key_prefix",
    "test_fix_issue_prefix_rewrites_config_and_preserves_existing_ids",
    "test_fix_issue_prefix_with_nothing_to_repair",
    "test_fix_preview_cancellation_never_opens_mutation",
    "test_fix_projection_refuses_row_set_drift",
    "test_fix_projection_repairs_expected_drift_and_second_run_is_noop",
    "test_plain_doctor_forwards_roots_without_planning_or_writing",
    "test_projection_repair_guard_refuses_unexpected_shapes",
    "test_stale_preview_performs_no_updates_or_commit",
]
