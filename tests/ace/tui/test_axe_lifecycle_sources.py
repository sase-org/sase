"""Source-attribution coverage for ACE axe lifecycle actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest
from textual.worker import Worker

import sase.ace.tui.actions.axe as axe_actions
from sase.ace.tui.actions.axe import AxeMixin
from sase.axe.process import AxeStartResult, AxeStopResult


class _WorkerHarness(AxeMixin):
    def __init__(self) -> None:
        self._axe_worker: Worker[Any] | None = None
        self._axe_worker_operation = None
        self.worker_results: list[tuple[bool, str]] = []

    def _set_axe_starting(self, _starting: bool) -> None:  # type: ignore[override]
        return

    def _set_axe_stopping(self, _stopping: bool) -> None:  # type: ignore[override]
        return

    def _set_axe_restarting(self, _restarting: bool) -> None:  # type: ignore[override]
        return

    def run_worker(
        self,
        work: Callable[[], tuple[bool, str]],
        *,
        thread: bool,
    ) -> Worker[Any]:
        assert thread is True
        self.worker_results.append(work())
        return cast(Worker[Any], object())


def test_manual_ace_lifecycle_actions_pass_explicit_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def start(**kwargs: object) -> AxeStartResult:
        calls.append(("start", kwargs))
        return AxeStartResult(status="started", pid=101)

    def stop(**kwargs: object) -> AxeStopResult:
        calls.append(("stop", kwargs))
        return AxeStopResult(orchestrator_signaled=True, orchestrator_stopped=True)

    def restart(**kwargs: object) -> AxeStartResult:
        calls.append(("restart", kwargs))
        return AxeStartResult(status="started", pid=202)

    monkeypatch.setattr(axe_actions, "_start_axe_daemon_result", start)
    monkeypatch.setattr(axe_actions, "_stop_axe_daemon_result", stop)
    monkeypatch.setattr(axe_actions, "_restart_axe_daemon_result", restart)
    app = _WorkerHarness()

    app._start_axe()
    app._axe_worker = None
    app._stop_axe()
    app._axe_worker = None
    app._restart_axe_daemon()

    assert calls == [
        ("start", {"desired_state_source": "ace start"}),
        ("stop", {"desired_state_source": "ace stop"}),
        ("restart", {"desired_state_source": "ace restart"}),
    ]


class _StartupHarness(AxeMixin):
    def __init__(self, *, running: bool, restart: bool) -> None:
        self.axe_running = running
        self._restart_axe = restart
        self._auto_start_axe = True
        self.sources: list[tuple[str, str]] = []

    async def _load_axe_status_async(self) -> None:  # type: ignore[override]
        return

    def _start_axe(self, *, source: str = "ace start") -> None:  # type: ignore[override]
        self.sources.append(("start", source))

    def _restart_axe_daemon(  # type: ignore[override]
        self,
        *,
        source: str = "ace restart",
    ) -> None:
        self.sources.append(("restart", source))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("running", "restart", "expected"),
    [
        (False, False, [("start", "ace startup")]),
        (True, True, [("restart", "ace startup restart")]),
    ],
)
async def test_ace_startup_lifecycle_sources(
    running: bool,
    restart: bool,
    expected: list[tuple[str, str]],
) -> None:
    app = _StartupHarness(running=running, restart=restart)

    await app._run_axe_startup_init()

    assert app.sources == expected
