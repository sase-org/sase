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
def test_telegram_receiver_does_not_delay_restart(
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

    assert app.restart_calls == [True]
    assert app.timers == []
    assert app.messages == [
        ("updated — restarting ACE to load new code.", "information")
    ]
    assert all(
        "queued" not in message and "expired" not in message
        for message, _ in app.messages
    )


def test_telegram_receiver_with_ordinary_work_waits_only_for_ordinary_work(
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
        ("updated - restart queued until 1 proc finishes.", "information")
    ]

    app._proc_projection = _projection(receiver, _ordinary_row(status="success"))
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
        "updated - restart wait expired; restarting with 1 proc: Sync workspace still active."
    ]
    assert _RECEIVER_LABEL not in warnings[0]


def test_restart_filter_matches_receiver_origin_not_label() -> None:
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

    assert [row.proc_id for row in blockers] == ["same-label"]


def test_restart_filter_preserves_projection_rows_and_counts() -> None:
    receiver = _receiver_row()
    monitor = _monitor_row()
    app = _App(receiver, monitor)
    projection = app._proc_projection

    assert running_background_procs(app) == []
    assert app._proc_projection is projection
    assert projection.rows == (receiver, monitor)
    assert projection.active_rows() == [receiver, monitor]
    assert projection.active_count == 2
    assert projection.active_monitor_count == 1
