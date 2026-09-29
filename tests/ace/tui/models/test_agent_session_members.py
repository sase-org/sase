"""Concrete sequential agent session-member projection tests.

Split facade: the tests now live in ``test_agent_session_members_concrete``,
``test_agent_session_members_turns``, and ``test_agent_session_members_current``.
This module re-exports the public names so the original import path keeps
working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.models.test_agent_session_members_concrete import (
    test_bare_non_plan_container_stays_execution_neutral,
    test_concrete_planner_replaces_aggregate_root_and_mixed_links_dedupe,
    test_member_plus_monitor_still_makes_a_agent_session_container,
    test_monitor_only_child_does_not_make_starter_a_agent_session_container,
    test_plan_root_without_concrete_planner_uses_root_fallback,
    test_promoted_plan_agent_session_root_no_longer_double_counted_as_member,
    test_rename_on_attach_root_remains_the_first_real_member,
    test_workflow_aggregate_projects_only_loaded_agent_steps,
    test_workflow_without_loaded_agent_steps_falls_back_to_root,
)
from tests.ace.tui.models.test_agent_session_members_current import (
    test_current_agent_session_turn_ignores_waiting_and_parallel_agent_sessions,
    test_current_agent_session_turn_returns_none_without_active_turn,
    test_current_agent_session_turn_selects_active_promoted_root,
    test_current_agent_session_turn_selects_later_serial_continuation,
    test_current_agent_session_turn_selects_nested_running_monitor,
    test_current_agent_session_turn_uses_newest_active_candidate_in_chain_order,
    test_lane_entries_keep_failed_bucket_when_followup_errored,
    test_lane_entries_map_final_launched_monitor_to_running,
    test_lane_entries_skip_non_final_failed_monitor_with_launched_followup,
)
from tests.ace.tui.models.test_agent_session_members_turns import (
    test_attach_agent_session_containers_reaches_nested_monitor_without_rerooting,
    test_gate_agent_session_member_rows_do_not_count_as_agents,
    test_gate_starter_root_still_counts_as_concrete_agent,
    test_monitor_agent_session_member_rows_do_not_count_as_agents,
    test_monitor_starter_root_still_counts_as_concrete_agent,
    test_nested_monitor_follows_mid_agent_session_continuation,
    test_planner_step_projection_keeps_every_monitor,
    test_root_monitor_follows_its_planner_step_anchor,
    test_root_monitor_follows_root_when_no_step_is_loaded,
    test_root_monitor_precedes_later_continuations,
    test_settling_gate_can_be_current_agent_session_turn,
    test_turn_projection_dedupes_overlapping_links_and_identity,
    test_turn_projection_terminates_on_cycles,
)

__test__ = False

__all__ = [
    "test_attach_agent_session_containers_reaches_nested_monitor_without_rerooting",
    "test_bare_non_plan_container_stays_execution_neutral",
    "test_concrete_planner_replaces_aggregate_root_and_mixed_links_dedupe",
    "test_current_agent_session_turn_ignores_waiting_and_parallel_agent_sessions",
    "test_current_agent_session_turn_returns_none_without_active_turn",
    "test_current_agent_session_turn_selects_active_promoted_root",
    "test_current_agent_session_turn_selects_later_serial_continuation",
    "test_current_agent_session_turn_selects_nested_running_monitor",
    "test_current_agent_session_turn_uses_newest_active_candidate_in_chain_order",
    "test_gate_agent_session_member_rows_do_not_count_as_agents",
    "test_gate_starter_root_still_counts_as_concrete_agent",
    "test_lane_entries_keep_failed_bucket_when_followup_errored",
    "test_lane_entries_map_final_launched_monitor_to_running",
    "test_lane_entries_skip_non_final_failed_monitor_with_launched_followup",
    "test_member_plus_monitor_still_makes_a_agent_session_container",
    "test_monitor_agent_session_member_rows_do_not_count_as_agents",
    "test_monitor_only_child_does_not_make_starter_a_agent_session_container",
    "test_monitor_starter_root_still_counts_as_concrete_agent",
    "test_nested_monitor_follows_mid_agent_session_continuation",
    "test_plan_root_without_concrete_planner_uses_root_fallback",
    "test_planner_step_projection_keeps_every_monitor",
    "test_promoted_plan_agent_session_root_no_longer_double_counted_as_member",
    "test_rename_on_attach_root_remains_the_first_real_member",
    "test_root_monitor_follows_its_planner_step_anchor",
    "test_root_monitor_follows_root_when_no_step_is_loaded",
    "test_root_monitor_precedes_later_continuations",
    "test_settling_gate_can_be_current_agent_session_turn",
    "test_turn_projection_dedupes_overlapping_links_and_identity",
    "test_turn_projection_terminates_on_cycles",
    "test_workflow_aggregate_projects_only_loaded_agent_steps",
    "test_workflow_without_loaded_agent_steps_falls_back_to_root",
]
