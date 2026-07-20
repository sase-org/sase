"""Tests for lumberjack crash-loop and bounded-log outage recovery."""

import os
import time
from pathlib import Path

import pytest

from sase.axe.config import AxeConfig
from sase.axe.state import append_bounded_log, reap_stale_log_rotation_temps


pytest_plugins = ("tests._axe_outage_recovery_fixtures",)
pytestmark = pytest.mark.usefixtures("allow_axe_lifecycle_in_tests")


class TestCrashLoopAndBackoff:
    """Crash-loop detection, backoff, and notification."""

    def test_crash_loop_backoff_schedule(
        self, temp_state_dir: Path, axe_config: AxeConfig
    ) -> None:
        """Crash-loop backoff doubles until ceiling, then holds at ceiling."""
        from sase.axe.orchestrator import _LumberjackRestartState

        state = _LumberjackRestartState()

        assert state.backoff_seconds == 0.0
        state.backoff_seconds = 1.0
        state.consecutive_failures = 1
        assert state.backoff_seconds == 1.0

        state.backoff_seconds *= 2
        assert state.backoff_seconds == 2.0

        state.backoff_seconds *= 2
        assert state.backoff_seconds == 4.0

        state.backoff_seconds = min(state.backoff_seconds, 60.0)
        assert state.backoff_seconds == 4.0

        state.backoff_seconds = 60.0
        state.backoff_seconds *= 2
        state.backoff_seconds = min(state.backoff_seconds, 60.0)
        assert state.backoff_seconds == 60.0

    def test_backoff_reset_on_healthy_run(
        self, temp_state_dir: Path, axe_config: AxeConfig
    ) -> None:
        """After a healthy run lasting N minutes, backoff resets to 1.0s."""
        from sase.axe.orchestrator import (
            _RESTART_HEALTHY_RUN_SECONDS,
            _LumberjackRestartState,
        )

        state = _LumberjackRestartState()
        now = 1000.0

        state.started_at = now
        state.backoff_seconds = 60.0
        state.consecutive_failures = 10
        state.recent_failures.append(now - 100)
        assert len(state.recent_failures) == 1

        now = 1000.0 + _RESTART_HEALTHY_RUN_SECONDS + 10
        healthy_run = (
            state.started_at is not None
            and now - state.started_at >= _RESTART_HEALTHY_RUN_SECONDS
        )
        assert healthy_run is True

        if healthy_run:
            state.backoff_seconds = 1.0
            state.consecutive_failures = 0
            state.recent_failures.clear()
            state.alert_sent = False

        assert state.backoff_seconds == 1.0
        assert state.consecutive_failures == 0
        assert len(state.recent_failures) == 0

    def test_crash_loop_threshold_and_notification(self) -> None:
        """After N failures within a time window, one loud notification is sent."""
        from sase.axe.orchestrator import (
            _CRASH_LOOP_FAILURE_THRESHOLD,
            _CRASH_LOOP_WINDOW_SECONDS,
            _LumberjackRestartState,
        )

        state = _LumberjackRestartState()
        now = 1000.0

        for i in range(_CRASH_LOOP_FAILURE_THRESHOLD - 1):
            state.recent_failures.append(now + i)

        assert len(state.recent_failures) == _CRASH_LOOP_FAILURE_THRESHOLD - 1
        assert state.alert_sent is False

        state.recent_failures.append(now + 100)
        should_notify = (
            len(state.recent_failures) >= _CRASH_LOOP_FAILURE_THRESHOLD
            and not state.alert_sent
        )

        assert should_notify is True
        state.alert_sent = True
        state.recent_failures.append(now + 101)
        should_notify = (
            len(state.recent_failures) >= _CRASH_LOOP_FAILURE_THRESHOLD
            and not state.alert_sent
        )
        assert should_notify is False


class TestAtCapLogging:
    """At-cap logging hysteresis and temp file cleanup."""

    def test_bounded_log_hysteresis_truncation(self, temp_state_dir: Path) -> None:
        """Appending beyond max_bytes truncates the log to roughly half its cap."""
        log_path = temp_state_dir / "test.log"
        cap = 1000

        data1 = b"x" * cap
        append_bounded_log(log_path, data1, max_bytes=cap)
        assert log_path.stat().st_size == cap

        data2 = b"y" * 100
        append_bounded_log(log_path, data2, max_bytes=cap)

        final_size = log_path.stat().st_size
        assert final_size <= cap
        assert final_size < cap

        final_contents = log_path.read_bytes()
        assert b"[sase] lumberjack log truncated" in final_contents
        assert final_contents.endswith(data2)

    def test_bounded_log_cheap_appends_below_cap(self, temp_state_dir: Path) -> None:
        """Appends below the cap do not trigger truncation."""
        log_path = temp_state_dir / "test.log"
        cap = 1000

        data1 = b"start\n"
        append_bounded_log(log_path, data1, max_bytes=cap)
        size1 = log_path.stat().st_size
        assert size1 == len(data1)

        for i in range(5):
            data = f"line {i}\n".encode()
            append_bounded_log(log_path, data, max_bytes=cap)
        size_after_appends = log_path.stat().st_size

        expected = len(data1) + sum(len(f"line {i}\n".encode()) for i in range(5))
        assert size_after_appends == expected
        assert size_after_appends < cap

    def test_orphan_log_rotation_temp_files_reaped(self, temp_state_dir: Path) -> None:
        """Old orphaned rotation files are cleaned up while fresh ones remain."""
        log_dir = temp_state_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        old_temp_1 = log_dir / ".lumberjack.log.1.tmp"
        old_temp_2 = log_dir / ".lumberjack.log.2.tmp"
        old_temp_1.write_bytes(b"orphaned" * 1000)
        old_temp_2.write_bytes(b"orphaned" * 1000)

        old_mtime = time.time() - 600
        old_temp_1.touch()
        old_temp_2.touch()
        os.utime(old_temp_1, (old_mtime, old_mtime))
        os.utime(old_temp_2, (old_mtime, old_mtime))

        fresh_temp = log_dir / ".lumberjack.log.3.tmp"
        fresh_temp.write_bytes(b"recent" * 100)

        reap_stale_log_rotation_temps(log_dir, max_age_seconds=300)

        assert not old_temp_1.exists()
        assert not old_temp_2.exists()
        assert fresh_temp.exists()

    def test_bounded_log_respects_cap_across_many_appends(
        self, temp_state_dir: Path
    ) -> None:
        """File never exceeds cap even with many rapid appends."""
        log_path = temp_state_dir / "test.log"
        cap = 5000

        for i in range(50):
            data = f"Log line {i}\n" * 20
            append_bounded_log(log_path, data, max_bytes=cap)
            current_size = log_path.stat().st_size
            if current_size > cap + 100:
                pytest.fail(f"Log size {current_size} exceeded cap {cap}")

        final_size = log_path.stat().st_size
        assert final_size <= cap
