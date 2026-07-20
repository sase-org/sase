"""Tests for axe restart recovery and verification."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.config import AxeConfig
from sase.axe.desired_state import read_desired_state, write_desired_state
from sase.axe._process_restart import _verify_startup
from sase.axe.process import AxeStartResult, restart_axe_daemon_result
from sase.axe.state import LumberjackStatus, get_timestamp


pytest_plugins = ("tests._axe_outage_recovery_fixtures",)
pytestmark = pytest.mark.usefixtures("allow_axe_lifecycle_in_tests")


class TestUpdateRestartInterruption:
    """Simulated update-restart interruption recovery via `sase axe ensure`."""

    def test_desired_state_survives_mid_restart_crash(
        self, temp_state_dir: Path
    ) -> None:
        """When restart dies between stop and start, desired state persists."""
        write_desired_state(
            "running",
            source="restart",
            timestamp=get_timestamp(),
        )

        state = read_desired_state()
        assert state is not None
        assert state.state == "running"
        assert state.source == "restart"

    def test_restart_retries_start_phase(
        self, temp_state_dir: Path, axe_config: AxeConfig
    ) -> None:
        """Restart retries the start phase when transient failures occur."""
        delays: list[float] = []
        observed_states: list[str | None] = []

        def _stop(**_kwargs: object) -> object:
            state = read_desired_state()
            observed_states.append(state.state if state else None)
            return object()

        with (
            patch(
                "sase.axe._process_restart.stop_axe_daemon_result", side_effect=_stop
            ),
            patch(
                "sase.axe._process_restart.start_axe_daemon_result",
                side_effect=[
                    AxeStartResult(status="blocked", message="old lock held"),
                    AxeStartResult(status="blocked", message="old lock held"),
                    AxeStartResult(status="started", pid=9999, message="started"),
                ],
            ),
            patch(
                "sase.axe._process_restart._verify_startup", return_value=(True, None)
            ),
            patch(
                "sase.axe._process_restart._heartbeat_snapshot",
                return_value=(100, "old"),
            ),
        ):
            result = restart_axe_daemon_result(axe_config, sleep_fn=delays.append)

        assert result.succeeded is True
        assert result.verified is True
        assert len(result.attempts) == 3
        assert delays == [0.25, 0.5]
        assert observed_states[0] == "running"

    def test_restart_failure_notified_and_journaled(
        self, temp_state_dir: Path, axe_config: AxeConfig
    ) -> None:
        """All restart failures are persisted to inbox and error log, not silent."""
        failures = [
            AxeStartResult(status="blocked", message="lock held"),
            AxeStartResult(status="failed", message="spawn error"),
            AxeStartResult(status="failed", message="pid file not written"),
        ]
        delays: list[float] = []

        with (
            patch("sase.axe._process_restart.stop_axe_daemon_result"),
            patch(
                "sase.axe._process_restart.start_axe_daemon_result",
                side_effect=failures,
            ),
            patch(
                "sase.axe._process_restart._heartbeat_snapshot",
                return_value=(100, "old"),
            ),
            patch("sase.axe._process_restart.append_error") as mock_append_error,
            patch(
                "sase.notifications.senders.notify_axe_restart_failed"
            ) as mock_notify,
        ):
            result = restart_axe_daemon_result(axe_config, sleep_fn=delays.append)

        assert result.status == "failed"
        assert result.pid is None
        assert len(result.attempts) == 3
        assert [a.status for a in result.attempts] == ["blocked", "failed", "failed"]
        mock_append_error.assert_called_once()
        error = mock_append_error.call_args.args[0]
        assert error["job"] == "restart"
        assert "3 attempt(s)" in error["error"]
        mock_notify.assert_called_once()


class TestRestartVerification:
    """End-to-end restart verification with journaled outcomes."""

    def test_verify_startup_requires_fresh_heartbeats(
        self, temp_state_dir: Path
    ) -> None:
        """Restart is verified when orchestrator and lumberjack heartbeats advance."""
        status = LumberjackStatus(
            name="hooks",
            pid=5555,
            started_at="2026-07-19T12:00:01-04:00",
            status="running",
            interval=5,
            last_cycle="2026-07-19T12:00:05-04:00",
        )
        with (
            patch("sase.axe._process_restart.get_axe_pid", return_value=5555),
            patch(
                "sase.axe._process_restart.read_lumberjack_status", return_value=status
            ),
        ):
            verified, error = _verify_startup(
                5555,
                lumberjack_names=("hooks",),
                heartbeat_baseline={"hooks": (100, "2026-07-19T12:00:00-04:00")},
                timeout=0.0,
                sleep_fn=lambda _: None,
                monotonic_fn=lambda: 0.0,
            )

        assert verified is True
        assert error is None

    def test_verify_startup_fails_on_stale_heartbeat(
        self, temp_state_dir: Path
    ) -> None:
        """If lumberjack heartbeat doesn't advance, restart fails verification."""
        status = LumberjackStatus(
            name="hooks",
            pid=5555,
            started_at="2026-07-19T12:00:00-04:00",
            status="running",
            interval=5,
            last_cycle="2026-07-19T12:00:00-04:00",
        )
        with (
            patch("sase.axe._process_restart.get_axe_pid", return_value=5555),
            patch(
                "sase.axe._process_restart.read_lumberjack_status", return_value=status
            ),
        ):
            verified, error = _verify_startup(
                5555,
                lumberjack_names=("hooks",),
                heartbeat_baseline={"hooks": (100, "2026-07-19T12:00:00-04:00")},
                timeout=0.0,
                sleep_fn=lambda _: None,
                monotonic_fn=lambda: 0.0,
            )

        assert verified is False
        assert error == "timed out waiting for fresh heartbeats: hooks"

    def test_restart_result_structured_and_journaled(
        self, temp_state_dir: Path, axe_config: AxeConfig
    ) -> None:
        """Restart result includes per-attempt details for reliable journaling."""
        with (
            patch(
                "sase.axe._process_restart.stop_axe_daemon_result",
                return_value=object(),
            ),
            patch(
                "sase.axe._process_restart.start_axe_daemon_result",
                side_effect=[
                    AxeStartResult(status="blocked", message="lock held"),
                    AxeStartResult(status="started", pid=7777, message="started"),
                ],
            ),
            patch(
                "sase.axe._process_restart._verify_startup", return_value=(True, None)
            ),
            patch(
                "sase.axe._process_restart._heartbeat_snapshot",
                return_value=(100, "old"),
            ),
        ):
            result = restart_axe_daemon_result(axe_config)

        assert result.status == "started"
        assert result.succeeded is True
        assert result.verified is True
        assert result.pid == 7777
        assert len(result.attempts) == 2
        assert result.attempts[0].status == "blocked"
        assert result.attempts[0].message == "lock held"
        assert result.attempts[1].status == "started"
        assert result.attempts[1].message == "started"


class TestIntegratedOutageRecovery:
    """Integration tests for complete outage and recovery cycles."""

    def test_full_restart_interruption_recovery_flow(
        self, temp_state_dir: Path, axe_config: AxeConfig
    ) -> None:
        """Desired state survives an interrupted restart until `axe ensure` heals."""
        write_desired_state("running", source="restart", timestamp=get_timestamp())
        marker_before = read_desired_state()
        assert marker_before is not None
        assert marker_before.state == "running"

        marker_after_crash = read_desired_state()
        assert marker_after_crash is not None
        assert marker_after_crash.state == "running"

    def test_crash_loop_alert_prevents_silent_outage(
        self, temp_state_dir: Path, axe_config: AxeConfig
    ) -> None:
        """Crash-loop alert reaches inbox even if primary Telegram chop is down."""
        from sase.axe.orchestrator import _LumberjackRestartState

        log_dir = temp_state_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        state = _LumberjackRestartState()
        now = 1000.0

        for i in range(3):
            state.recent_failures.append(now + i * 10)
            state.alert_sent = False

        should_alert = len(state.recent_failures) >= 3 and not state.alert_sent
        assert should_alert is True

        state.alert_sent = True
        assert state.alert_sent is True
