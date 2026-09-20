from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui import AceExitAction
from sase.ace.tui.actions.axe import AxeMixin
from sase.ace.tui.modals import QuitOptionsModal


class _StopQuitApp(AxeMixin):
    def __init__(
        self,
        *,
        axe_running: bool = False,
        kill_tasks_raises: bool = False,
        running_task_count: int = 0,
        order: list[str] | None = None,
    ) -> None:
        self.axe_running = axe_running
        self._kill_procs_raises = kill_tasks_raises
        self._running_task_count = running_task_count
        self.order = order if order is not None else []
        self.did_quit = False
        self.exit_action = AceExitAction.QUIT
        self.stall_watchdog_stops = 0
        self.kill_task_calls = 0
        self.submitted_workers: list[Any] = []
        self.pushed: list[tuple[Any, Any]] = []
        self.notifications: list[tuple[str, str | None]] = []

    def run_worker(self, work: Any) -> Any:
        self.submitted_workers.append(work)
        return work

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed.append((modal, callback))

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def _count_running_tasks(self) -> int:
        return self._running_task_count

    def _stop_tui_stall_watchdog(self) -> None:
        self.stall_watchdog_stops += 1
        self.order.append("watchdog")

    def _kill_all_running_tasks(self) -> None:
        self.kill_task_calls += 1
        self.order.append("kill-tasks")
        if self._kill_procs_raises:
            raise RuntimeError("task kill failed")

    def _do_quit(self) -> None:
        self.did_quit = True
        self.order.append("quit")


async def _run_stop_quit_worker(app: _StopQuitApp) -> None:
    await app._stop_axe_and_quit()


