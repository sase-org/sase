"""Scoreboard manifest coverage, section diff, and doctor tests (E2 phase 6).

This module is a facade preserving the original import path. The tests
now live in :mod:`tests.instructions.test_scoreboard_sessions`,
:mod:`tests.instructions.test_scoreboard_section_diff`, and
:mod:`tests.instructions.test_scoreboard_doctor`; shared fixtures live
in :mod:`tests.instructions._scoreboard_support`. Only public names are
re-exported here, never ``_``-private helpers.
"""

from __future__ import annotations

# The re-exported tests must not be collected twice: pytest collects
# this module (zero tests) and each home module (the real tests).
__test__ = False

from tests.instructions._scoreboard_support import (
    COVERED_START,
    RENDERED,
    RUN_END,
    RUN_START,
    SESSION_TS,
    UNCOVERED_START,
    WORKSPACE,
)
from tests.instructions.test_scoreboard_doctor import (
    test_doctor_coverage_ok_when_fully_covered,
    test_doctor_coverage_skips_without_manifests,
    test_doctor_coverage_warns_on_uncovered_and_errors,
    test_json_carries_coverage_and_section_diff,
)
from tests.instructions.test_scoreboard_section_diff import (
    test_diff_contract_sections_observed_twice,
    test_diff_grok_home_sections_zero,
    test_diff_muse_home_sections_zero,
    test_diff_partial_and_missing_manifest_are_unavailable,
    test_diff_skips_frame_and_heading_only_sections,
    test_real_writer_round_trip_covers_and_diffs,
)
from tests.instructions.test_scoreboard_sessions import (
    test_agy_scored_per_run,
    test_count_run_errors_reads_error_files,
    test_fallback_run_covers_two_providers,
    test_full_coverage_single_session,
    test_latest_manifest_wins,
    test_purpose_rows_name_uncovered_pairs_and_latency,
    test_root_session_starts_from_provider_files,
    test_skew_allows_seconds_late_manifest,
    test_uncovered_session_before_manifest,
)

__all__ = [
    "COVERED_START",
    "RENDERED",
    "RUN_END",
    "RUN_START",
    "SESSION_TS",
    "UNCOVERED_START",
    "WORKSPACE",
    "test_agy_scored_per_run",
    "test_count_run_errors_reads_error_files",
    "test_diff_contract_sections_observed_twice",
    "test_diff_grok_home_sections_zero",
    "test_diff_muse_home_sections_zero",
    "test_diff_partial_and_missing_manifest_are_unavailable",
    "test_diff_skips_frame_and_heading_only_sections",
    "test_doctor_coverage_ok_when_fully_covered",
    "test_doctor_coverage_skips_without_manifests",
    "test_doctor_coverage_warns_on_uncovered_and_errors",
    "test_fallback_run_covers_two_providers",
    "test_full_coverage_single_session",
    "test_json_carries_coverage_and_section_diff",
    "test_latest_manifest_wins",
    "test_purpose_rows_name_uncovered_pairs_and_latency",
    "test_real_writer_round_trip_covers_and_diffs",
    "test_root_session_starts_from_provider_files",
    "test_skew_allows_seconds_late_manifest",
    "test_uncovered_session_before_manifest",
]
