"""Run-loop, signal, close, and install tests for the release watcher.

Split from ``tests.test_release_watch``; the focused modules below are re-exported
so the original import path keeps working. This facade collects no tests itself.
"""

from __future__ import annotations

from tests._release_watch_helpers import (
    NOW as NOW,
    SHA as SHA,
    FakeClock,
    FakeSignals as FakeSignals,
    Reader as Reader,
    engine as engine,
    fake_process as fake_process,
    options as options,
    pr as pr,
    run as run,
    run_payload as run_payload,
    signal_values as signal_values,
    watch as watch,
)
from tests.test_release_watch_lifecycle_close import (
    bead_aware_process as bead_aware_process,
    closed_read_output as closed_read_output,
    open_read_output as open_read_output,
    test_already_closed_bead_exits_without_watching,
    test_close_retries_three_times_and_waits_between_attempts,
    test_close_retry_stops_when_bead_closes_elsewhere,
    test_close_skipped_when_bead_already_closed,
    test_idempotent_close_check_fails_open_on_error,
)
from tests.test_release_watch_lifecycle_install import (
    inventory_json as inventory_json,
    test_install_attempt_rejects_core_below_configured_minimum,
    test_install_attempt_rejects_invalid_host_inventory,
    test_install_attempt_rejects_subprocess_failure,
    test_install_attempt_uses_fresh_venv_and_records_core_version,
    test_once_preflight_prints_one_state_and_close_argv_without_running_it,
)
from tests.test_release_watch_lifecycle_run import (
    test_deadline_and_startup_failure_verdicts,
    test_deadline_while_awaiting_core,
    test_repeated_malformed_completed_reads_close_broken,
    test_three_consecutive_malformed_reads_write_broken_verdict,
)
from tests.test_release_watch_lifecycle_signals import (
    test_polling_sigterm_restores_handlers,
    test_signal_during_close_retry_starts_detached_closer,
    test_sigterm_detaches_closer_with_stopped_verdict,
    test_sigterm_then_group_sigkill_still_closes_bead,
    test_startup_sigterm_is_stopped_and_restores_handlers,
)

__test__ = False

__all__ = [
    "FakeClock",
    "FakeSignals",
    "test_already_closed_bead_exits_without_watching",
    "test_close_retries_three_times_and_waits_between_attempts",
    "test_close_retry_stops_when_bead_closes_elsewhere",
    "test_close_skipped_when_bead_already_closed",
    "test_deadline_and_startup_failure_verdicts",
    "test_deadline_while_awaiting_core",
    "test_idempotent_close_check_fails_open_on_error",
    "test_install_attempt_uses_fresh_venv_and_records_core_version",
    "test_install_attempt_rejects_core_below_configured_minimum",
    "test_install_attempt_rejects_invalid_host_inventory",
    "test_install_attempt_rejects_subprocess_failure",
    "test_once_preflight_prints_one_state_and_close_argv_without_running_it",
    "test_polling_sigterm_restores_handlers",
    "test_repeated_malformed_completed_reads_close_broken",
    "test_signal_during_close_retry_starts_detached_closer",
    "test_sigterm_detaches_closer_with_stopped_verdict",
    "test_sigterm_then_group_sigkill_still_closes_bead",
    "test_startup_sigterm_is_stopped_and_restores_handlers",
    "test_three_consecutive_malformed_reads_write_broken_verdict",
]
