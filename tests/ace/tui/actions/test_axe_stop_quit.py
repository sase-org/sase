from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui import AceExitAction
from sase.ace.tui.actions.axe import AxeMixin
from sase.ace.tui.modals import QuitOptionsModal
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.proc_observer import ObservedProc


class _FakeWorker:
    def __init__(self, *, finished: bool = False) -> None:
        self._finished = finished

    @property
    def is_finished(self) -> bool:
        return self._finished


def _session_task(
    proc_id: str = "session-1", display_name: str = "Sync visual-auth"
) -> ObservedProc:
    return ObservedProc(
        proc_id=proc_id,
        proc_type="sync",
        cl_name="sync-cl",
        project_file="/tmp/project.sase",
        status="running",
        message="sync in progress",
        started_at=datetime(2026, 6, 23, 12, 0, 0),
        display_name=display_name,
    )


class _StopQuitApp(AxeMixin):
    def __init__(
        self,
        *,
        axe_running: bool = False,
        kill_tasks_raises: bool = False,
        order: list[str] | None = None,
        session_rows: tuple[ObservedProc, ...] = (),
        durable_workers: dict[str, Any] | None = None,
    ) -> None:
        self.axe_running = axe_running
        self._kill_procs_raises = kill_tasks_raises
        self.order = order if order is not None else []
        self.did_quit = False
        self.exit_action = AceExitAction.QUIT
        self.stall_watchdog_stops = 0
        self.kill_task_calls = 0
        self.submitted_workers: list[Any] = []
        self.pushed: list[tuple[Any, Any]] = []
        self.notifications: list[tuple[str, str | None]] = []
        self._session_rows = tuple(session_rows)
        self._durable_submit_workers = dict(durable_workers or {})
        self._quit_options_open = False
        self._quit_confirm_open = False

    def _session_overlay_rows(self) -> tuple[ObservedProc, ...]:
        return self._session_rows

    def run_worker(self, work: Any) -> Any:
        self.submitted_workers.append(work)
        return work

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed.append((modal, callback))

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

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


