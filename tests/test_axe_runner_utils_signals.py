"""SIGTERM handler and killed-state tests for axe runner utils.

Split from ``tests.test_axe_runner_utils``; the original module re-exports
these tests so its import path keeps working.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.runner_signals import (
    install_sigterm_handler,
    killed_at,
    reset_killed,
    was_killed,
)

__all__ = [
    "test_reset_killed_clears_timestamp",
    "test_sigterm_handler_can_be_rearmed",
    "test_sigterm_handler_contains_logging_failure",
    "test_sigterm_handler_hard_mode_exits_once",
    "test_sigterm_handler_ignores_nested_delivery",
    "test_sigterm_handler_repeated_delivery_is_a_noop",
    "test_sigterm_handler_runs_cleanup_callback",
    "test_sigterm_handler_sets_killed",
    "test_sigterm_handler_subprocess_survives_signal_burst",
    "test_sigterm_handler_writes_without_buffered_stderr",
]


def test_sigterm_handler_sets_killed() -> None:
    """Test that invoking the captured handler sets was_killed to True."""
    reset_killed()
    captured_handler = None

    with patch("sase.axe.runner_signals.signal.signal") as mock_signal:
        install_sigterm_handler("test")
        captured_handler = mock_signal.call_args[0][1]

    # Invoke the handler - it calls sys.exit, so we catch SystemExit
    with (
        patch("sase.axe.runner_signals.sys.exit"),
        patch("sase.axe.runner_signals.time.time", return_value=123.456),
    ):
        captured_handler(signal.SIGTERM, None)

    assert was_killed() is True
    assert killed_at() == 123.456
    # Reset state
    reset_killed()


def test_sigterm_handler_runs_cleanup_callback() -> None:
    """SIGTERM handlers can run best-effort cleanup before exiting."""
    reset_killed()
    cleanup = MagicMock()

    with patch("sase.axe.runner_signals.signal.signal") as mock_signal:
        install_sigterm_handler("test", on_signal=cleanup)
        captured_handler = mock_signal.call_args[0][1]

    with (
        patch("sase.axe.runner_signals.sys.exit"),
        patch("sase.axe.runner_signals.time.time", return_value=123.456),
    ):
        captured_handler(signal.SIGTERM, None)

    cleanup.assert_called_once_with()
    assert was_killed() is True
    reset_killed()


def test_sigterm_handler_ignores_nested_delivery() -> None:
    """A nested SIGTERM must not repeat cleanup or replace the first timestamp."""
    reset_killed()
    captured_handler = None
    cleanup = MagicMock()

    def cleanup_and_redeliver() -> None:
        cleanup()
        assert captured_handler is not None
        captured_handler(signal.SIGTERM, None)

    with patch("sase.axe.runner_signals.signal.signal") as mock_signal:
        install_sigterm_handler("test", soft=True, on_signal=cleanup_and_redeliver)
        captured_handler = mock_signal.call_args[0][1]

    with (
        patch("sase.axe.runner_signals.time.time", side_effect=[123.456, 999.0]) as now,
        patch("sase.axe.runner_signals.os.write"),
    ):
        captured_handler(signal.SIGTERM, None)

    cleanup.assert_called_once_with()
    assert now.call_count == 1
    assert killed_at() == 123.456
    reset_killed()


def test_sigterm_handler_repeated_delivery_is_a_noop() -> None:
    """A later SIGTERM writes one message and invokes cleanup only once."""
    reset_killed()
    cleanup = MagicMock()

    with patch("sase.axe.runner_signals.signal.signal") as mock_signal:
        install_sigterm_handler("test", soft=True, on_signal=cleanup)
        captured_handler = mock_signal.call_args[0][1]

    with patch("sase.axe.runner_signals.os.write") as write:
        captured_handler(signal.SIGTERM, None)
        captured_handler(signal.SIGTERM, None)

    assert write.call_count == 1
    assert write.call_args.args[1] == b"\nReceived SIGTERM - test was killed\n"
    cleanup.assert_called_once_with()
    reset_killed()


def test_sigterm_handler_writes_without_buffered_stderr() -> None:
    """The handler never calls write on the buffered stderr object."""
    reset_killed()
    stderr = MagicMock()
    stderr.fileno.return_value = 99
    stderr.write.side_effect = RuntimeError("reentrant call inside stderr")

    with patch("sase.axe.runner_signals.signal.signal") as mock_signal:
        install_sigterm_handler("test", soft=True)
        captured_handler = mock_signal.call_args[0][1]

    with (
        patch("sase.axe.runner_signals.sys.stderr", stderr),
        patch("sase.axe.runner_signals.os.write") as write,
    ):
        captured_handler(signal.SIGTERM, None)

    write.assert_called_once_with(99, b"\nReceived SIGTERM - test was killed\n")
    stderr.write.assert_not_called()
    reset_killed()


def test_sigterm_handler_hard_mode_exits_once() -> None:
    """Hard mode exits on the first signal and ignores a repeated one."""
    reset_killed()
    with patch("sase.axe.runner_signals.signal.signal") as mock_signal:
        install_sigterm_handler("test")
        captured_handler = mock_signal.call_args[0][1]

    with patch("sase.axe.runner_signals.os.write"):
        with pytest.raises(SystemExit) as exc_info:
            captured_handler(signal.SIGTERM, None)
        assert exc_info.value.code == 128 + signal.SIGTERM
        captured_handler(signal.SIGTERM, None)

    reset_killed()


def test_sigterm_handler_can_be_rearmed() -> None:
    """reset_killed permits a later kill to run the handler again."""
    reset_killed()
    cleanup = MagicMock()
    with patch("sase.axe.runner_signals.signal.signal") as mock_signal:
        install_sigterm_handler("test", soft=True, on_signal=cleanup)
        captured_handler = mock_signal.call_args[0][1]

    with patch("sase.axe.runner_signals.os.write"):
        captured_handler(signal.SIGTERM, None)
        reset_killed()
        captured_handler(signal.SIGTERM, None)

    assert cleanup.call_count == 2
    reset_killed()


def test_sigterm_handler_contains_logging_failure() -> None:
    """Logging a cleanup failure must not escape the signal handler."""
    reset_killed()

    def fail_cleanup() -> None:
        raise RuntimeError("cleanup failed")

    with patch("sase.axe.runner_signals.signal.signal") as mock_signal:
        install_sigterm_handler("test", soft=True, on_signal=fail_cleanup)
        captured_handler = mock_signal.call_args[0][1]

    with (
        patch("sase.axe.runner_signals.os.write"),
        patch(
            "sase.axe.runner_signals.logger.exception",
            side_effect=RuntimeError("logging failed"),
        ) as log_exception,
    ):
        captured_handler(signal.SIGTERM, None)

    log_exception.assert_called_once_with("SIGTERM cleanup callback failed")
    reset_killed()


def test_sigterm_handler_subprocess_survives_signal_burst(tmp_path: Path) -> None:
    """Repeated SIGTERM during stderr writes exits cleanly in a child runner."""
    child = """
