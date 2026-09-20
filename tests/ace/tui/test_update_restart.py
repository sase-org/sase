"""Regression tests for ACE restart waiting after code-changing updates."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.update_restart import (
    restart_after_update_when_ready,
    running_background_procs,
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
from sase.ace.tui.proc_observer import (
    ObservedProc,
    ProcProjection,
    recount_projection,
    store_proc_row,
)

_STARTED_AT = "2026-09-14T20:30:30.456885Z"
_RECEIVER_LABEL = "Telegram inbound long-poll receiver"
_TELEGRAM_RECEIVER_ORIGIN = "telegram-receiver"


class _App(SimpleNamespace):
    def __init__(self, *rows: ObservedProc) -> None:
        super().__init__()
        self._proc_projection = _projection(*rows)
        self.messages: list[tuple[str, str]] = []
        self.restart_calls: list[bool] = []
        self.timers: list[tuple[float, Any]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.messages.append((message, severity))

    def set_timer(self, delay: float, callback: Any) -> object:
        self.timers.append((delay, callback))
        return SimpleNamespace(stop=lambda: None)

    def _restart_tui(self, *, restart_axe: bool) -> None:
        self.restart_calls.append(restart_axe)


def _projection(*rows: ObservedProc) -> ProcProjection:
    return recount_projection(ProcProjection(rows=tuple(rows), session_id="session-a"))


def _receiver_row(
    *,
    status: str = "running",
    label: str = _RECEIVER_LABEL,
    origin: str = _TELEGRAM_RECEIVER_ORIGIN,
    proc_id: str = "telegram-receiver",
) -> ObservedProc:
    return store_proc_row(
        Proc(
            proc_id=proc_id,
            label=label,
            kind="command",
            status=status,
            command=[],
            cwd="/tmp",
            origin=origin,
            created_at=_STARTED_AT,
            started_at=_STARTED_AT,
            log_path="/tmp/telegram-receiver.log",
            message="polling",
        )
    )


def _ordinary_row(
    *,
    status: str = "running",
    label: str = "Sync workspace",
    origin: str = "ace",
    proc_id: str = "ordinary-work",
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
        )
    )


def _service_row(
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


def _daemon_block(name: str = "gateway") -> ProcServiceBlock:
    return ProcServiceBlock(
        name=name,
        mode=SERVICE_PROC_MODE_DAEMON,
        source=SERVICE_PROC_SOURCE_BUILTIN,
    )


def _oneshot_row() -> ObservedProc:
    return _service_row(
        proc_id="bgcmd-1",
        origin=SERVICE_ONESHOT_ORIGIN,
        service=ProcServiceBlock(
            name=None,
            mode=SERVICE_PROC_MODE_ONESHOT,
            source=SERVICE_PROC_SOURCE_TRANSIENT,
        ),
    )


def _monitor_row() -> ObservedProc:
    return ObservedProc(
        proc_id="monitor-1",
        proc_type="command",
        cl_name="",
        project_file="",
        status="running",
        message="monitoring",
        started_at=datetime(2026, 9, 15, 12, 0, 0),
        display_name="monitor shell",
        origin=MONITOR_PROC_ORIGIN,
    )


@pytest.mark.parametrize("status", ["pending", "running", "settling"])
@pytest.mark.parametrize("with_monitor", [False, True])
def test_telegram_receiver_delays_restart(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    with_monitor: bool,
) -> None:
    rows = [_receiver_row(status=status)]
    if with_monitor:
        rows.append(_monitor_row())
    app = _App(*rows)
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", lambda: 100.0)

    restart_after_update_when_ready(app, "updated", deferred=False)

    assert app.restart_calls == []
    assert [(delay, callable(callback)) for delay, callback in app.timers] == [
        (1.0, True)
    ]
    assert app.messages == [
        ("updated - restart queued until 1 proc finishes.", "information")
    ]


def test_telegram_receiver_with_ordinary_work_waits_for_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver = _receiver_row()
    ordinary = _ordinary_row()
    app = _App(receiver, ordinary)
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", lambda: 100.0)

    restart_after_update_when_ready(app, "updated", deferred=False)

    assert app.restart_calls == []
    assert [(delay, callable(callback)) for delay, callback in app.timers] == [
        (1.0, True)
    ]
    assert app.messages == [
        ("updated - restart queued until 2 procs finish.", "information")
    ]

    app._proc_projection = _projection(
        _receiver_row(status="success"),
        _ordinary_row(status="success"),
    )
    app.timers[0][1]()

    assert app.restart_calls == [True]
    assert app.messages[-1] == (
        "updated — restarting ACE to load new code.",
        "information",
    )


def test_ordinary_work_timeout_summary_omits_receiver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _App(_receiver_row(), _ordinary_row())
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", lambda: 100.0)

    restart_after_update_when_ready(
        app,
        "updated",
        deferred=True,
        deadline=99.0,
    )

    assert app.restart_calls == [True]
    warnings = [message for message, severity in app.messages if severity == "warning"]
    assert warnings == [
        "updated - restart wait expired; restarting with 2 procs: "
        "Telegram inbound long-poll receiver, Sync workspace still active."
    ]


def test_restart_filter_treats_receiver_like_ordinary_proc() -> None:
    app = _App(
        _receiver_row(
            proc_id="same-label",
            origin="ace",
            label=_RECEIVER_LABEL,
        ),
        _receiver_row(
            proc_id="same-origin",
            origin=_TELEGRAM_RECEIVER_ORIGIN,
            label="Long poller renamed",
        ),
    )

    blockers = running_background_procs(app)

    assert [row.proc_id for row in blockers] == ["same-label", "same-origin"]


def test_restart_filter_preserves_projection_rows_and_counts() -> None:
    receiver = _receiver_row()
    monitor = _monitor_row()
    app = _App(receiver, monitor)
    projection = app._proc_projection

    assert running_background_procs(app) == [receiver]
    assert app._proc_projection is projection
    assert projection.rows == (receiver, monitor)
    assert projection.active_rows() == [receiver, monitor]
    assert projection.active_count == 2
    assert projection.active_monitor_count == 1


@pytest.mark.parametrize("marked", [True, False], ids=["with-block", "origin-only"])
def test_restart_filter_ignores_service_daemons(marked: bool) -> None:
    daemon = _service_row(service=_daemon_block() if marked else None)
    ordinary = _ordinary_row()
    app = _App(daemon, ordinary)

    assert running_background_procs(app) == [ordinary]


def test_restart_filter_keeps_transient_oneshots_as_blockers() -> None:
    oneshot = _oneshot_row()
    app = _App(_service_row(service=_daemon_block()), oneshot)

    assert running_background_procs(app) == [oneshot]


def test_oneshot_without_service_block_still_blocks_restart() -> None:
    # Origin alone marks a row as service-owned, but only a daemon never ends.
    oneshot = _service_row(proc_id="bgcmd-2", origin=SERVICE_ONESHOT_ORIGIN)

    assert running_background_procs(_App(oneshot)) == [oneshot]


@pytest.mark.parametrize("marked", [True, False], ids=["with-block", "origin-only"])
def test_daemon_only_projection_restarts_immediately(
    monkeypatch: pytest.MonkeyPatch, marked: bool
) -> None:
    app = _App(
        _service_row(
            proc_id="service-gateway", service=_daemon_block() if marked else None
        ),
        _service_row(
            proc_id="service-scheduler",
            service=_daemon_block("scheduler") if marked else None,
        ),
        _monitor_row(),
    )
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", lambda: 100.0)

    restart_after_update_when_ready(app, "updated", deferred=False)

    assert app.restart_calls == [True]
    assert app.timers == []
    assert not any("restart queued until" in message for message, _ in app.messages)
    assert app.messages == [
        ("updated — restarting ACE to load new code.", "information")
    ]