def _patch_no_inflight(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.axe.state as axe_state

    monkeypatch.setattr(axe_state, "find_inflight_chop_launches", lambda: [])


def _fake_launch() -> Any:
    from sase.axe.state import InflightChopLaunch

    return InflightChopLaunch(
        lumberjack_name="run_every",
        chop_name="toobig_split[sase]",
        run_id="20260928T093200_850344",
        started_at="2026-09-28T09:32:00-04:00",
        proposed_count=61,
        launched_count=2,
        clan="toobig-@",
    )


def _patch_inflight(monkeypatch: pytest.MonkeyPatch, launches: list[Any]) -> None:
    import sase.axe.state as axe_state

    monkeypatch.setattr(
        axe_state, "find_inflight_chop_launches", lambda: list(launches)
    )


async def _drain_quit_tasks(app: _StopQuitApp) -> None:
    tasks = list(getattr(app, "_quit_confirm_tasks", ()))
    for task in tasks:
        try:
            await task
        except Exception:
            pass
    # Yield once so call_from_thread-free continuations settle.
    await asyncio.sleep(0)


def _push_quit_panel(app: _StopQuitApp) -> Any:
    app.action_stop_axe_and_quit()
    assert len(app.pushed) == 1
    _, callback = app.pushed[0]
    assert callback is not None
    return callback


def test_stop_axe_and_quit_action_pushes_quit_options_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_no_inflight(monkeypatch)
    app = _StopQuitApp(
        session_rows=(
            _session_task(),
            _session_task("session-2"),
        )
    )

    callback = _push_quit_panel(app)

    modal, _ = app.pushed[0]
    assert isinstance(modal, QuitOptionsModal)
    assert modal._tui_task_count == 2

    callback(None)
    assert app.submitted_workers == []
    assert app.did_quit is False


@pytest.mark.asyncio
async def test_no_impact_quit_stop_axe_behaves_as_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_no_inflight(monkeypatch)
    app = _StopQuitApp()
    calls: list[str] = []

    async def fake_stop_axe_and_quit() -> None:
        calls.append("stop")

    app._stop_axe_and_quit = fake_stop_axe_and_quit  # type: ignore[method-assign]
    callback = _push_quit_panel(app)

    callback("quit_stop_axe")
    await _drain_quit_tasks(app)

    assert len(app.submitted_workers) == 1
    await app.submitted_workers[0]
    assert calls == ["stop"]
    # No confirmation modal when nothing would be lost.
    assert len(app.pushed) == 1


@pytest.mark.parametrize(
    ("choice", "expected_restart_axe"),
    [
        ("restart_tui", False),
        ("restart_tui_and_axe", True),
    ],
)
def test_no_impact_restart_options_behave_as_today(
    monkeypatch: pytest.MonkeyPatch,
    choice: str,
    expected_restart_axe: bool,
) -> None:
    _patch_no_inflight(monkeypatch)
    app = _StopQuitApp()
    restart_calls: list[bool] = []

    def fake_restart_tui(*, restart_axe: bool) -> None:
        restart_calls.append(restart_axe)

    app._restart_tui = fake_restart_tui  # type: ignore[method-assign]
    callback = _push_quit_panel(app)

    callback(choice)

    # restart_tui is sync; restart_tui_and_axe with no impact falls back to
    # sync when there is no running loop.
    assert app.submitted_workers == []
    assert restart_calls == [expected_restart_axe]
    assert len(app.pushed) == 1


@pytest.mark.asyncio
async def test_tui_impact_confirms_all_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_no_inflight(monkeypatch)
    for choice in ("quit_stop_axe", "restart_tui", "restart_tui_and_axe"):
        app = _StopQuitApp(session_rows=(_session_task(),))
        restart_calls: list[bool] = []

        def fake_restart_tui(
            *, restart_axe: bool, _calls: list[bool] = restart_calls
        ) -> None:
            _calls.append(restart_axe)

        app._restart_tui = fake_restart_tui  # type: ignore[method-assign]
        callback = _push_quit_panel(app)
        callback(choice)
        await _drain_quit_tasks(app)

        assert len(app.pushed) == 2
        assert isinstance(app.pushed[1][0], ConfirmActionModal)
        assert app.submitted_workers == []
        assert restart_calls == []
        assert app.did_quit is False


@pytest.mark.asyncio
async def test_scheduler_impact_confirms_only_stop_and_restart_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launch = _fake_launch()
    _patch_inflight(monkeypatch, [launch])

    # quit_stop_axe and restart_tui_and_axe confirm.
    for choice in ("quit_stop_axe", "restart_tui_and_axe"):
        app = _StopQuitApp()
        callback = _push_quit_panel(app)
        callback(choice)
        await _drain_quit_tasks(app)

        assert len(app.pushed) == 2
        modal = app.pushed[1][0]
        assert isinstance(modal, ConfirmActionModal)
        assert "2/61" in modal._message
        assert app.submitted_workers == []
        assert app.did_quit is False

    # restart_tui ignores scheduler launches.
    _patch_inflight(monkeypatch, [launch])
    app = _StopQuitApp()
    restart_calls: list[bool] = []

    def fake_restart_tui(*, restart_axe: bool) -> None:
        restart_calls.append(restart_axe)

    app._restart_tui = fake_restart_tui  # type: ignore[method-assign]
    callback = _push_quit_panel(app)
    callback("restart_tui")
    await _drain_quit_tasks(app)

    assert len(app.pushed) == 1
    assert restart_calls == [False]


@pytest.mark.asyncio
async def test_declining_never_stops_or_restarts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop_calls = _patch_scheduler_stop(monkeypatch)
    _patch_inflight(monkeypatch, [_fake_launch()])
    app = _StopQuitApp(session_rows=(_session_task(),))
    restart_calls: list[bool] = []

    def fake_restart_tui(*, restart_axe: bool) -> None:
        restart_calls.append(restart_axe)

    app._restart_tui = fake_restart_tui  # type: ignore[method-assign]
    callback = _push_quit_panel(app)

    callback("quit_stop_axe")
    await _drain_quit_tasks(app)
    assert len(app.pushed) == 2
    _, confirm_cb = app.pushed[1]
    confirm_cb(False)

    assert stop_calls == []
    assert restart_calls == []
    assert app.submitted_workers == []
    assert app.did_quit is False
    assert app.kill_task_calls == 0


@pytest.mark.asyncio
async def test_confirming_runs_existing_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_scheduler_stop(monkeypatch)
    _patch_no_inflight(monkeypatch)
    app = _StopQuitApp(session_rows=(_session_task(),))
    calls: list[str] = []

    async def fake_stop_axe_and_quit() -> None:
        calls.append("stop")

    app._stop_axe_and_quit = fake_stop_axe_and_quit  # type: ignore[method-assign]
    callback = _push_quit_panel(app)
    callback("quit_stop_axe")
    await _drain_quit_tasks(app)

    _, confirm_cb = app.pushed[1]
    confirm_cb(True)

    assert len(app.submitted_workers) == 1
    await app.submitted_workers[0]
    assert calls == ["stop"]


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
