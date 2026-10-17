"""Public facade for check-mode screenshot recapture tests."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from pathlib import Path

from tests._fix_tui_screenshots_helpers import (
    ACE_NODE,
    PAGER_NODE,
    AttemptScript,
    FakeRunner,
    ScriptedCapture,
    commit_all,
    git_index,
    init_repo,
    make_png,
    silent_hooks,
    write_golden,
)
from tests.ace.tui.visual._visual_capture import InventoryReport
from tests.ace.tui.visual._visual_maintenance import (
    EXIT_DRIFT,
    EXIT_FAILURE,
    EXIT_SUCCESS,
    MaintenanceHooks,
    main,
)
from tests.ace.tui.visual._visual_maintenance_cli import RECAPTURE_BUDGET_ENV
from tests.ace.tui.visual._visual_maintenance_verify import (
    CHECK_RECAPTURE_NODE_LIMIT,
    FIRST_ATTEMPT_DIFFS_DIRNAME,
    check_mode_strict_errors,
)

from tests._test_fix_tui_screenshots_check_recapture_basic import (
    test_check_fails_every_attempt_exits_drift,
    test_check_first_pass_match_does_not_recapture,
    test_check_over_cap_pytest_failures_exit_failure,
    test_check_over_cap_skips_recapture_on_systemic_drift,
    test_check_persistent_test_failure_exits_failure,
    test_check_recovered_node_does_not_hide_skipped_node,
    test_check_recovered_node_does_not_hide_uninventoried_node,
    test_check_retry_match_is_unstable_and_does_not_write,
)
from tests._test_fix_tui_screenshots_check_recapture_retry import (
    test_check_broken_retry_cannot_cure_first_pass,
    test_check_budget_env_zero_skips_recapture,
    test_check_budget_exhaustion_keeps_first_pass_and_writes_manifest,
    test_check_budget_expires_between_retries_keeps_first_pass,
    test_check_exit_disagreement_recovery_still_fails,
    test_check_internal_error_recovery_still_fails,
    test_check_only_broken_retry_leaves_node_unrecovered,
    test_check_ordinary_failure_recovery_stays_clean,
    test_check_protocol_broken_retry_cannot_cure_first_pass,
    test_check_targeted_recapture_ignores_missing_root,
    test_check_timed_out_retry_keeps_first_pass_and_writes_manifest,
    test_check_timed_out_retry_preserves_unrecovered_first_pass_failure,
)
from tests._test_fix_tui_screenshots_check_recapture_strict import (
    test_strict_flags_collection_mismatch_and_unexpected_worker,
    test_strict_flags_exit_disagreement,
    test_strict_flags_internal_error_and_child_exit,
    test_strict_flags_skipped_nodes_and_protocol_errors,
    test_strict_ignores_cured_failure_and_ordinary_session_status,
    test_strict_keeps_uncured_failed_node,
    test_strict_targeted_scope_ignores_missing_root,
)

SKIP_NODE = "tests/ace/tui/visual/test_c.py::test_c"
UNINVENTORIED_NODE = "tests/ace/tui/visual/test_d.py::test_d"

__all__ = (
    "dataclasses",
    "json",
    "Sequence",
    "Path",
    "ACE_NODE",
    "PAGER_NODE",
    "AttemptScript",
    "FakeRunner",
    "ScriptedCapture",
    "commit_all",
    "git_index",
    "init_repo",
    "make_png",
    "silent_hooks",
    "write_golden",
    "InventoryReport",
    "EXIT_DRIFT",
    "EXIT_FAILURE",
    "EXIT_SUCCESS",
    "MaintenanceHooks",
    "main",
    "RECAPTURE_BUDGET_ENV",
    "CHECK_RECAPTURE_NODE_LIMIT",
    "FIRST_ATTEMPT_DIFFS_DIRNAME",
    "check_mode_strict_errors",
    "SKIP_NODE",
    "UNINVENTORIED_NODE",
    "test_check_broken_retry_cannot_cure_first_pass",
    "test_check_budget_env_zero_skips_recapture",
    "test_check_budget_exhaustion_keeps_first_pass_and_writes_manifest",
    "test_check_budget_expires_between_retries_keeps_first_pass",
    "test_check_exit_disagreement_recovery_still_fails",
    "test_check_fails_every_attempt_exits_drift",
    "test_check_first_pass_match_does_not_recapture",
    "test_check_internal_error_recovery_still_fails",
    "test_check_only_broken_retry_leaves_node_unrecovered",
    "test_check_ordinary_failure_recovery_stays_clean",
    "test_check_over_cap_pytest_failures_exit_failure",
    "test_check_over_cap_skips_recapture_on_systemic_drift",
    "test_check_persistent_test_failure_exits_failure",
    "test_check_protocol_broken_retry_cannot_cure_first_pass",
    "test_check_recovered_node_does_not_hide_skipped_node",
    "test_check_recovered_node_does_not_hide_uninventoried_node",
    "test_check_retry_match_is_unstable_and_does_not_write",
    "test_check_targeted_recapture_ignores_missing_root",
    "test_check_timed_out_retry_keeps_first_pass_and_writes_manifest",
    "test_check_timed_out_retry_preserves_unrecovered_first_pass_failure",
    "test_strict_flags_collection_mismatch_and_unexpected_worker",
    "test_strict_flags_exit_disagreement",
    "test_strict_flags_internal_error_and_child_exit",
    "test_strict_flags_skipped_nodes_and_protocol_errors",
    "test_strict_ignores_cured_failure_and_ordinary_session_status",
    "test_strict_keeps_uncured_failed_node",
    "test_strict_targeted_scope_ignores_missing_root",
)
