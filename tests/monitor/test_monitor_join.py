"""Monitor joins: ``sase monitor start -J/--join RUN`` and the join worker lane."""

from __future__ import annotations

from tests.main.monitor_handler_helpers import monitor_home

from .test_monitor_join_engine import (
    test_join_duplicate_start_replays_without_resubmitting,
    test_join_records_before_submit_and_skips_a_new_reservation,
    test_join_settle_race_tears_down_and_leaves_the_lane_clear,
    test_join_submit_failure_releases_the_join_and_tears_down,
    test_settle_skips_monitor_owned_reconcile_for_joined_runs,
    test_settle_still_reconciles_monitor_owned_runs,
    test_tool_stop_on_joined_run_stops_the_monitor_without_followup,
    test_tool_stop_with_terminal_join_monitor_falls_back_to_the_proc_path,
)
from .test_monitor_join_handler import (
    test_join_joined_elsewhere_is_refused,
    test_join_label_reason_and_command_derive_from_the_run,
    test_join_non_detached_run_is_refused,
    test_join_other_agents_run_is_refused,
    test_join_rejects_a_command_remainder,
    test_join_rejects_an_explicit_agent,
    test_join_rejects_completion_and_points_at_next,
    test_join_rejects_hidden_command_alias,
    test_join_requires_an_agent,
    test_join_settled_run_is_refused_with_state_and_pointer,
    test_join_start_builds_a_join_request_and_reports_joined,
    test_join_start_json_reports_tool_run_joined,
    test_join_stop_requested_run_is_refused,
    test_join_unknown_run_is_refused,
)

__all__ = [
    "monitor_home",
    "test_join_duplicate_start_replays_without_resubmitting",
    "test_join_joined_elsewhere_is_refused",
    "test_join_label_reason_and_command_derive_from_the_run",
    "test_join_non_detached_run_is_refused",
    "test_join_other_agents_run_is_refused",
    "test_join_records_before_submit_and_skips_a_new_reservation",
    "test_join_rejects_a_command_remainder",
    "test_join_rejects_an_explicit_agent",
    "test_join_rejects_completion_and_points_at_next",
    "test_join_rejects_hidden_command_alias",
    "test_join_requires_an_agent",
    "test_join_settled_run_is_refused_with_state_and_pointer",
    "test_join_settle_race_tears_down_and_leaves_the_lane_clear",
    "test_join_start_builds_a_join_request_and_reports_joined",
    "test_join_start_json_reports_tool_run_joined",
    "test_join_stop_requested_run_is_refused",
    "test_join_submit_failure_releases_the_join_and_tears_down",
    "test_join_unknown_run_is_refused",
    "test_settle_skips_monitor_owned_reconcile_for_joined_runs",
    "test_settle_still_reconciles_monitor_owned_runs",
    "test_tool_stop_on_joined_run_stops_the_monitor_without_followup",
    "test_tool_stop_with_terminal_join_monitor_falls_back_to_the_proc_path",
]
