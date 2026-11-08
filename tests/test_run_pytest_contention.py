"""The opt-in contention soak lane in ``tools/run_pytest``.

This module remains the public import and pytest collection path for the
contention contract tests, which are grouped into private suite modules.
"""

from __future__ import annotations

import json  # noqa: F401
import os  # noqa: F401
import subprocess  # noqa: F401
import sys  # noqa: F401
from pathlib import Path  # noqa: F401
from types import SimpleNamespace  # noqa: F401
from typing import Any  # noqa: F401

import pytest

from tests import _contention_plugin as contention_plugin  # noqa: F401
from tests._contention import (  # noqa: F401
    DIAGNOSTICS_ENV,
    FAILURES_ENV,
    FAILURE_DETAIL_LIMIT,
    SHARDS_ENV,
    NodeTally,
    append_failure_report,
    format_tally,
    read_failure_record,
    read_failures,
    read_shard_map,
    start_failure_record,
    tally_failures,
    write_failures,
)
from tests._run_pytest_fixtures import (
    isolate_run_pytest_environment,  # noqa: F401 (registers autouse env-isolation fixture)
    load_run_pytest,
)
from tests._run_pytest_contention_support import FakeSampler, RecordedRepeat
from tests._test_selection_health_store import RECORD_ENV, STORE_ENV  # noqa: F401
from tests._test_shards import discover_test_files  # noqa: F401
from tests._test_run_pytest_contention_lane import (
    test_contention_mode_runs_the_default_lane_selection,
    test_contention_stays_out_of_the_recorded_and_full_lane_modes,
    test_contention_is_unreachable_from_the_verification_recipes,
    test_repeat_runs_neither_lease_the_gate_nor_record_health,
    test_repeats_run_hypothesis_with_the_profile_hosted_ci_uses,
    test_repeat_count_and_selector_subset_are_honoured,
    test_a_whole_suite_soak_gives_each_worker_its_own_shard_of_the_files,
    test_a_caller_chosen_scope_keeps_whole_collection_on_every_worker,
    test_red_soak_returns_the_first_repeat_exit_status,
    test_stale_records_from_a_longer_soak_are_cleared,
    test_invalid_repeat_count_is_a_usage_error,
    test_numprocesses_is_rejected_with_the_lane_specific_remedy,
    test_worker_width_falls_back_to_the_general_knob_then_the_default,
)
from tests._test_run_pytest_contention_records import (
    test_empty_tally_reports_the_clean_soak_as_a_result,
    test_recorded_failures_round_trip_deduplicated,
    test_recorder_writes_test_failures_and_collection_errors,
    test_failure_reports_are_durable_before_session_finish_and_bounded,
    test_failure_record_write_errors_do_not_escape_into_pytest,
    test_only_the_controller_registers_the_recorder,
    test_each_repeat_gets_its_own_progress_record_and_one_sampler_watches_all,
    test_an_unavailable_sampler_changes_neither_the_run_nor_its_exit_status,
    test_a_signalled_repeat_is_named_and_keeps_its_exit_status,
    test_interrupted_failure_reports_stay_separate_from_completed_tally,
    test_nested_contention_does_not_clear_a_parent_soak_record,
    test_missing_record_after_zero_exit_is_not_a_clean_repeat,
    test_an_interrupted_soak_still_stops_its_sampler,
    test_invalid_sample_interval_is_a_usage_error,
    test_tally_orders_frequent_nodes_first_and_keeps_repeat_indices,
    test_unreadable_or_foreign_records_contribute_no_nodes,
)

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[1]
