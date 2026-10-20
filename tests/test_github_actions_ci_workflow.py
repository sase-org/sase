"""Public facade for the GitHub Actions CI workflow contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests._github_actions_ci_helpers import CORE_ARTIFACT_CONSUMER_JOBS
from tests._github_actions_ci_helpers import REPO_ROOT
from tests._test_selection_contexts import ARTIFACT_PREFIX
from tests._test_shards import SHARD_TIMINGS_ARTIFACT_NAME
from tests._github_actions_ci_workflow_setup import (
    test_ci_workflow_is_pull_request_and_reusable_only,
)
from tests._github_actions_ci_workflow_setup import (
    test_lint_job_initializes_sase_home_before_lint,
)
from tests._github_actions_ci_workflow_setup import (
    test_lint_job_never_regenerates_committed_project_files,
)
from tests._github_actions_ci_workflow_setup import (
    test_lint_job_uses_single_lint_command,
)
from tests._github_actions_ci_workflow_setup import (
    test_lint_job_checks_pinned_core_bindings_before_sidecars,
)
from tests._github_actions_ci_workflow_build import (
    test_ci_build_core_job_delegates_to_the_reusable_build_core_workflow,
)
from tests._github_actions_ci_workflow_build import (
    test_rust_core_is_built_once_and_shared_with_source_based_jobs,
)
from tests._github_actions_ci_workflow_build import (
    test_build_core_resolves_pinned_revision_before_checking_out_sase_core,
)
from tests._github_actions_ci_workflow_lanes import (
    test_redundant_lanes_are_consolidated_without_dropping_commands,
)
from tests._github_actions_ci_workflow_lanes import (
    test_test_job_timeout_allows_slow_3_12_leg,
)
from tests._github_actions_ci_workflow_lanes import (
    test_test_job_only_collects_coverage_on_3_12_leg,
)
from tests._github_actions_ci_workflow_lanes import (
    test_test_job_publishes_shard_timings_from_the_master_fast_leg,
)
from tests._github_actions_ci_workflow_lanes import (
    test_contexts_job_publishes_the_per_test_database_on_master_only,
)
from tests._github_actions_ci_workflow_lanes import (
    test_contexts_job_does_not_slow_the_per_pr_coverage_leg,
)
from tests._github_actions_ci_workflow_lanes import (
    test_contexts_databases_are_portable_between_machines,
)
from tests._github_actions_ci_workflow_lanes import (
    test_release_branch_core_floor_lane_uses_published_floor,
)
from tests._github_actions_ci_workflow_lanes import (
    test_ci_does_not_invoke_plugin_release_dependency_floor,
)
from tests._github_actions_ci_workflow_lanes import (
    test_ci_and_publish_never_invoke_the_testpypi_drill,
)
from tests._github_actions_ci_workflow_lanes import (
    test_ci_and_master_gate_never_run_the_diff_scoped_test_lane,
)
from tests._github_actions_ci_workflow_lanes import (
    test_visual_suite_runs_only_in_dedicated_job,
)
from tests._github_actions_ci_workflow_lanes import (
    test_ace_page_group_isolation_job_runs_dedicated_lane,
)
from tests._github_actions_ci_workflow_lanes import test_perf_floors_job_runs_slow_lane
from tests._github_actions_ci_workflow_lanes import (
    test_docs_build_once_per_event_and_deploys_are_serialized,
)
from tests._github_actions_ci_workflow_lanes import (
    test_ci_workflow_no_longer_contains_the_telemetry_lanes,
)
from tests._github_actions_ci_workflow_lanes import (
    test_core_artifact_consumer_jobs_run_just_recipes_after_setup,
)
from tests._github_actions_ci_workflow_qualification import (
    test_prepare_job_rejects_invalid_source_version_manifest_combinations,
)
from tests._github_actions_ci_workflow_qualification import (
    test_sase_checkouts_thread_the_explicit_ref_input,
)
from tests._github_actions_ci_workflow_qualification import (
    test_setup_sase_asserts_expected_core_version_in_published_mode,
)
from tests._github_actions_ci_workflow_qualification import (
    test_blocking_jobs_report_qualification_evidence_unconditionally,
)
from tests._github_actions_ci_workflow_qualification import (
    test_test_commands_and_plugin_activation_stay_reporting_only,
)
from tests._github_actions_ci_workflow_qualification import (
    test_advisory_jobs_still_run_for_qualification,
)

pytestmark = pytest.mark.contract

__all__ = [
    "test_ci_workflow_is_pull_request_and_reusable_only",
    "test_lint_job_initializes_sase_home_before_lint",
    "test_lint_job_never_regenerates_committed_project_files",
    "test_lint_job_uses_single_lint_command",
    "test_lint_job_checks_pinned_core_bindings_before_sidecars",
    "test_ci_build_core_job_delegates_to_the_reusable_build_core_workflow",
    "test_rust_core_is_built_once_and_shared_with_source_based_jobs",
    "test_build_core_resolves_pinned_revision_before_checking_out_sase_core",
    "test_redundant_lanes_are_consolidated_without_dropping_commands",
    "test_test_job_timeout_allows_slow_3_12_leg",
    "test_test_job_only_collects_coverage_on_3_12_leg",
    "test_test_job_publishes_shard_timings_from_the_master_fast_leg",
    "test_contexts_job_publishes_the_per_test_database_on_master_only",
    "test_contexts_job_does_not_slow_the_per_pr_coverage_leg",
    "test_contexts_databases_are_portable_between_machines",
    "test_release_branch_core_floor_lane_uses_published_floor",
    "test_ci_does_not_invoke_plugin_release_dependency_floor",
    "test_ci_and_publish_never_invoke_the_testpypi_drill",
    "test_ci_and_master_gate_never_run_the_diff_scoped_test_lane",
    "test_visual_suite_runs_only_in_dedicated_job",
    "test_ace_page_group_isolation_job_runs_dedicated_lane",
    "test_perf_floors_job_runs_slow_lane",
    "test_docs_build_once_per_event_and_deploys_are_serialized",
    "test_ci_workflow_no_longer_contains_the_telemetry_lanes",
    "test_core_artifact_consumer_jobs_run_just_recipes_after_setup",
    "test_prepare_job_rejects_invalid_source_version_manifest_combinations",
    "test_sase_checkouts_thread_the_explicit_ref_input",
    "test_setup_sase_asserts_expected_core_version_in_published_mode",
    "test_blocking_jobs_report_qualification_evidence_unconditionally",
    "test_test_commands_and_plugin_activation_stay_reporting_only",
    "test_advisory_jobs_still_run_for_qualification",
    "ARTIFACT_PREFIX",
    "CORE_ARTIFACT_CONSUMER_JOBS",
    "Path",
    "REPO_ROOT",
    "SHARD_TIMINGS_ARTIFACT_NAME",
    "pytest",
    "pytestmark",
    "yaml",
]
