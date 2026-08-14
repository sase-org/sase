"""Shared harness for Admin Center Procs tab tests."""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from typing import Any

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import logs_pane as lp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals import procs_pane as tp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.procs_pane import ProcsPane
from sase.ace.tui.modals.procs_store_rows import StoreTasksSnapshot, _store_task_row
from sase.ace.tui.proc_queue import ProcInfo, ProcQueue
from sase.ace.testing import wait_for
from sase.procs import Proc


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


class ProcsTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, proc_queue: ProcQueue) -> None:
        super().__init__()
        self._proc_queue = proc_queue
        self.killed_task_ids: list[str] = []
        self.notifications: list[tuple[str, str | None]] = []

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
    await wait_for(pilot, lambda: not pane._store_load_pending)
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


def patch_store_loader(
    monkeypatch: pytest.MonkeyPatch,
    tasks: list[Proc],
    *,
    live_session_ids: frozenset[str] = frozenset(),
    output: str = "",
) -> list[dict[str, Any]]:
    """Serve store rows without touching disk, recording each load request."""
    calls: list[dict[str, Any]] = []

    def _fake_load(
        *,
        session_id: str | None,
        all_sessions: bool,
        known_mtime: float | None = None,
        known_detail_task_id: str | None = None,
        detail_task_id: str | None = None,
    ) -> StoreTasksSnapshot:
        calls.append(
            {
                "session_id": session_id,
                "all_sessions": all_sessions,
                "detail_task_id": detail_task_id,
                "known_mtime": known_mtime,
            }
        )
        rows = [
            _store_task_row(store_task, live_session_ids=live_session_ids)
            for store_task in tasks
            if all_sessions or store_task.session_id in (None, session_id)
        ]
        for row in rows:
            if row.proc_id == detail_task_id:
                row.output = output
        return StoreTasksSnapshot(
            rows=rows,
            live_session_ids=live_session_ids,
            mtime=1.0,
            detail_task_id=detail_task_id,
            all_sessions=all_sessions,
        )

    monkeypatch.setattr(tp, "load_store_task_rows", _fake_load)
    monkeypatch.setattr(tp, "current_tui_session_id", lambda: "session-mine")
    return calls
