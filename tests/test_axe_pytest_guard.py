"""Regression tests for pytest isolation of axe lifecycle operations."""

from unittest.mock import patch

import pytest

from sase.axe.config import AxeConfig
from sase.axe._process_guard import (
    AXE_LIFECYCLE_TEST_BLOCK_MESSAGE,
    AXE_LIFECYCLE_TEST_OVERRIDE_ENV,
    axe_lifecycle_blocked_in_tests,
)
from sase.axe.process import (
    restart_axe_daemon_result,
    start_axe_daemon_result,
    stop_axe_daemon_result,
)


@pytest.mark.parametrize("context_var", ["PYTEST_CURRENT_TEST", "PYTEST_VERSION"])
def test_pytest_context_detection(
    monkeypatch: pytest.MonkeyPatch,
    context_var: str,
) -> None:
    monkeypatch.delenv(AXE_LIFECYCLE_TEST_OVERRIDE_ENV, raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("PYTEST_VERSION", raising=False)
    monkeypatch.setenv(context_var, "present")

    assert axe_lifecycle_blocked_in_tests() is True


def test_pytest_override_disables_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "present")
    monkeypatch.setenv(AXE_LIFECYCLE_TEST_OVERRIDE_ENV, "1")

    assert axe_lifecycle_blocked_in_tests() is False


def test_start_is_blocked_before_any_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "present")
    monkeypatch.delenv(AXE_LIFECYCLE_TEST_OVERRIDE_ENV, raising=False)
    with (
        patch("sase.axe._process_start.write_desired_state") as write_state,
        patch("sase.axe._process_start.get_axe_pid") as get_pid,
        patch(
            "sase.axe._process_start._acquire_lifecycle_lock_for_start"
        ) as acquire_lock,
        patch("sase.axe._process_start.subprocess.Popen") as popen,
    ):
        result = start_axe_daemon_result(AxeConfig())

    assert result.status == "blocked_in_tests"
    assert result.message == AXE_LIFECYCLE_TEST_BLOCK_MESSAGE
    write_state.assert_not_called()
    get_pid.assert_not_called()
    acquire_lock.assert_not_called()
    popen.assert_not_called()


def test_stop_is_blocked_before_any_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "present")
    monkeypatch.delenv(AXE_LIFECYCLE_TEST_OVERRIDE_ENV, raising=False)
    with (
        patch("sase.axe._process_stop.write_desired_state") as write_state,
        patch("sase.axe._process_stop.probe_orchestrator") as probe,
        patch("sase.axe._process_stop._terminate_process") as terminate,
    ):
        result = stop_axe_daemon_result()

    assert result.blocked_in_tests is True
    assert result.error == AXE_LIFECYCLE_TEST_BLOCK_MESSAGE
    assert result.summary() == AXE_LIFECYCLE_TEST_BLOCK_MESSAGE
    write_state.assert_not_called()
    probe.assert_not_called()
    terminate.assert_not_called()


def test_restart_is_blocked_before_any_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "present")
    monkeypatch.delenv(AXE_LIFECYCLE_TEST_OVERRIDE_ENV, raising=False)
    with (
        patch("sase.axe._process_restart.write_desired_state") as write_state,
        patch("sase.axe._process_restart.load_axe_config") as load_config,
        patch("sase.axe._process_restart.stop_axe_daemon_result") as stop,
        patch("sase.axe._process_restart.start_axe_daemon_result") as start,
    ):
        result = restart_axe_daemon_result()

    assert result.status == "blocked_in_tests"
    assert result.message == AXE_LIFECYCLE_TEST_BLOCK_MESSAGE
    write_state.assert_not_called()
    load_config.assert_not_called()
    stop.assert_not_called()
    start.assert_not_called()