import sys
import time
from sase.axe.runner_signals import install_sigterm_handler, was_killed

install_sigterm_handler("agent", soft=True)
print("ready", flush=True)
while not was_killed():
    sys.stderr.write("x" * 32768)
    sys.stderr.flush()
    time.sleep(0.001)
print("clean-exit", flush=True)
"""
    stderr_path = tmp_path / "child.stderr"
    with stderr_path.open("wb") as stderr_file:
        proc = subprocess.Popen(
            [sys.executable, "-c", child],
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            start_new_session=True,
            text=True,
        )
        try:
            assert proc.stdout is not None
            assert proc.stdout.readline() == "ready\n"
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            for _ in range(20):
                try:
                    os.kill(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    break

            try:
                exit_code = proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=5)
                pytest.fail("SIGTERM child did not exit after the kill burst")
            remaining_stdout = proc.stdout.read()
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=5)

    stderr = stderr_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "clean-exit\n" in remaining_stdout
    assert "reentrant" not in stderr
    assert "Traceback" not in stderr


def test_reset_killed_clears_timestamp() -> None:
    """reset_killed clears both the boolean kill flag and timestamp."""
    from sase.axe import runner_signals

    runner_signals._killed_state["killed"] = True
    runner_signals._killed_state["killed_at"] = 42.0

    reset_killed()

    assert was_killed() is False
    assert killed_at() is None
