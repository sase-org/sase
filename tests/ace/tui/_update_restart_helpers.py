"""Shared fixtures for ACE update restart tests."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.proc_observer import (
    ObservedProc,
    ProcProjection,
    recount_projection,
    store_proc_row,
)
from sase.monitor_state import MONITOR_PROC_ORIGIN
from sase.procs import Proc
from sase.procs.service_meta import (
    SERVICE_HOST_ORIGIN,
    SERVICE_ONESHOT_ORIGIN,
    SERVICE_PROC_MODE_DAEMON,
    SERVICE_PROC_MODE_ONESHOT,
    SERVICE_PROC_SOURCE_BUILTIN,
    SERVICE_PROC_SOURCE_TRANSIENT,
    ProcServiceBlock,
)


class App(SimpleNamespace):
    def __init__(
        self,
        *rows: ObservedProc,
        overlay: tuple[ObservedProc, ...] = (),
        submit_workers: dict[str, Any] | None = None,
        session_workers: dict[str, Any] | None = None,
        callbacks: dict[str, Any] | None = None,
        observer: Any | None = None,
    ) -> None:
        super().__init__()
        self._proc_projection = _projection(*rows)
        self._session_overlay = list(overlay)
        self._session_workers = dict(session_workers or {})
        self._durable_submit_workers = dict(submit_workers or {})
        self._proc_completion_callbacks = dict(callbacks or {})
        self._proc_observer = observer
        self.messages: list[tuple[str, str]] = []
        self.restart_calls: list[bool] = []
        self.timers: list[tuple[float, Any]] = []

    def _session_overlay_rows(self) -> tuple[ObservedProc, ...]:
        return tuple(self._session_overlay)

    def _effective_proc_projection(self) -> ProcProjection:
        return self._proc_projection

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.messages.append((message, severity))

    def set_timer(self, delay: float, callback: Any) -> object:
        self.timers.append((delay, callback))
        return SimpleNamespace(stop=lambda: None)

    def _restart_tui(self, *, restart_axe: bool) -> None:
        self.restart_calls.append(restart_axe)


def _projection(*rows: ObservedProc) -> ProcProjection:
    return recount_projection(ProcProjection(rows=tuple(rows), session_id="session-a"))


def session_row(
    *,
    status: str = "running",
    proc_id: str = "session-sync",
    label: str = "local sync",
    proc_type: str = "sync",
) -> ObservedProc:
    return ObservedProc(
        proc_id=proc_id,
        proc_type=proc_type,
        cl_name="",
        project_file="",
        status=status,
        message="running",
        started_at=datetime(2026, 9, 15, 12, 0, 0),
        display_name=label,
        session_id="session-a",
    )


def tool_run_row(
    *,
    status: str = "running",
    label: str = "tool:check",
    proc_id: str = "tool-run-1",
    session_id: str | None = "session-a",
    command: list[str] | None = None,
) -> ObservedProc:
    return store_proc_row(
        Proc(
            proc_id=proc_id,
            label=label,
            kind="command",
            status=status,
            command=command or ["sase", "tool", "run", "check"],
            cwd="/tmp",
            origin="tool-run",
            created_at="2026-09-15T12:00:00Z",
            started_at="2026-09-15T12:00:00Z",
            log_path=f"/tmp/{proc_id}.log",
            message="running",
            session_id=session_id,
        )
    )


def install_row(
    *,
    proc_id: str = "plugin-install-1",
    proc_type: str = "plugin.install",
    scopes: frozenset[str] = frozenset({"plugin-install:sample"}),
    status: str = "running",
    label: str = "plugin install sample",
    session_id: str | None = None,
) -> ObservedProc:
    return ObservedProc(
        proc_id=proc_id,
        proc_type=proc_type,
        cl_name="",
        project_file="",
        status=status,
        message="installing",
        started_at=datetime(2026, 9, 15, 12, 0, 0),
        display_name=label,
        exclusive_scopes=scopes,
        session_id=session_id,
        durable_proc_id=proc_id,
    )


def ordinary_row(
    *,
    status: str = "running",
    label: str = "Sync workspace",
    origin: str = "ace",
    proc_id: str = "ordinary-work",
    session_id: str | None = "session-a",
) -> ObservedProc:
    return store_proc_row(
        Proc(
            proc_id=proc_id,
            label=label,
            kind="command",
            status=status,
            command=["sase", "sync"],
            cwd="/tmp",
            origin=origin,
            created_at="2026-09-15T12:00:00Z",
            started_at="2026-09-15T12:00:00Z",
            log_path=f"/tmp/{proc_id}.log",
            message="running",
            session_id=session_id,
        )
    )


def service_row(
    *,
    proc_id: str = "service-gateway",
    origin: str = SERVICE_HOST_ORIGIN,
    service: ProcServiceBlock | None = None,
) -> ObservedProc:
    return store_proc_row(
        Proc(
            proc_id=proc_id,
            label=proc_id,
            kind="command",
            status="running",
            command=["sase", "service"],
            cwd="/tmp",
            origin=origin,
            created_at="2026-09-20T12:00:00Z",
            started_at="2026-09-20T12:00:00Z",
            log_path=f"/tmp/{proc_id}.log",
            message="running",
            service=service,
        )
    )


def daemon_block(name: str = "gateway") -> ProcServiceBlock:
    return ProcServiceBlock(
        name=name,
        mode=SERVICE_PROC_MODE_DAEMON,
        source=SERVICE_PROC_SOURCE_BUILTIN,
    )


def oneshot_row() -> ObservedProc:
    return service_row(
        proc_id="bgcmd-1",
        origin=SERVICE_ONESHOT_ORIGIN,
        service=ProcServiceBlock(
            name=None,
            mode=SERVICE_PROC_MODE_ONESHOT,
            source=SERVICE_PROC_SOURCE_TRANSIENT,
        ),
    )


def monitor_row() -> ObservedProc:
    return ObservedProc(
        proc_id="monitor-1",
        proc_type="command",
        cl_name="",
        project_file="",
        status="running",
        message="monitoring",
        started_at=datetime(2026, 9, 15, 12, 0, 0),
        display_name="monitor turn",
        origin=MONITOR_PROC_ORIGIN,
    )
