from __future__ import annotations

from typing import Any

import pytest

import sase.ace.tui.actions.axe as axe_actions
from sase.ace.tui.actions.axe import AxeMixin
from sase.axe.process import AxeStopResult


class _StopQuitApp(AxeMixin):
    def __init__(
        self,
        *,
        axe_running: bool = False,
        kill_tasks_raises: bool = False,
        order: list[str] | None = None,
    ) -> None:
        self.axe_running = axe_running
        self._kill_tasks_raises = kill_tasks_raises
        self.order = order if order is not None else []
        self.did_quit = False
        self.stall_watchdog_stops = 0
        self.kill_task_calls = 0
        self.submitted_workers: list[Any] = []

    def run_worker(self, work: Any) -> Any:
        self.submitted_workers.append(work)
        return work

    def _stop_tui_stall_watchdog(self) -> None:
        self.stall_watchdog_stops += 1
        self.order.append("watchdog")

    def _kill_all_running_tasks(self) -> None:
        self.kill_task_calls += 1
        self.order.append("kill-tasks")
        if self._kill_tasks_raises:
            raise RuntimeError("task kill failed")

    def _do_quit(self) -> None:
        self.did_quit = True
        self.order.append("quit")


async def _run_stop_quit_action(app: _StopQuitApp) -> None:
    app.action_stop_axe_and_quit()
    assert len(app.submitted_workers) == 1
    await app.submitted_workers[0]


@pytest.mark.asyncio
async def test_stop_axe_and_quit_uses_robust_stop_when_status_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    order: list[str] = []

    def fake_stop(**kwargs: Any) -> AxeStopResult:
        calls.append(kwargs)
        order.append("stop")
        return AxeStopResult()

    monkeypatch.setattr(axe_actions, "_stop_axe_daemon_result", fake_stop)
    app = _StopQuitApp(axe_running=False, order=order)

    await _run_stop_quit_action(app)

    assert calls == [{"timeout": 5.0, "kill_timeout": 2.0}]
    assert app.kill_task_calls == 1
    assert app.stall_watchdog_stops == 1
    assert app.did_quit is True
    assert order == ["watchdog", "kill-tasks", "stop", "quit"]


@pytest.mark.asyncio
async def test_stop_axe_and_quit_still_quits_when_stop_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_stop(**_kwargs: Any) -> AxeStopResult:
        nonlocal calls
        calls += 1
        raise RuntimeError("stop failed")

    monkeypatch.setattr(axe_actions, "_stop_axe_daemon_result", fake_stop)
    app = _StopQuitApp(axe_running=True)

    await _run_stop_quit_action(app)

    assert calls == 1
    assert app.kill_task_calls == 1
    assert app.did_quit is True


@pytest.mark.asyncio
async def test_stop_axe_and_quit_still_stops_and_quits_when_task_kill_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_stop(**_kwargs: Any) -> AxeStopResult:
        nonlocal calls
        calls += 1
        return AxeStopResult()

    monkeypatch.setattr(axe_actions, "_stop_axe_daemon_result", fake_stop)
    app = _StopQuitApp(kill_tasks_raises=True)

    await _run_stop_quit_action(app)

    assert calls == 1
    assert app.kill_task_calls == 1
    assert app.did_quit is True
