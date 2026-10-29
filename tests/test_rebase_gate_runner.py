"""Subprocess tests for the after-rebase gate runner.

The Rust policy matrix itself is covered by sase-core tests; these tests
prove the runner's job: project-scoped configuration, bounded process
execution with group teardown, capped evidence, fail-open errors, and exact
delegation of command facts plus the checker's report to the facade.

Test implementations live in private split modules; this module is a facade
preserving the historic import path.
"""

from __future__ import annotations

from tests._rebase_gate_runner_config import (
    test_config_load_failure_warns,
    test_configuration_is_isolated_between_project_roots,
    test_disabled_hook_launches_no_process,
    test_facade_failure_warns_and_keeps_evidence,
    test_invalid_timeout_is_preflighted_before_context_git_queries,
    test_invalid_timeout_warns_without_launching,
    test_non_string_hook_warns_without_launching,
)
from tests._rebase_gate_runner_decisions import (
    test_clean_report_permits_push_and_delegates_exact_facts,
    test_crash_without_report_warns,
    test_error_report_warns_and_allows_push,
    test_findings_report_blocks_push,
    test_malformed_report_warns,
    test_oversize_report_is_dropped,
    test_stale_report_warns,
    test_unsupported_exit_status_warns,
)
from tests._rebase_gate_runner_execution import (
    test_cancellation_kills_and_reaps_hook_group,
    test_cleanup_failure_keeps_decision,
    test_excessive_output_is_bounded,
    test_failed_log_creation_warns_without_launching,
    test_one_budget_passes_decreasing_timeouts_and_stops_exhausted_work,
    test_signalled_hook_reports_signal,
    test_spawn_failure_warns,
    test_surviving_child_is_killed_after_group_leader_exits,
    test_timeout_kills_process_group_and_warns,
)
from tests._rebase_gate_runner_helpers import (
    FINDING_PATH as FINDING_PATH,
    HEAD as HEAD,
    TREE as TREE,
    GateHarness as GateHarness,
    harness as harness,
    make_context as make_context,
    make_report as make_report,
    write_checker as write_checker,
)

__all__ = [
    "FINDING_PATH",
    "GateHarness",
    "HEAD",
    "TREE",
    "harness",
    "make_context",
    "make_report",
    "test_cancellation_kills_and_reaps_hook_group",
    "test_clean_report_permits_push_and_delegates_exact_facts",
    "test_cleanup_failure_keeps_decision",
    "test_config_load_failure_warns",
    "test_configuration_is_isolated_between_project_roots",
    "test_crash_without_report_warns",
    "test_disabled_hook_launches_no_process",
    "test_error_report_warns_and_allows_push",
    "test_excessive_output_is_bounded",
    "test_facade_failure_warns_and_keeps_evidence",
    "test_failed_log_creation_warns_without_launching",
    "test_findings_report_blocks_push",
    "test_invalid_timeout_is_preflighted_before_context_git_queries",
    "test_invalid_timeout_warns_without_launching",
    "test_malformed_report_warns",
    "test_non_string_hook_warns_without_launching",
    "test_one_budget_passes_decreasing_timeouts_and_stops_exhausted_work",
    "test_oversize_report_is_dropped",
    "test_signalled_hook_reports_signal",
    "test_spawn_failure_warns",
    "test_stale_report_warns",
    "test_surviving_child_is_killed_after_group_leader_exits",
    "test_timeout_kills_process_group_and_warns",
    "test_unsupported_exit_status_warns",
    "write_checker",
]
