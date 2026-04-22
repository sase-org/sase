"""Tests for shared subprocess helpers in ``_subprocess.py``."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.llm_provider._subprocess import start_interrupt_monitor


def _wait_until(pred, timeout: float = 1.0, interval: float = 0.01) -> bool:
    """Busy-wait for a predicate, returning True if it became truthy in time."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return pred()


def test_start_interrupt_monitor_fires_callback_and_terminates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When interrupt_request.json appears, callback fires and process terminates."""
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    # Pre-place the interrupt file so the monitor detects it on the first poll.
    interrupt_path = tmp_path / "interrupt_request.json"
    interrupt_path.write_text(json.dumps({"message": "stop work"}), encoding="utf-8")

    process = MagicMock()
    process.poll.return_value = None

    received: list[str | None] = []
    start_interrupt_monitor(process, on_interrupt=received.append)

    assert _wait_until(lambda: bool(received))
    assert received == ["stop work"]
    assert _wait_until(lambda: not interrupt_path.exists())
    assert _wait_until(lambda: process.terminate.called)
    process.terminate.assert_called_once()


def test_start_interrupt_monitor_no_op_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No thread, no callback, no terminate when SASE_ARTIFACTS_DIR is unset."""
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    process = MagicMock()
    process.poll.return_value = None

    received: list[str | None] = []
    start_interrupt_monitor(process, on_interrupt=received.append)

    time.sleep(0.05)
    assert received == []
    process.terminate.assert_not_called()


def test_start_interrupt_monitor_handles_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed interrupt JSON: callback not fired and terminate not called."""
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    interrupt_path = tmp_path / "interrupt_request.json"
    interrupt_path.write_text("not valid json", encoding="utf-8")

    # poll() returns None then a non-None value so the thread exits quickly
    # even if the exception path leaves the while-loop uncompleted.
    process = MagicMock()
    process.poll.side_effect = [None, 0]

    received: list[str | None] = []
    start_interrupt_monitor(process, on_interrupt=received.append)

    # Wait for the monitor to attempt the read and return.
    assert _wait_until(lambda: process.poll.call_count >= 1)
    # Give the thread a beat to finish its post-try `return`.
    time.sleep(0.05)

    assert received == []
    process.terminate.assert_not_called()


def test_start_interrupt_monitor_missing_message_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """JSON without a 'message' field calls callback with None."""
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    interrupt_path = tmp_path / "interrupt_request.json"
    interrupt_path.write_text(json.dumps({"unrelated": "field"}), encoding="utf-8")

    process = MagicMock()
    process.poll.return_value = None

    received: list[str | None] = []
    start_interrupt_monitor(process, on_interrupt=received.append)

    assert _wait_until(lambda: bool(received))
    assert received == [None]
    assert _wait_until(lambda: not interrupt_path.exists())
    assert _wait_until(lambda: process.terminate.called)
    process.terminate.assert_called_once()
