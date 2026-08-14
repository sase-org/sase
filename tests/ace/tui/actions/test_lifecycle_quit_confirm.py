from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui.util import shutdown
from sase.ace.tui.actions.lifecycle import LifecycleMixin
from sase.ace.tui.modals import QuitConfirmModal
from sase.ace.tui.proc_queue import ProcInfo, ProcQueue


class _QuitApp(LifecycleMixin):
    def __init__(self, proc_queue: ProcQueue | None = None) -> None:
        self._proc_queue = proc_queue or ProcQueue()
        self.pushed: list[tuple[Any, Any]] = []
        self.did_quit = False
        self.killed_task_ids: list[str] = []

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed.append((modal, callback))

    def _kill_proc(self, proc_id: str) -> bool:
        self.killed_task_ids.append(proc_id)
        return True

    def _do_quit(self) -> None:
        self.did_quit = True


class _FlushQuitApp(_QuitApp):
    def __init__(self, proc_queue: ProcQueue | None = None) -> None:
        super().__init__(proc_queue)
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
) -> ProcInfo:
    return ProcInfo(
        proc_id=proc_id,
        proc_type=proc_type,
        cl_name=f"{proc_type}-cl",
        project_file="/tmp/project.sase",
        status=status,
        message=f"{proc_type} in progress",
        started_at=datetime(2026, 6, 23, 12, 0, 0),
        display_name=display_name,
    )


def _queue(*tasks: ProcInfo) -> ProcQueue:
    queue = ProcQueue()
    for task in tasks:
        queue._procs[task.proc_id] = task
    return queue


@pytest.mark.asyncio
async def test_action_quit_with_running_tasks_pushes_quit_confirm_modal() -> None:
    running = _task("run-1", "sync", display_name="Sync visual-auth")
    completed = _task("done-1", "mail", status="success")
    app = _QuitApp(_queue(running, completed))

    await app.action_quit()

    assert app.did_quit is False
    assert app.killed_task_ids == []
    assert len(app.pushed) == 1
    modal, callback = app.pushed[0]
    assert isinstance(modal, QuitConfirmModal)
    assert callback is not None
    assert modal._tasks == [running]


@pytest.mark.asyncio
async def test_action_quit_confirm_kills_running_tasks_and_quits() -> None:
    sync = _task("run-sync", "sync")
    mail = _task("run-mail", "mail")
    completed = _task("done-accept", "accept", status="success")
    app = _QuitApp(_queue(sync, mail, completed))

    await app.action_quit()
    _, callback = app.pushed[0]
    callback(True)

    assert app.did_quit is True
    assert app.killed_task_ids == ["run-sync", "run-mail"]


@pytest.mark.asyncio
async def test_action_quit_cancel_keeps_tasks_running() -> None:
    app = _QuitApp(_queue(_task("run-sync", "sync")))

    await app.action_quit()
    _, callback = app.pushed[0]
    callback(False)
    callback(None)

    assert app.did_quit is False
    assert app.killed_task_ids == []


@pytest.mark.asyncio
async def test_action_quit_without_running_tasks_quits_without_modal() -> None:
    app = _QuitApp(_queue(_task("done-mail", "mail", status="success")))

    await app.action_quit()

    assert app.did_quit is True
    assert app.pushed == []
    assert app.killed_task_ids == []


@pytest.mark.asyncio
async def test_ordinary_quit_flushes_fold_state_before_exit() -> None:
    app = _FlushQuitApp()

    await app.action_quit()

    assert set(app.exit_events[:-1]) == {"flush-folds", "flush-admin-center"}
    assert app.exit_events[-1] == "quit"


@pytest.mark.asyncio
async def test_confirmed_quit_flushes_fold_state_before_exit() -> None:
    app = _FlushQuitApp(_queue(_task("run-sync", "sync")))

    await app.action_quit()
    _, callback = app.pushed[0]
    callback(True)
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
