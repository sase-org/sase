"""Tests for the reusable child-supervision library."""

import io
import os
import signal
import subprocess
import threading
from unittest.mock import MagicMock, patch

from sase.supervision.logs import pump_output
from sase.supervision.restart import (
    RestartPolicy,
    RestartState,
    record_started,
    schedule_restart,
)
from sase.service.restart import (
    ServiceRestartDecision,
    ServiceRestartHistory,
    ServiceRestartTuning,
)
from sase.supervision.termination import send_sigterm, wait_with_escalation


def _policy(**overrides: float | int) -> RestartPolicy:
    defaults: dict[str, float | int] = {
        "initial_backoff_seconds": 1.0,
        "healthy_run_seconds": 300.0,
        "max_backoff_seconds": 60.0,
        "crash_loop_window_seconds": 60.0,
        "crash_loop_failure_threshold": 3,
    }
    defaults.update(overrides)
    return RestartPolicy(**defaults)  # type: ignore[arg-type]


# --- restart state / backoff ---


def test_record_started_clears_pending_retry_state() -> None:
    state = RestartState(restart_at=5.0, last_exit_code=1)

    record_started(state, now=10.0)

    assert state.started_at == 10.0
    assert state.restart_at is None
    assert state.last_exit_code is None


def test_schedule_restart_delegates_to_core_restart_facade() -> None:
    state = RestartState(
        started_at=10.0,
        backoff_seconds=2.0,
        consecutive_failures=2,
        last_exit_code=99,
    )
    failures = state.recent_failures
    failures.extend([11.0, 12.0])
    policy = _policy(
        initial_backoff_seconds=1.5,
        healthy_run_seconds=120.0,
        max_backoff_seconds=8.0,
        crash_loop_window_seconds=30.0,
        crash_loop_failure_threshold=4,
    )
    decision = ServiceRestartDecision(
        schema_version=1,
        action="restart",
        clean_exit=False,
        delay_seconds=4.0,
        restart_at=24.0,
        reason="test decision",
        crash_loop=True,
        notify=True,
        history=ServiceRestartHistory(
            started_at=None,
            backoff_seconds=4.0,
            consecutive_failures=3,
            recent_failures=(12.0, 20.0),
            alert_sent=True,
        ),
    )

    with patch(
        "sase.supervision.restart.decide_service_restart",
        return_value=decision,
    ) as decide_restart:
        triggered = schedule_restart(state, policy, now=20.0, exit_code=7)

    assert triggered is True
    decide_restart.assert_called_once()
    args, kwargs = decide_restart.call_args
    assert args[0] == "always"
    assert args[1].exit_code == 7
    assert args[2] == ServiceRestartHistory(
        started_at=10.0,
        backoff_seconds=2.0,
        consecutive_failures=2,
        recent_failures=(11.0, 12.0),
        alert_sent=False,
    )
    assert kwargs == {
        "now": 20.0,
        "tuning": ServiceRestartTuning(
            initial_backoff_seconds=1.5,
            max_backoff_seconds=8.0,
            healthy_run_seconds=120.0,
            crash_loop_window_seconds=30.0,
            crash_loop_threshold=4,
        ),
    }
    assert state.started_at is None
    assert state.restart_at == 24.0
    assert state.backoff_seconds == 4.0
    assert state.consecutive_failures == 3
    assert state.recent_failures is failures
    assert list(state.recent_failures) == [12.0, 20.0]
    assert state.last_exit_code == 7
    assert state.alert_sent is True


def test_schedule_restart_uses_capped_exponential_backoff() -> None:
    state = RestartState()
    policy = _policy(max_backoff_seconds=4.0)

    schedule_restart(state, policy, now=0.0, exit_code=1)
    assert state.backoff_seconds == 1.0
    assert state.restart_at == 1.0

    schedule_restart(state, policy, now=1.0, exit_code=1)
    assert state.backoff_seconds == 2.0

    schedule_restart(state, policy, now=3.0, exit_code=1)
    assert state.backoff_seconds == 4.0

    schedule_restart(state, policy, now=7.0, exit_code=1)
    assert state.backoff_seconds == 4.0  # held at the ceiling


