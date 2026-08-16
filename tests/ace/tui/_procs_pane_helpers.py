"""Shared harness for Admin Center Procs tab tests."""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Any

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import logs_pane as lp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.procs_pane import ProcsPane
from sase.ace.tui.proc_observer import (
    ObservedProc,
    ProcProjection,
    compose_proc_projection,
)
from sase.ace.testing import wait_for
from sase.core.time import local_now, to_local
from sase.procs import Proc

ProcInfo = ObservedProc
_PATCHED_STORE_ROWS: list[ObservedProc] = []


def patch_other_panes(monkeypatch: pytest.MonkeyPatch) -> None:
    config_result = cp._LoadResult(view=None, error=None, token=("tasks", 1))
    monkeypatch.setattr(cp, "_load_config_view", lambda **_kw: config_result)
    plugins_result = pbp._PluginsLoadResult(catalog=None, error="stub", now=0.0)
    monkeypatch.setattr(pbp, "_load_plugins_catalog", lambda **_kw: plugins_result)
    monkeypatch.setattr(
        lp,
        "_build_log_pane_load_result",
        lambda _idx, _source_id=None: lp._LogPaneLoadResult([], [], 0, 0, Text("stub")),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_pane.get_all_prompts",
        lambda project=None: {},
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_project_local_prompts",
        lambda: {},
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_a, **_kw: [],
    )


@dataclass
class ProcQueue:
    _procs: dict[str, ProcInfo] = field(default_factory=dict)

    def get_all(self) -> list[ProcInfo]:
        for task in self._procs.values():
            live_buffer = getattr(task, "_live_buffer", None)
            if live_buffer is not None:
                task.output = live_buffer.getvalue()
        return sorted(
            self._procs.values(),
            key=lambda task: task.started_at,
            reverse=True,
        )

    def get(self, proc_id: str) -> ProcInfo | None:
        return self._procs.get(proc_id)

    def complete(
        self,
        proc_id: str,
        *,
        success: bool,
        message: str,
        output: str,
        error: str | None = None,
    ) -> None:
        task = self._procs[proc_id]
        task.status = "success" if success else "error"
        task.message = message
        task.output = output
        task.error = error
        task.finished_at = task.started_at + timedelta(seconds=3)
        if hasattr(task, "_live_buffer"):
            delattr(task, "_live_buffer")

    def remove(self, proc_id: str) -> None:
        self._procs.pop(proc_id, None)

    def remove_completed(self) -> None:
        self._procs = {
            proc_id: task
            for proc_id, task in self._procs.items()
            if task.status in {"pending", "running"}
        }


class ProcsTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        proc_queue: ProcQueue,
        session_rows: tuple[ObservedProc, ...] = (),
    ) -> None:
        super().__init__()
        self._proc_queue = proc_queue
        self._session_overlay = session_rows
        self.killed_task_ids: list[str] = []
        self.notifications: list[tuple[str, str | None]] = []

    @property
    def _proc_projection(self) -> ProcProjection:
        rows = (*self._proc_queue.get_all(), *_PATCHED_STORE_ROWS)
        projection = ProcProjection(rows=rows, session_id="session-mine")
        return ProcProjection(
            rows=rows,
            active_count=len(projection.active_rows()),
            session_id="session-mine",
        )

    def _effective_proc_projection(self) -> ProcProjection:
        return compose_proc_projection(self._proc_projection, self._session_overlay)

    def compose(self) -> ComposeResult:
        yield from ()

    def _kill_proc(self, proc_id: str) -> bool:
        self.killed_task_ids.append(proc_id)
        self._proc_queue.complete(
            proc_id,
            success=False,
            message="Killed by user",
            output="",
            error="Killed by user",
        )
        return True

    def notify(
        self,
        message: str,
        *,
        title: str = "",
        severity: str = "information",
        timeout: float | None = None,
        markup: bool = True,
    ) -> None:
        del title, timeout, markup
        self.notifications.append((message, severity))


