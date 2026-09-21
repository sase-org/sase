"""Regression tests for pytest isolation of axe lifecycle operations."""

from unittest.mock import patch

import pytest

from sase.axe._process_guard import (
    AXE_LIFECYCLE_TEST_BLOCK_MESSAGE,
    AXE_LIFECYCLE_TEST_OVERRIDE_ENV,
    axe_lifecycle_blocked_in_tests,
)
from sase.axe.process import stop_axe_daemon_result


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


def test_stop_is_blocked_before_any_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "present")
    monkeypatch.delenv(AXE_LIFECYCLE_TEST_OVERRIDE_ENV, raising=False)
    with (
        patch("sase.axe._process_stop.probe_orchestrator") as probe,
        patch("sase.axe._process_stop._terminate_process") as terminate,
    ):
        result = stop_axe_daemon_result()

    assert result.blocked_in_tests is True
    assert result.error == AXE_LIFECYCLE_TEST_BLOCK_MESSAGE
    assert result.summary() == AXE_LIFECYCLE_TEST_BLOCK_MESSAGE
    probe.assert_not_called()
    terminate.assert_not_called()