def _patch_scheduler_stop(
    monkeypatch: pytest.MonkeyPatch,
    *,
    order: list[str] | None = None,
    raises: bool = False,
) -> list[tuple[str, dict[str, Any]]]:
    """Record ``stop_service_proc`` calls; the service host itself must survive."""
    import sase.service.actions as service_actions
    import sase.service.control as service_control

    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_stop(name: str, **kwargs: Any) -> None:
        calls.append((name, kwargs))
        if order is not None:
            order.append("stop")
        if raises:
            raise RuntimeError("stop failed")

    def host_stopped(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the service host must not be stopped on quit")

    monkeypatch.setattr(service_actions, "stop_service_proc", fake_stop)
    monkeypatch.setattr(service_control, "stop_service_host", host_stopped)
    return calls


def _push_quit_panel(app: _StopQuitApp) -> Any:
    app.action_stop_axe_and_quit()
    assert len(app.pushed) == 1
    _, callback = app.pushed[0]
    assert callback is not None
    return callback


def test_stop_axe_and_quit_action_pushes_quit_options_modal() -> None:
    app = _StopQuitApp(running_task_count=2)

    callback = _push_quit_panel(app)

    modal, _ = app.pushed[0]
    assert isinstance(modal, QuitOptionsModal)
    assert modal._running_task_count == 2

    callback(None)
    assert app.submitted_workers == []
    assert app.did_quit is False


@pytest.mark.asyncio
async def test_stop_axe_and_quit_action_routes_quit_stop_axe() -> None:
    app = _StopQuitApp()
    calls: list[str] = []

    async def fake_stop_axe_and_quit() -> None:
        calls.append("stop")

    app._stop_axe_and_quit = fake_stop_axe_and_quit  # type: ignore[method-assign]
    callback = _push_quit_panel(app)

    callback("quit_stop_axe")

    assert len(app.submitted_workers) == 1
    await app.submitted_workers[0]
    assert calls == ["stop"]


@pytest.mark.parametrize(
    ("choice", "expected_restart_axe"),
    [
        ("restart_tui", False),
        ("restart_tui_and_axe", True),
    ],
)
def test_stop_axe_and_quit_action_routes_restart_options(
    choice: str,
    expected_restart_axe: bool,
) -> None:
    app = _StopQuitApp()
    restart_calls: list[bool] = []

    def fake_restart_tui(*, restart_axe: bool) -> None:
        restart_calls.append(restart_axe)

    app._restart_tui = fake_restart_tui  # type: ignore[method-assign]
    callback = _push_quit_panel(app)

    callback(choice)

    assert app.submitted_workers == []
    assert restart_calls == [expected_restart_axe]


@pytest.mark.asyncio
async def test_stop_axe_and_quit_stops_scheduler_even_when_status_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    calls = _patch_scheduler_stop(monkeypatch, order=order)
    app = _StopQuitApp(axe_running=False, order=order)

    await _run_stop_quit_worker(app)

    assert calls == [("scheduler", {"actor": "tui", "reason": "ace quit"})]
    assert app.kill_task_calls == 0
    assert app.stall_watchdog_stops == 1
    assert app.did_quit is True
    assert order == ["watchdog", "stop", "quit"]


@pytest.mark.asyncio
async def test_stop_axe_and_quit_routes_through_controlled_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_scheduler_stop(monkeypatch)
    app = _StopQuitApp()
    controlled_exit_calls = 0

    async def fake_begin_controlled_exit() -> None:
        nonlocal controlled_exit_calls
        controlled_exit_calls += 1

    app._begin_controlled_exit = fake_begin_controlled_exit  # type: ignore[attr-defined]

    await _run_stop_quit_worker(app)

    assert controlled_exit_calls == 1
    assert app.did_quit is False


@pytest.mark.asyncio
async def test_stop_axe_and_quit_still_quits_when_stop_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_scheduler_stop(monkeypatch, raises=True)
    app = _StopQuitApp(axe_running=True)

    await _run_stop_quit_worker(app)

    assert len(calls) == 1
    assert app.kill_task_calls == 0
    assert app.did_quit is True


@pytest.mark.asyncio
async def test_stop_axe_and_quit_does_not_kill_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_scheduler_stop(monkeypatch)
    app = _StopQuitApp(kill_tasks_raises=True)

    await _run_stop_quit_worker(app)

    assert len(calls) == 1
    assert app.kill_task_calls == 0
    assert app.did_quit is True


@pytest.mark.parametrize(
    ("restart_axe", "expected_exit_action"),
    [
        (False, AceExitAction.RESTART_TUI),
        (True, AceExitAction.RESTART_TUI_AND_AXE),
    ],
)
def test_restart_tui_sets_exit_action_and_quits(
    monkeypatch: pytest.MonkeyPatch,
    restart_axe: bool,
    expected_exit_action: AceExitAction,
) -> None:
    stops = _patch_scheduler_stop(monkeypatch)
    order: list[str] = []
    app = _StopQuitApp(order=order)

    app._restart_tui(restart_axe=restart_axe)

    assert stops == [], "_restart_tui must not stop the scheduler directly"
    assert app.exit_action == expected_exit_action
    assert app.kill_task_calls == 0
    assert app.stall_watchdog_stops == 1
    assert app.did_quit is True
    assert order == ["watchdog", "quit"]


@pytest.mark.parametrize("restart_axe", [False, True])
def test_restart_tui_routes_through_controlled_exit(restart_axe: bool) -> None:
    app = _StopQuitApp()
    controlled_exit_calls = 0

    def fake_request_controlled_exit() -> None:
        nonlocal controlled_exit_calls
        controlled_exit_calls += 1

    app._request_controlled_exit = fake_request_controlled_exit  # type: ignore[attr-defined]

    app._restart_tui(restart_axe=restart_axe)

    assert controlled_exit_calls == 1
    assert app.did_quit is False


def test_restart_tui_does_not_kill_tasks() -> None:
    app = _StopQuitApp(kill_tasks_raises=True)

    app._restart_tui(restart_axe=False)

    assert app.exit_action == AceExitAction.RESTART_TUI
    assert app.kill_task_calls == 0
    assert app.did_quit is True


class _RestartStashApp(_StopQuitApp):
    def __init__(self, *, stash_raises: bool = False) -> None:
        super().__init__()
        self._stash_raises = stash_raises
        self.stash_calls = 0

    def _stash_prompt_bar_before_restart(self) -> bool:
        self.stash_calls += 1
        self.order.append("stash")
        if self._stash_raises:
            raise RuntimeError("stash failed")
        return True


def test_restart_tui_stashes_prompt_before_quit() -> None:
    app = _RestartStashApp()

    app._restart_tui(restart_axe=False)

    assert app.stash_calls == 1
    assert app.exit_action == AceExitAction.RESTART_TUI
    assert app.did_quit is True
    assert app.order == ["watchdog", "stash", "quit"]
    assert app.notifications == [
        ("Prompt draft stashed; press @ to restore after restart", None)
    ]


def test_restart_tui_still_quits_when_restart_stash_raises() -> None:
    app = _RestartStashApp(stash_raises=True)

    app._restart_tui(restart_axe=False)

    assert app.stash_calls == 1
    assert app.exit_action == AceExitAction.RESTART_TUI
    assert app.kill_task_calls == 0
    assert app.did_quit is True
    assert app.order == ["watchdog", "stash", "quit"]
    assert app.notifications == []


@pytest.mark.asyncio
@pytest.mark.parametrize("raises", [False, True])
async def test_stop_and_quit_stops_scheduler_only(
    monkeypatch: pytest.MonkeyPatch, raises: bool
) -> None:
    calls = _patch_scheduler_stop(monkeypatch, raises=raises)
    app = _StopQuitApp()

    await _run_stop_quit_worker(app)

    assert calls == [("scheduler", {"actor": "tui", "reason": "ace quit"})]
    assert app.did_quit is True


def test_quit_modal_stops_the_scheduler() -> None:
    assert QuitOptionsModal()._stop_target == "Scheduler"
