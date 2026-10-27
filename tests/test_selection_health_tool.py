"""Tests for the `tools/selection_health` CLI wrapper.

The synthetic record store keeps these tests independent from this host's history.
Test implementations live in private modules; this module preserves the public
import path and remains the sole pytest collection entry point.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

from tests._selection_health_tool_helpers import (
    AUDIT_NODE,
    FLAKE_NODE,
    NOW,
    ROOT,
    TOOL_PATH,
    WORKSPACE,
)
from tests._selection_health_tool_report import (
    test_empty_store_reports_rather_than_failing,
    test_fail_on_false_negative_is_opt_in,
    test_json_output_is_parseable,
    test_report_reads_the_requested_store,
    test_tool_script_is_executable,
)
from tests._selection_health_tool_flake_gate import (
    test_committed_flake_baseline_parses_through_the_tool_parser,
    test_fail_on_new_flake_allows_committed_baseline_debt,
    test_fail_on_new_flake_excludes_attributable_dirty_tree_audit_failures,
    test_fail_on_new_flake_ignores_fixed_deterministic_breaks,
    test_fail_on_new_flake_ignores_records_before_the_baseline_effective_time,
    test_fail_on_new_flake_passes_when_store_has_too_few_records,
    test_fail_on_new_flake_reports_nodes_that_exceed_the_baseline,
    test_fail_on_new_flake_treats_an_uncollectable_node_as_stale_not_a_flake,
)
from tests._selection_health_tool_flake_retirement import (
    test_fail_on_new_flake_does_not_retire_a_record_with_no_recorded_at,
    test_fail_on_new_flake_exits_2_on_a_duplicate_fixed_at_entry,
    test_fail_on_new_flake_exits_2_on_malformed_fixed_at_directives,
    test_fail_on_new_flake_reports_a_fixed_at_entry_that_retired_nothing,
    test_fail_on_new_flake_retires_evidence_recorded_before_the_fix,
    test_fail_on_new_flake_retirement_is_scoped_to_its_own_node,
    test_fail_on_new_flake_still_flags_a_node_that_fails_again_after_its_fix,
)
from tests._test_selection_health_store import (
    KIND_FULL_RUN,
    allocate_record_path,
    full_run_record,
    record_selection,
    write_record,
)

__all__ = [
    "importlib",
    "json",
    "UTC",
    "datetime",
    "timedelta",
    "SourceFileLoader",
    "Path",
    "ModuleType",
    "pytest",
    "KIND_FULL_RUN",
    "allocate_record_path",
    "full_run_record",
    "record_selection",
    "write_record",
    "AUDIT_NODE",
    "FLAKE_NODE",
    "NOW",
    "ROOT",
    "TOOL_PATH",
    "WORKSPACE",
    "test_empty_store_reports_rather_than_failing",
    "test_fail_on_false_negative_is_opt_in",
    "test_json_output_is_parseable",
    "test_report_reads_the_requested_store",
    "test_tool_script_is_executable",
    "test_committed_flake_baseline_parses_through_the_tool_parser",
    "test_fail_on_new_flake_allows_committed_baseline_debt",
    "test_fail_on_new_flake_excludes_attributable_dirty_tree_audit_failures",
    "test_fail_on_new_flake_ignores_fixed_deterministic_breaks",
    "test_fail_on_new_flake_ignores_records_before_the_baseline_effective_time",
    "test_fail_on_new_flake_passes_when_store_has_too_few_records",
    "test_fail_on_new_flake_reports_nodes_that_exceed_the_baseline",
    "test_fail_on_new_flake_treats_an_uncollectable_node_as_stale_not_a_flake",
    "test_fail_on_new_flake_does_not_retire_a_record_with_no_recorded_at",
    "test_fail_on_new_flake_exits_2_on_a_duplicate_fixed_at_entry",
    "test_fail_on_new_flake_exits_2_on_malformed_fixed_at_directives",
    "test_fail_on_new_flake_reports_a_fixed_at_entry_that_retired_nothing",
    "test_fail_on_new_flake_retires_evidence_recorded_before_the_fix",
    "test_fail_on_new_flake_retirement_is_scoped_to_its_own_node",
    "test_fail_on_new_flake_still_flags_a_node_that_fails_again_after_its_fix",
]
