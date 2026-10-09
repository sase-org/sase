"""PyPI execution pipeline: hermetic end-to-end runs plus unit coverage.

Split facade: the tests now live in ``test_run_pypi_flow``,
``test_run_pypi_lifecycle``, and ``test_run_pypi_verify``, with shared
fakes in ``_run_pypi_harness``. This module re-exports the public names
so the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.sase_install._run_pypi_harness import (
    FAKE_SASE,
    FAKE_TOOL_PYTHON,
    FAKE_UV,
    Harness,
)
from tests.sase_install.test_run_pypi_flow import (
    test_advisory_runners_warn_but_do_not_block,
    test_explicit_python_request_wins_over_pin,
    test_lock_contention_times_out_naming_holder,
    test_lock_path_and_holder_match_sase,
    test_overrides_written_only_when_editables_remain,
    test_pypi_run_success_end_to_end,
    test_swap_argv_pins_existing_interpreter,
    test_swap_failure_prints_restore_command,
)
from tests.sase_install.test_run_pypi_lifecycle import (
    test_force_reinstalls_when_current,
    test_json_reports_failure_with_error,
    test_json_reports_success_with_log_path,
    test_noop_skipped_when_health_fails,
    test_noop_when_current_and_healthy,
    test_quiet_prints_only_the_summary,
    test_scheduler_restart_failure_warns_without_failing,
    test_scheduler_restart_runs_when_scheduler_is_live,
    test_scheduler_restart_skipped_when_idle,
)
from tests.sase_install.test_run_pypi_verify import (
    test_backup_restore_names_editable_rebuild,
    test_fresh_install_suggests_missing_plugins,
    test_missing_plugin_probe_error_prints_nothing,
    test_mixed_agrees_when_keeping_an_editable_plugin,
    test_path_shadow_is_warning_only,
    test_progress_plain_quiet_and_live,
    test_swap_argv_for_fresh_env_takes_uv_default,
    test_update_disagreement_is_warning_only,
    test_update_timeout_is_warning_only,
    test_verify_failure_blocks_the_install,
)

__test__ = False

__all__ = [
    "FAKE_SASE",
    "FAKE_TOOL_PYTHON",
    "FAKE_UV",
    "Harness",
    "test_advisory_runners_warn_but_do_not_block",
    "test_backup_restore_names_editable_rebuild",
    "test_explicit_python_request_wins_over_pin",
    "test_force_reinstalls_when_current",
    "test_fresh_install_suggests_missing_plugins",
    "test_json_reports_failure_with_error",
    "test_json_reports_success_with_log_path",
    "test_lock_contention_times_out_naming_holder",
    "test_lock_path_and_holder_match_sase",
    "test_missing_plugin_probe_error_prints_nothing",
    "test_mixed_agrees_when_keeping_an_editable_plugin",
    "test_noop_skipped_when_health_fails",
    "test_noop_when_current_and_healthy",
    "test_overrides_written_only_when_editables_remain",
    "test_path_shadow_is_warning_only",
    "test_progress_plain_quiet_and_live",
    "test_pypi_run_success_end_to_end",
    "test_quiet_prints_only_the_summary",
    "test_scheduler_restart_failure_warns_without_failing",
    "test_scheduler_restart_runs_when_scheduler_is_live",
    "test_scheduler_restart_skipped_when_idle",
    "test_swap_argv_for_fresh_env_takes_uv_default",
    "test_swap_argv_pins_existing_interpreter",
    "test_swap_failure_prints_restore_command",
    "test_update_disagreement_is_warning_only",
    "test_update_timeout_is_warning_only",
    "test_verify_failure_blocks_the_install",
]
