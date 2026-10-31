"""Facade preserving the historic ``test_monitor_start_stage`` import path.

Internal stage/adopt/cleanup tests now live in
:mod:`test_monitor_start_stage_adopt`,
:mod:`test_monitor_start_stage_prepared`, and
:mod:`test_monitor_start_stage_cleanup`; this module re-exports their public
test functions so existing import paths keep working.
"""

from __future__ import annotations

# Tests live in the split modules below; keep this facade out of pytest
# collection so each test runs once while the import path keeps working.
__test__ = False

from ._start_stage import SANDBOX_CATALOG
from .test_monitor_start_stage_adopt import (
    test_nested_cwd_and_explicit_lane_freeze_workspace,
    test_stage_blocks_lane_and_replays_identical_request,
    test_stage_persists_payload_and_reconstructs,
    test_staged_authored_checkpoint_missing_or_corrupt_refuses_before_launch,
    test_staged_authored_checkpoint_survives_cli_file_removal,
    test_staged_monitor_adoption_saves_real_response_and_exact_starter_parent,
    test_staged_monitor_rejects_foreign_persisted_starter_before_launch,
    test_tool_run_id_is_stable_from_stage_to_launch,
)
from .test_monitor_start_stage_cleanup import (
    test_ack_failure_rolls_back_staged_launch,
    test_cleanup_at_resource_boundaries,
    test_cleanup_releases_staged_join_without_stopping_run,
    test_failed_finalization_releases_monitor_resources_and_keeps_stage,
    test_held_cleanup_keeps_outer_record,
    test_immediate_start_still_launches,
    test_launch_from_persisted_payload_runs,
    test_launcher_exit_keeps_pending_owner,
    test_reserved_join_that_settles_before_adoption_is_consumed,
)
from .test_monitor_start_stage_prepared import (
    test_prepared_stage_ack_failure_rolls_back_binding_and_reservation,
    test_prepared_stage_rejects_wrong_command_before_publish,
    test_prepared_stage_reserves_without_binding_then_binds_at_spawn,
    test_staged_monitor_waits_for_real_finalizer_controller,
)

__all__ = [
    "SANDBOX_CATALOG",
    "test_ack_failure_rolls_back_staged_launch",
    "test_cleanup_at_resource_boundaries",
    "test_cleanup_releases_staged_join_without_stopping_run",
    "test_failed_finalization_releases_monitor_resources_and_keeps_stage",
    "test_held_cleanup_keeps_outer_record",
    "test_immediate_start_still_launches",
    "test_launch_from_persisted_payload_runs",
    "test_launcher_exit_keeps_pending_owner",
    "test_nested_cwd_and_explicit_lane_freeze_workspace",
    "test_prepared_stage_ack_failure_rolls_back_binding_and_reservation",
    "test_prepared_stage_rejects_wrong_command_before_publish",
    "test_prepared_stage_reserves_without_binding_then_binds_at_spawn",
    "test_reserved_join_that_settles_before_adoption_is_consumed",
    "test_stage_blocks_lane_and_replays_identical_request",
    "test_stage_persists_payload_and_reconstructs",
    "test_staged_authored_checkpoint_missing_or_corrupt_refuses_before_launch",
    "test_staged_authored_checkpoint_survives_cli_file_removal",
    "test_staged_monitor_adoption_saves_real_response_and_exact_starter_parent",
    "test_staged_monitor_rejects_foreign_persisted_starter_before_launch",
    "test_staged_monitor_waits_for_real_finalizer_controller",
    "test_tool_run_id_is_stable_from_stage_to_launch",
]