def test_schedule_restart_resets_after_healthy_run() -> None:
    state = RestartState(
        started_at=0.0,
        backoff_seconds=60.0,
        consecutive_failures=8,
        alert_sent=True,
    )
    state.recent_failures.extend([1.0, 2.0, 3.0])
    policy = _policy(healthy_run_seconds=300.0)

    schedule_restart(state, policy, now=301.0, exit_code=7)

    assert state.backoff_seconds == 1.0
    assert state.restart_at == 302.0
    assert state.consecutive_failures == 1
    assert list(state.recent_failures) == [301.0]
    assert state.last_exit_code == 7
    assert state.alert_sent is False


def test_schedule_restart_reports_crash_loop_once_per_episode() -> None:
    state = RestartState()
    policy = _policy(crash_loop_window_seconds=60.0, crash_loop_failure_threshold=3)

    triggered = [
        schedule_restart(state, policy, now=now, exit_code=1)
        for now in (0.0, 10.0, 20.0, 30.0)
    ]

    assert triggered == [False, False, True, False]
    assert state.alert_sent is True


def test_schedule_restart_expires_old_failures_outside_window() -> None:
    state = RestartState()
    policy = _policy(crash_loop_window_seconds=60.0, crash_loop_failure_threshold=3)

    schedule_restart(state, policy, now=0.0, exit_code=1)
    schedule_restart(state, policy, now=10.0, exit_code=1)
    triggered = schedule_restart(state, policy, now=100.0, exit_code=1)

    assert triggered is False
    assert list(state.recent_failures) == [100.0]


# --- bounded log pump ---


def test_pump_output_appends_each_chunk_and_closes_stream() -> None:
    stream = io.BytesIO(b"hello world")
    chunks: list[bytes] = []

    pump_output(stream, chunks.append)

    assert chunks == [b"hello world"]
    assert stream.closed


def test_pump_output_flushes_available_pipe_bytes_before_eof() -> None:
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "rb", buffering=64 * 1024)
    appended = threading.Event()
    chunks: list[bytes] = []

    def capture(chunk: bytes) -> None:
        chunks.append(chunk)
        appended.set()

    thread = threading.Thread(target=pump_output, args=(stream, capture))
    thread.start()
    os.write(write_fd, b"partial\n")
    flushed_before_eof = appended.wait(timeout=1)
    os.close(write_fd)
    thread.join(timeout=1)

    assert flushed_before_eof
    assert not thread.is_alive()
    assert chunks == [b"partial\n"]


# --- SIGTERM -> SIGKILL escalation ---


def test_send_sigterm_signals_only_live_children() -> None:
    live = MagicMock()
    live.pid = 100
    live.poll.return_value = None
    dead = MagicMock()
    dead.pid = 200
    dead.poll.return_value = 0

    with patch("os.kill") as mock_kill:
        send_sigterm({"live": live, "dead": dead})

    mock_kill.assert_called_once_with(100, signal.SIGTERM)


def test_send_sigterm_swallows_lookup_and_permission_errors() -> None:
    proc = MagicMock()
    proc.pid = 100
    proc.poll.return_value = None

    with patch("os.kill", side_effect=ProcessLookupError):
        send_sigterm({"proc": proc})  # must not raise


def test_wait_with_escalation_does_not_kill_a_prompt_exit() -> None:
    proc = MagicMock()
    proc.wait.return_value = 0

    wait_with_escalation({"proc": proc}, term_timeout=1, kill_timeout=1)

    proc.wait.assert_called_once()
    proc.kill.assert_not_called()


def test_wait_with_escalation_kills_stragglers_after_term_timeout() -> None:
    proc = MagicMock()
    proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="x", timeout=0), 0]

    wait_with_escalation({"proc": proc}, term_timeout=0, kill_timeout=1)

    proc.kill.assert_called_once()
    assert proc.wait.call_count == 2