def task(
    proc_id: str,
    *,
    label: str,
    status: str,
    age_seconds: int,
    output: str = "",
    error: str | None = None,
    live_output: str | None = None,
) -> ProcInfo:
    started_at = datetime.now() - timedelta(seconds=age_seconds)
    info = ProcInfo(
        proc_id=proc_id,
        proc_type=label.split()[0],
        cl_name="",
        project_file="",
        status=status,
        message=f"{label} complete",
        started_at=started_at,
        display_name=label,
        finished_at=(
            started_at + timedelta(seconds=3) if status != "running" else None
        ),
        output=output,
        error=error,
    )
    if live_output is not None:
        info._live_buffer = io.StringIO(live_output)
        info.output = live_output
    return info


def queue(*tasks: ProcInfo) -> ProcQueue:
    return ProcQueue(_procs={task.proc_id: task for task in tasks})


async def open_procs_pane(
    pilot: Any,
    *,
    session_state: AdminCenterSessionState | None = None,
) -> tuple[ConfigCenterModal, ProcsPane]:
    modal = ConfigCenterModal(initial_tab="procs", session_state=session_state)
    pilot.app.push_screen(modal)
    await pilot.pause()
    pane = modal.query_one("#procs", ProcsPane)
    await wait_for(pilot, lambda: pane._store_loaded_once or True)
    return modal, pane


def output_plain(pane: ProcsPane) -> str:
    return pane.query_one("#procs-output-content", Static).render().plain


def store_task(
    proc_id: str,
    *,
    label: str,
    status: str,
    session_id: str | None,
    session_label: str | None = None,
    kind: str = "command",
    message: str = "",
) -> Proc:
    return Proc(
        proc_id=proc_id,
        label=label,
        kind=kind,
        status=status,
        command=["sase", "bead", "work", "plan.md"],
        cwd="/tmp",
        origin="cli",
        created_at="2026-06-26T11:58:00Z",
        started_at="2026-06-26T11:58:00Z",
        finished_at=None
        if status in {"pending", "running"}
        else "2026-06-26T11:59:00Z",
        log_path=f"/tmp/{proc_id}.log",
        session_id=session_id,
        session_label=session_label,
        message=message or None,
    )


def _store_task_row(
    record: Proc,
    *,
    live_session_ids: frozenset[str] = frozenset(),
    output: str = "",
) -> ObservedProc:
    started_at = _local_datetime(record.started_at or record.created_at) or local_now()
    return ObservedProc(
        proc_id=record.proc_id,
        proc_type=record.kind,
        cl_name=record.cl_name or "",
        project_file="",
        status=record.status,
        message=record.message or "",
        started_at=started_at,
        display_name=record.label,
        finished_at=_local_datetime(record.finished_at),
        output=output,
        error=record.message if record.status in {"error", "killed"} else None,
        command=list(record.command) or None,
        phase=record.phase,
        exit_code=record.exit_code,
        durable_proc_id=record.proc_id,
        store_backed=True,
        session_id=record.session_id,
        session_label=record.session_label,
        session_live=bool(record.session_id and record.session_id in live_session_ids),
    )


def _local_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    return to_local(parsed)


def patch_store_loader(
    monkeypatch: pytest.MonkeyPatch,
    tasks: list[Proc],
    *,
    live_session_ids: frozenset[str] = frozenset(),
    output: str = "",
) -> list[dict[str, Any]]:
    """Serve durable rows through the test app's observer projection."""
    calls: list[dict[str, Any]] = []

    rows = [
        _store_task_row(
            store_record,
            live_session_ids=live_session_ids,
            output=output,
        )
        for store_record in tasks
    ]
    monkeypatch.setattr(
        "tests.ace.tui._procs_pane_helpers._PATCHED_STORE_ROWS",
        rows,
    )
    return calls
