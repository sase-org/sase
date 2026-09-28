from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui.util import shutdown
from sase.ace.tui.actions.lifecycle import LifecycleMixin
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.confirm_dialog import ConfirmKind
from sase.ace.tui.proc_observer import ObservedProc, ProcProjection


class _FakeWorker:
    def __init__(self, *, finished: bool = False) -> None:
        self._finished = finished

    @property
    def is_finished(self) -> bool:
        return self._finished


class _QuitApp(LifecycleMixin):
    def __init__(
        self,
        tasks: tuple[ObservedProc, ...] = (),
        *,
        session_rows: tuple[ObservedProc, ...] = (),
        durable_workers: dict[str, Any] | None = None,
    ) -> None:
        self._proc_projection = ProcProjection(
            rows=tasks,
            active_count=sum(1 for task in tasks if task.status == "running"),
        )
        self._session_rows = tuple(session_rows)
        self._durable_submit_workers = dict(durable_workers or {})
        self.pushed: list[tuple[Any, Any]] = []
        self.did_quit = False
        self._quit_confirm_open = False

    def _session_overlay_rows(self) -> tuple[ObservedProc, ...]:
        return self._session_rows

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

    async def _flush_agents_query_state(self) -> None:
        self.exit_events.append("flush-agents-query")

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


@pytest.mark.asyncio
async def test_action_quit_without_impact_quits_without_modal() -> None:
    # Durable proc rows alone must not prompt: they outlive the TUI.
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
async def test_action_quit_with_session_worker_confirms() -> None:
    worker = _task("session-1", "sync", display_name="Sync visual-auth")
    app = _QuitApp((), session_rows=(worker,))

    await app.action_quit()

    assert app.did_quit is False
    assert len(app.pushed) == 1
    modal, callback = app.pushed[0]
    assert isinstance(modal, ConfirmActionModal)
    assert modal._kind is ConfirmKind.DANGER
    assert modal._confirm_label == "Quit"
    assert modal._cancel_label == "Stay"

    callback(True)
    assert app.did_quit is True


@pytest.mark.asyncio
async def test_action_quit_decline_stays() -> None:
    worker = _task("session-1", "sync", display_name="Sync visual-auth")
    app = _QuitApp((), session_rows=(worker,))

    await app.action_quit()

    assert len(app.pushed) == 1
    _, callback = app.pushed[0]
    callback(False)

    assert app.did_quit is False


@pytest.mark.asyncio
async def test_action_quit_with_durable_submit_confirms() -> None:
    app = _QuitApp((), durable_workers={"pending-1": _FakeWorker(finished=False)})

    await app.action_quit()

    assert app.did_quit is False
    assert len(app.pushed) == 1
    assert isinstance(app.pushed[0][0], ConfirmActionModal)


@pytest.mark.asyncio
async def test_action_quit_finished_submit_does_not_prompt() -> None:
    app = _QuitApp((), durable_workers={"pending-1": _FakeWorker(finished=True)})

    await app.action_quit()

    assert app.did_quit is True
    assert app.pushed == []


@pytest.mark.asyncio
async def test_action_quit_guards_reentry() -> None:
    worker = _task("session-1", "sync", display_name="Sync visual-auth")
    app = _QuitApp((), session_rows=(worker,))

    await app.action_quit()
    await app.action_quit()

    assert len(app.pushed) == 1


@pytest.mark.asyncio
async def test_ordinary_quit_flushes_fold_state_before_exit() -> None:
    app = _FlushQuitApp()

    await app.action_quit()

    assert set(app.exit_events[:-1]) == {
        "flush-folds",
        "flush-admin-center",
        "flush-agents-query",
    }
    assert app.exit_events[-1] == "quit"


@pytest.mark.asyncio
async def test_confirmed_quit_flushes_fold_state_before_exit() -> None:
    app = _FlushQuitApp((_task("run-sync", "sync"),))

    await app.action_quit()
    await asyncio.gather(*app.scheduled)

    assert set(app.exit_events[:-1]) == {
        "flush-folds",
        "flush-admin-center",
        "flush-agents-query",
    }
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

    assert shutdown._shutdown_signal.is_requested() is True
    assert app.did_quit is False
    release.set()
    await quitting

    assert app.did_quit is True


@pytest.mark.asyncio
async def test_controlled_exit_waits_for_fold_state_flush() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class _WaitingFlushApp(_QuitApp):
        async def _flush_agents_fold_state(self) -> None:
            entered.set()
            await release.wait()

    app = _WaitingFlushApp()
    quitting = asyncio.create_task(app.action_quit())
    await asyncio.wait_for(entered.wait(), timeout=0.5)

    assert shutdown._shutdown_signal.is_requested() is True
    assert app.did_quit is False
    release.set()
    await quitting

    assert app.did_quit is True


@pytest.mark.asyncio
async def test_controlled_exit_waits_for_agents_query_flush() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class _WaitingFlushApp(_QuitApp):
        async def _flush_agents_query_state(self) -> None:
            entered.set()
            await release.wait()

    app = _WaitingFlushApp()
    quitting = asyncio.create_task(app.action_quit())
    await asyncio.wait_for(entered.wait(), timeout=0.5)

    assert shutdown._shutdown_signal.is_requested() is True
    assert app.did_quit is False
    release.set()
    await quitting

    assert app.did_quit is True
