"""Tests for verified axe restart orchestration and desired state."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.config import AxeConfig, LumberjackConfig
from sase.axe._process_restart import _verify_startup
from sase.axe.desired_state import read_desired_state, write_desired_state
from sase.axe.lifecycle_journal import read_recent_lifecycle_events
from sase.axe.process import AxeStartResult, restart_axe_daemon_result
from sase.axe.state import LumberjackStatus


pytestmark = pytest.mark.usefixtures("allow_axe_lifecycle_in_tests")


def _config() -> AxeConfig:
    return AxeConfig(
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                description="Run restart test checks",
                interval=5,
            ),
        }
    )


def test_desired_state_round_trip(tmp_path: Path) -> None:
    state_dir = tmp_path / "axe"
    with patch("sase.axe.state.axe_state_dir", return_value=state_dir):
        running = write_desired_state(
            "running",
            source="test-start",
            timestamp="2026-07-19T12:00:00-04:00",
        )
        assert read_desired_state() == running

        stopped = write_desired_state(
            "stopped",
            source="test-stop",
            timestamp="2026-07-19T12:01:00-04:00",
        )
        assert read_desired_state() == stopped


def test_restart_records_running_before_stop_and_retries_start(tmp_path: Path) -> None:
    state_dir = tmp_path / "axe"
    observed_during_stop: list[str] = []
    delays: list[float] = []

    def _stop(**_kwargs: object) -> object:
        marker = read_desired_state()
        assert marker is not None
        observed_during_stop.append(marker.state)
        return object()

    with (
        patch("sase.axe.state.axe_state_dir", return_value=state_dir),
        patch(
            "sase.axe._process_restart.stop_axe_daemon_result",
            side_effect=_stop,
        ) as stop,
        patch(
            "sase.axe._process_restart.start_axe_daemon_result",
            side_effect=[
                AxeStartResult(status="blocked", message="old lock held"),
                AxeStartResult(status="started", pid=2468, message="started"),
            ],
        ) as start,
        patch(
            "sase.axe._process_restart._verify_startup",
            return_value=(True, None),
        ) as verify,
        patch(
            "sase.axe._process_restart._heartbeat_snapshot",
            return_value=(100, "old"),
        ),
    ):
        result = restart_axe_daemon_result(
            _config(),
            sleep_fn=delays.append,
            desired_state_source="sase update",
        )
        marker = read_desired_state()
        journal = read_recent_lifecycle_events(limit=0)

    assert result.succeeded is True
    assert result.verified is True
    assert result.pid == 2468
    assert [attempt.status for attempt in result.attempts] == ["blocked", "started"]
    assert observed_during_stop == ["running"]
    assert stop.call_count == 1
    assert start.call_count == 2
    assert delays == [0.25]
    verify.assert_called_once()
    assert marker is not None
    assert marker.state == "running"
    assert marker.source == "sase update"
    assert stop.call_args.kwargs == {
        "desired_state_source": "sase update",
        "record_desired_state": False,
    }
    assert all(
        call.kwargs["desired_state_source"] == "sase update"
        for call in start.call_args_list
    )
    assert journal[-1]["event"] == "restart"
    assert journal[-1]["outcome"] == "restarted"
    assert journal[-1]["source"] == "sase update"
    assert journal[-1]["orchestrator_pid"] == 2468


def test_restart_failure_is_journaled_and_notified(tmp_path: Path) -> None:
    state_dir = tmp_path / "axe"
    failures = [
        AxeStartResult(status="blocked", message="lock held"),
        AxeStartResult(status="failed", message="spawn failed"),
        AxeStartResult(status="failed", message="pid was not published"),
    ]
    delays: list[float] = []

    with (
        patch("sase.axe.state.axe_state_dir", return_value=state_dir),
        patch("sase.axe._process_restart.stop_axe_daemon_result"),
        patch(
            "sase.axe._process_restart.start_axe_daemon_result",
            side_effect=failures,
        ),
        patch(
            "sase.axe._process_restart._heartbeat_snapshot",
            return_value=(100, "old"),
        ),
        patch("sase.axe._process_restart.append_error") as append_error,
        patch("sase.notifications.senders.notify_axe_restart_failed") as notify_failed,
    ):
        result = restart_axe_daemon_result(
            _config(),
            sleep_fn=delays.append,
        )

    assert result.status == "failed"
    assert result.pid is None
    assert len(result.attempts) == 3
    assert delays == [0.25, 0.5]
    append_error.assert_called_once()
    error = append_error.call_args.args[0]
    assert error["job"] == "restart"
    assert "3 attempt(s)" in error["error"]
    notify_failed.assert_called_once()
    assert "pid was not published" in notify_failed.call_args.args[0]


def test_restart_verification_requires_advancing_heartbeats() -> None:
    fresh_status = LumberjackStatus(
        name="hooks",
        pid=99,
        started_at="2026-07-19T12:00:01-04:00",
        status="running",
        interval=5,
        last_cycle="2026-07-19T12:00:01-04:00",
    )
    with (
        patch("sase.axe._process_restart.get_axe_pid", return_value=99),
        patch(
            "sase.axe._process_restart.read_lumberjack_status",
            return_value=fresh_status,
        ),
    ):
        verified, error = _verify_startup(
            99,
            lumberjack_names=("hooks",),
            heartbeat_baseline={"hooks": (98, "2026-07-19T12:00:00-04:00")},
            timeout=0.0,
            sleep_fn=lambda _delay: None,
            monotonic_fn=lambda: 0.0,
        )

    assert verified is True
    assert error is None

    stale_status = LumberjackStatus(
        name="hooks",
        pid=99,
        started_at="2026-07-19T12:00:00-04:00",
        status="running",
        interval=5,
        last_cycle="2026-07-19T12:00:00-04:00",
    )
    with (
        patch("sase.axe._process_restart.get_axe_pid", return_value=99),
        patch(
            "sase.axe._process_restart.read_lumberjack_status",
            return_value=stale_status,
        ),
    ):
        verified, error = _verify_startup(
            99,
            lumberjack_names=("hooks",),
            heartbeat_baseline={"hooks": (99, "2026-07-19T12:00:00-04:00")},
            timeout=0.0,
            sleep_fn=lambda _delay: None,
            monotonic_fn=lambda: 0.0,
        )

    assert verified is False
    assert error == "timed out waiting for fresh heartbeats: hooks"
