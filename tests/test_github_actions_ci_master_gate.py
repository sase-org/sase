"""Contract tests for the scheduled/per-SHA workflows layered on top of ci.yml.

Companion to ``test_github_actions_ci_workflow.py``; master-gate.yml,
full.yml, core-pin-ratchet.yml, and shard-timings-ratchet.yml live here
because they have their own trigger and reuse contracts. Shared workflow
loaders live in ``tests/_github_actions_ci_helpers.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._github_actions_ci_helpers import REPO_ROOT
from tests._github_actions_ci_helpers import TELEMETRY_CORE_ARTIFACT_CONSUMER_JOBS
from tests._github_actions_ci_helpers import callee_declared_scopes
from tests._github_actions_ci_helpers import caller_effective_permissions
from tests._github_actions_ci_helpers import permission_gaps
from tests._github_actions_ci_helpers import reusable_caller_permission_gaps
from tests._test_shards import DEFAULT_SHARD_COUNT
from tests._test_shards import SHARD_TIMINGS_ARTIFACT_NAME
from tests._github_actions_ci_master_gate_full import (
    test_build_core_workflow_is_reusable_only,
)
from tests._github_actions_ci_master_gate_full import (
    test_build_core_workflow_is_the_only_consumer_of_its_own_artifact_name,
)
from tests._github_actions_ci_master_gate_full import (
    test_full_ci_triggers_and_calls_the_reusable_ci_workflow,
)
from tests._github_actions_ci_master_gate_full import (
    test_heavy_lane_jobs_are_defined_once_in_the_reusable_workflow,
)
from tests._github_actions_ci_master_gate_full import (
    test_named_reusable_calls_cover_callee_scopes,
)
from tests._github_actions_ci_master_gate_full import (
    test_old_full_yml_fails_the_reusable_permission_contract,
)
from tests._github_actions_ci_master_gate_full import (
    test_readme_explains_the_three_ci_badges,
)
from tests._github_actions_ci_master_gate_full import (
    test_reusable_workflow_callers_grant_callee_permissions,
)
from tests._github_actions_ci_master_gate_full import (
    test_telemetry_lane_jobs_run_just_recipes_against_the_shared_core_artifact,
)
from tests._github_actions_ci_master_gate_full import (
    test_telemetry_workflow_builds_core_through_the_shared_reusable_workflow,
)
from tests._github_actions_ci_master_gate_full import (
    test_telemetry_workflow_publishes_contexts_on_master_only_with_headroom,
)
from tests._github_actions_ci_master_gate_full import (
    test_telemetry_workflow_runs_cost_attribution_with_realistic_timeout,
)
from tests._github_actions_ci_master_gate_full import (
    test_telemetry_workflow_runs_one_contention_repeat_within_the_same_ceiling,
)
from tests._github_actions_ci_master_gate_full import (
    test_telemetry_workflow_triggers_on_a_schedule_offset_from_full_ci,
)
from tests._github_actions_ci_master_gate_full import (
    test_write_permission_covers_read_and_missing_explicit_map_fails,
)
from tests._github_actions_ci_master_gate_jobs import (
    test_master_gate_builds_docs_without_core_wheel_dependency,
)
from tests._github_actions_ci_master_gate_jobs import (
    test_master_gate_core_wheel_job_resolves_and_caches_by_sha,
)
from tests._github_actions_ci_master_gate_jobs import (
    test_master_gate_has_read_only_contents_permission,
)
from tests._github_actions_ci_master_gate_jobs import (
    test_master_gate_jobs_stay_within_the_twenty_minute_ceiling,
)
from tests._github_actions_ci_master_gate_jobs import (
    test_master_gate_lint_job_matches_ci_lint_steps_byte_for_byte,
)
from tests._github_actions_ci_master_gate_jobs import (
    test_master_gate_never_cancels_a_running_sha,
)
from tests._github_actions_ci_master_gate_jobs import (
    test_master_gate_never_runs_screenshot_maintenance,
)
from tests._github_actions_ci_master_gate_jobs import (
    test_master_gate_shard_matrix_matches_the_declared_shard_count,
)
from tests._github_actions_ci_master_gate_jobs import (
    test_master_gate_test_job_runs_only_the_sharded_fast_lane,
)
from tests._github_actions_ci_master_gate_jobs import (
    test_master_gate_triggers_on_master_pushes_and_manual_dispatch_only,
)
from tests._github_actions_ci_master_gate_ratchet import (
    test_core_pin_ratchet_apply_tolerates_exit_two,
)
from tests._github_actions_ci_master_gate_ratchet import (
    test_core_pin_ratchet_runs_on_schedule_not_push,
)
from tests._github_actions_ci_master_gate_ratchet import (
    test_core_pin_ratchet_step_apply_failure_aborts_before_push,
)
from tests._github_actions_ci_master_gate_ratchet import (
    test_core_pin_ratchet_step_check_failure_aborts_before_apply,
)
from tests._github_actions_ci_master_gate_ratchet import (
    test_core_pin_ratchet_step_pending_bump_pushes_and_opens_pr,
)
from tests._github_actions_ci_master_gate_ratchet import (
    test_core_pin_ratchet_step_pending_bump_updates_existing_pr,
)
from tests._github_actions_ci_master_gate_ratchet import (
    test_core_pin_ratchet_step_up_to_date_makes_no_push_or_pr,
)
from tests._github_actions_ci_master_gate_ratchet import (
    test_core_pin_ratchet_uses_the_shared_tool_and_names_the_pin_file,
)
from tests._github_actions_ci_master_gate_ratchet import (
    test_shard_timings_ratchet_consumes_the_full_ci_artifact,
)
from tests._github_actions_ci_master_gate_ratchet import (
    test_shard_timings_ratchet_runs_on_schedule_not_push,
)


pytestmark = pytest.mark.contract

__all__ = [
    "test_master_gate_triggers_on_master_pushes_and_manual_dispatch_only",
    "test_master_gate_never_cancels_a_running_sha",
    "test_master_gate_has_read_only_contents_permission",
    "test_master_gate_builds_docs_without_core_wheel_dependency",
    "test_master_gate_jobs_stay_within_the_twenty_minute_ceiling",
    "test_master_gate_shard_matrix_matches_the_declared_shard_count",
    "test_master_gate_test_job_runs_only_the_sharded_fast_lane",
    "test_master_gate_never_runs_screenshot_maintenance",
    "test_master_gate_core_wheel_job_resolves_and_caches_by_sha",
    "test_master_gate_lint_job_matches_ci_lint_steps_byte_for_byte",
    "test_full_ci_triggers_and_calls_the_reusable_ci_workflow",
    "test_reusable_workflow_callers_grant_callee_permissions",
    "test_old_full_yml_fails_the_reusable_permission_contract",
    "test_named_reusable_calls_cover_callee_scopes",
    "test_write_permission_covers_read_and_missing_explicit_map_fails",
    "test_heavy_lane_jobs_are_defined_once_in_the_reusable_workflow",
    "test_readme_explains_the_three_ci_badges",
    "test_build_core_workflow_is_reusable_only",
    "test_build_core_workflow_is_the_only_consumer_of_its_own_artifact_name",
    "test_telemetry_workflow_triggers_on_a_schedule_offset_from_full_ci",
    "test_telemetry_workflow_builds_core_through_the_shared_reusable_workflow",
    "test_telemetry_workflow_runs_cost_attribution_with_realistic_timeout",
    "test_telemetry_workflow_publishes_contexts_on_master_only_with_headroom",
    "test_telemetry_workflow_runs_one_contention_repeat_within_the_same_ceiling",
    "test_telemetry_lane_jobs_run_just_recipes_against_the_shared_core_artifact",
    "test_core_pin_ratchet_runs_on_schedule_not_push",
    "test_core_pin_ratchet_uses_the_shared_tool_and_names_the_pin_file",
    "test_core_pin_ratchet_apply_tolerates_exit_two",
    "test_core_pin_ratchet_step_pending_bump_pushes_and_opens_pr",
    "test_core_pin_ratchet_step_pending_bump_updates_existing_pr",
    "test_core_pin_ratchet_step_up_to_date_makes_no_push_or_pr",
    "test_core_pin_ratchet_step_check_failure_aborts_before_apply",
    "test_core_pin_ratchet_step_apply_failure_aborts_before_push",
    "test_shard_timings_ratchet_runs_on_schedule_not_push",
    "test_shard_timings_ratchet_consumes_the_full_ci_artifact",
    "DEFAULT_SHARD_COUNT",
    "Path",
    "REPO_ROOT",
    "SHARD_TIMINGS_ARTIFACT_NAME",
    "TELEMETRY_CORE_ARTIFACT_CONSUMER_JOBS",
    "callee_declared_scopes",
    "caller_effective_permissions",
    "permission_gaps",
    "pytest",
    "pytestmark",
    "reusable_caller_permission_gaps",
]
