"""Regression tests for axe daemon worker completion status handling."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

from textual.worker import Worker, WorkerState

from sase.ace.tui.actions.axe import (
    AxeMixin,
    AxeWorkerOperation,
    _POST_AXE_WORKER_STATUS_REPOLL_DELAYS,
)


class _Harness(AxeMixin):
    def __init__(
        self,
        status_reads: list[bool],
        *,
        operation: AxeWorkerOperation,
    ) -> None:
        self.axe_running = False
        self._status_reads = list(status_reads)
        self._load_calls = 0
        self._axe_worker = cast(Worker[Any], object())
        self._axe_worker_operation: AxeWorkerOperation | None = operation
        self._axe_config_restart_saved_path: str | None = None
        self._transition_state = {
            "starting": False,
            "restarting": operation == "restart",
            "stopping": operation == "stop",
        }
        self.notifications: list[tuple[str, str | None]] = []
        self.timers: list[tuple[float, Callable[[], None]]] = []

    def _load_axe_status(self) -> None:  # type: ignore[override]
        self._load_calls += 1
        self.axe_running = self._status_reads.pop(0)

    def _set_axe_starting(self, starting: bool) -> None:  # type: ignore[override]
        self._transition_state["starting"] = starting

    def _set_axe_restarting(self, restarting: bool) -> None:  # type: ignore[override]
        self._transition_state["restarting"] = restarting

    def _set_axe_stopping(self, stopping: bool) -> None:  # type: ignore[override]
        self._transition_state["stopping"] = stopping

    def _schedule_axe_async_refresh(self) -> None:  # type: ignore[override]
        self._load_axe_status()

    def set_timer(self, delay: float, callback: Callable[[], None]) -> None:
        self.timers.append((delay, callback))

    def notify(
        self,
        message: str,
        *,
        severity: str | None = None,
        **_kwargs: Any,
    ) -> None:
        self.notifications.append((message, severity))


def _worker(
    result: tuple[bool, str] | None = None,
    error: BaseException | None = None,
) -> Worker[Any]:
    return cast(Worker[Any], SimpleNamespace(result=result, error=error))


def test_restart_completion_clears_transient_state_before_repoll() -> None:
    """RESTARTING must not persist when the first post-worker read is stopped."""
    app = _Harness([False, True], operation="restart")

    app._on_axe_worker_done(
        _worker((True, "Axe restarted (pid 1234)")),
        WorkerState.SUCCESS,
    )

    assert app.axe_running is False
    assert app._transition_state == {
        "starting": False,
        "restarting": False,
        "stopping": False,
    }
    assert [delay for delay, _callback in app.timers] == list(
        _POST_AXE_WORKER_STATUS_REPOLL_DELAYS
    )

    app.timers[0][1]()

    assert app.axe_running is True
    assert app._transition_state["restarting"] is False


def test_running_restart_completion_does_not_schedule_repolls() -> None:
    app = _Harness([True], operation="restart")

    app._on_axe_worker_done(
        _worker((True, "Axe restarted (pid 1234)")),
        WorkerState.SUCCESS,
    )

    assert app.axe_running is True
    assert app._transition_state["restarting"] is False
    assert app.timers == []


def test_stop_completion_clears_transient_state_without_repolls() -> None:
    app = _Harness([False], operation="stop")

    app._on_axe_worker_done(_worker((True, "Axe stopped")), WorkerState.SUCCESS)

    assert app.axe_running is False
    assert app._transition_state == {
        "starting": False,
        "restarting": False,
        "stopping": False,
    }
    assert app.timers == []


def test_failed_restart_completion_clears_transient_state() -> None:
    app = _Harness([False], operation="restart")

    app._on_axe_worker_done(
        _worker((False, "Failed to restart axe")),
        WorkerState.SUCCESS,
    )

    assert app.notifications == [("Failed to restart axe", "error")]
    assert app._transition_state == {
        "starting": False,
        "restarting": False,
        "stopping": False,
    }
    assert app.timers == []


def test_config_restart_failure_keeps_saved_write_truthful() -> None:
    app = _Harness([False], operation="restart")
    app._axe_config_restart_saved_path = "/tmp/sase.yml"

    app._on_axe_worker_done(
        _worker((False, "Failed to restart axe")),
        WorkerState.SUCCESS,
    )

    assert app.notifications == [
        (
            "Config saved to /tmp/sase.yml, but AXE restart failed: Failed to restart axe",
            "error",
        )
    ]
    assert app._load_calls == 1
