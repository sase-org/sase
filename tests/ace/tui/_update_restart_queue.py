"""Deferred restart-chain tests for ACE updates."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.proc_observer import ObservedProc
from sase.ace.tui.update_restart import restart_after_update_when_ready
from ._update_restart_helpers import (
    App,
    install_row,
    ordinary_row,
    session_row,
    tool_run_row,
)


class _PendingApp(App):
    def __init__(
        self,
        *rows: ObservedProc,
        overlay: tuple[ObservedProc, ...] = (),
        submit_workers: dict[str, Any] | None = None,
        session_workers: dict[str, Any] | None = None,
        callbacks: dict[str, Any] | None = None,
        observer: Any | None = None,
    ) -> None:
        super().__init__(
            *rows,
            overlay=overlay,
            submit_workers=submit_workers,
            session_workers=session_workers,
            callbacks=callbacks,
            observer=observer,
        )
        self.pending: list[object | None] = []
        self._pending_restart_chain: dict[str, object] | None = None

    def _set_pending_update_restart(self, pending: object | None) -> None:
        self.pending.append(pending)


def _monotonic(value: float):
    return lambda: value


def test_coalesced_request_with_zero_blockers_restarts_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = session_row()
    app = _PendingApp(overlay=(session,))
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", lambda: 100.0)
    monkeypatch.setattr("sase.ace.tui.update_restart.time.time", lambda: 1700000000.0)

    restart_after_update_when_ready(app, "first", deferred=False)
    assert app.restart_calls == []
    assert len(app.timers) == 1

    app._session_overlay.clear()
    restart_after_update_when_ready(app, "second", deferred=False)

    assert app.restart_calls == [True]
    assert not any("0 " in message for message, _ in app.messages)
    assert app.messages[-1][0].startswith("second — restarting ACE")


def test_stale_timer_does_not_restart_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = session_row()
    app = _PendingApp(overlay=(session,))
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", lambda: 100.0)
    monkeypatch.setattr("sase.ace.tui.update_restart.time.time", lambda: 1700000000.0)

    restart_after_update_when_ready(app, "updated", deferred=False)
    callback = app.timers[0][1]
    app._session_overlay.clear()
    callback()

    assert app.restart_calls == [True]
    callback()
    assert app.restart_calls == [True]


def test_timeout_summary_uses_actual_blockers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = session_row()
    app = App(ordinary_row(), overlay=(session,))
    now = {"mono": 100.0}
    monkeypatch.setattr(
        "sase.ace.tui.update_restart.time.monotonic",
        lambda: now["mono"],
    )
    monkeypatch.setattr("sase.ace.tui.update_restart.time.time", lambda: 1700000000.0)

    restart_after_update_when_ready(app, "updated", deferred=False)
    assert app.restart_calls == []
    assert app.timers

    now["mono"] = 161.0
    app.timers[0][1]()

    assert app.restart_calls == [True]
    warnings = [message for message, severity in app.messages if severity == "warning"]
    assert warnings == [
        "updated - restart wait expired; restarting with 1 TUI task: "
        "local sync still active."
    ]


def test_tracked_deferred_publishes_pending_and_refreshes_on_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_row = session_row()
    app = _PendingApp(overlay=(first_row,))
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", _monotonic(100.0))
    monkeypatch.setattr("sase.ace.tui.update_restart.time.time", lambda: 1700000000.0)

    restart_after_update_when_ready(app, "updated", deferred=False)

    assert len(app.pending) == 1
    first = app.pending[0]
    assert getattr(first, "blocker_labels", ()) == ("local sync",)
    assert getattr(first, "blocker_identities", ()) == ("session-sync",)
    assert getattr(first, "restart_by", 0) == 1700000060.0
    assert getattr(first, "wait_phrase", "") == "1 TUI task finishes"
    assert app.timers != []

    app._session_overlay = [session_row(label="Other", proc_id="other-sync")]
    monkeypatch.setattr("sase.ace.tui.update_restart.time.time", lambda: 1700000001.0)
    app.timers[0][1]()

    assert len(app.pending) == 2
    second = app.pending[1]
    assert getattr(second, "blocker_labels", ()) == ("Other",)
    assert getattr(second, "queued_at", None) == getattr(first, "queued_at", None)
    assert getattr(second, "restart_by", None) == getattr(first, "restart_by", None)


def test_immediate_restart_publishes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _PendingApp()
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", _monotonic(100.0))

    restart_after_update_when_ready(app, "updated", deferred=False)

    assert app.restart_calls == [True]
    assert app.pending == []


def test_untracked_chain_never_publishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _PendingApp(overlay=(session_row(),))
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", _monotonic(100.0))

    restart_after_update_when_ready(app, "updated", deferred=False, track_pending=False)

    assert app.pending == []
    assert app.timers != []
    assert getattr(app, "_pending_restart_chain", None) is None


def test_second_tracked_request_coalesces_into_one_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _PendingApp(overlay=(session_row(),))
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", _monotonic(100.0))
    monkeypatch.setattr("sase.ace.tui.update_restart.time.time", lambda: 1700000000.0)

    restart_after_update_when_ready(app, "first", deferred=False)
    assert len(app.timers) == 1

    restart_after_update_when_ready(app, "second", deferred=False)

    assert len(app.timers) == 1
    assert app.messages[0][0].startswith("first - restart queued")
    assert app.messages[1][0].startswith("second - restart queued")

    app._session_overlay.clear()
    app.timers[0][1]()

    assert app.restart_calls == [True]
    assert app.messages[-1][0].startswith("second — restarting ACE")


def test_pending_cleared_when_restart_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = SimpleNamespace(
        messages=[],
        timers=[],
        pending=[],
        _pending_restart_chain=None,
    )
    app.notify = lambda message, *, severity="information": app.messages.append(  # type: ignore[attr-defined]
        (message, severity)
    )

    def _set_pending(pending: object | None) -> None:
        app.pending.append(pending)

    app._set_pending_update_restart = _set_pending  # type: ignore[attr-defined]

    def _set_timer(delay: float, callback: object) -> object:
        app.timers.append((delay, callback))
        return SimpleNamespace(stop=lambda: None)

    app.set_timer = _set_timer  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "sase.ace.tui.update_restart.running_background_procs",
        lambda _app: [],
    )

    restart_after_update_when_ready(app, "updated", deferred=False)

    assert app.pending == [None]
