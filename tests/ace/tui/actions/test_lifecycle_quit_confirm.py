from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui.util import shutdown
from sase.ace.tui.actions.lifecycle import LifecycleMixin
from sase.ace.tui.proc_observer import ObservedProc, ProcProjection


class _QuitApp(LifecycleMixin):
    def __init__(self, tasks: tuple[ObservedProc, ...] = ()) -> None:
        self._proc_projection = ProcProjection(
            rows=tasks,
            active_count=sum(1 for task in tasks if task.status == "running"),
        )
        self.pushed: list[tuple[Any, Any]] = []
        self.did_quit = False

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed.append((modal, callback))

    def _do_quit(self) -> None:
        self.did_quit = True


class _FlushQuitApp(_QuitApp):
    def __init__(self, tasks: tuple[ObservedProc, ...] = ()) -> None:
        super().__init__(tasks)
        self.exit_events: list[str] = []
        self.scheduled: list[asyncio.Task[None]] = []

    async def _flush_agents_fold_state(self) -> None:
        self.exit_events.append("flush-folds")

    async def _flush_admin_center_tab_state(self) -> None:
        self.exit_events.append("flush-admin-center")

    def _do_quit(self) -> None:
        self.exit_events.append("quit")
        super()._do_quit()

    def call_later(self, callback: Any) -> None:
        self.scheduled.append(asyncio.create_task(callback()))


def _task(
    proc_id: str,
    proc_type: str,
    status: str = "running",
    *,
    display_name: str | None = None,
) -> ObservedProc:
    return ObservedProc(
        proc_id=proc_id,
        proc_type=proc_type,
        cl_name=f"{proc_type}-cl",
        project_file="/tmp/project.sase",
        status=status,
        message=f"{proc_type} in progress",
        started_at=datetime(2026, 6, 23, 12, 0, 0),
        display_name=display_name,
    )


def test_running_task_count_includes_session_overlay() -> None:
    class _OverlayQuitApp(LifecycleMixin):
        def __init__(self) -> None:
            self._proc_projection = ProcProjection()

        def _effective_proc_projection(self) -> ProcProjection:
            return ProcProjection(
                rows=(_task("session-1", "sync"),),
                active_count=1,
                session_id="session-mine",
            )

    assert _OverlayQuitApp()._count_running_tasks() == 1


def test_running_task_count_excludes_monitor_shells() -> None:
    class _MonitorOverlayQuitApp(LifecycleMixin):
        def __init__(self) -> None:
            self._proc_projection = ProcProjection()

        def _effective_proc_projection(self) -> ProcProjection:
            return ProcProjection(
                rows=(_task("session-1", "sync"), _task("monitor-1", "detached")),
                active_count=2,
                active_monitor_count=1,
                session_id="session-mine",
            )

    # A detached monitor supervisor survives ACE exit, so it must not count
    # toward "N procs will be stopped" in the quit-options modal.
    assert _MonitorOverlayQuitApp()._count_running_tasks() == 1


@pytest.mark.asyncio
async def test_action_quit_with_running_tasks_quits_without_modal() -> None:
    running = _task("run-1", "sync", display_name="Sync visual-auth")
    completed = _task("done-1", "mail", status="success")
    app = _QuitApp((running, completed))

    await app.action_quit()

    assert app.did_quit is True
    assert app.pushed == []


@pytest.mark.asyncio
async def test_action_quit_without_running_tasks_quits_without_modal() -> None:
    app = _QuitApp((_task("done-mail", "mail", status="success"),))

    await app.action_quit()

    assert app.did_quit is True
    assert app.pushed == []


@pytest.mark.asyncio
async def test_ordinary_quit_flushes_fold_state_before_exit() -> None:
    app = _FlushQuitApp()

    await app.action_quit()

    assert set(app.exit_events[:-1]) == {"flush-folds", "flush-admin-center"}
    assert app.exit_events[-1] == "quit"


@pytest.mark.asyncio
async def test_confirmed_quit_flushes_fold_state_before_exit() -> None:
    app = _FlushQuitApp((_task("run-sync", "sync"),))

    await app.action_quit()
    await asyncio.gather(*app.scheduled)

    assert set(app.exit_events[:-1]) == {"flush-folds", "flush-admin-center"}
    assert app.exit_events[-1] == "quit"


@pytest.mark.asyncio
async def test_controlled_exit_waits_for_admin_center_flush() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class _WaitingFlushApp(_QuitApp):
        async def _flush_admin_center_tab_state(self) -> None:
            entered.set()
            await release.wait()

    app = _WaitingFlushApp()
    quitting = asyncio.create_task(app.action_quit())
    await asyncio.wait_for(entered.wait(), timeout=0.5)

    assert shutdown.is_shutdown_requested() is True
    assert app.did_quit is False
    release.set()
    await quitting

    assert app.did_quit is True
