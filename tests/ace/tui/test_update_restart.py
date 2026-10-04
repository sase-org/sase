"""Regression tests for ACE restart waiting after code-changing updates."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui._proc_observer_models import is_install_mutation_row
from sase.ace.tui.actions._proc_action_completion import ProcCompletionActionsMixin
from sase.ace.tui.actions._proc_action_types import ProcCallbackConfig
from sase.ace.tui.proc_observer import (
    ObservedProc,
    ProcCompletionRecord,
    ProcObserverSnapshot,
    ProcProjection,
    recount_projection,
    store_proc_row,
)
from sase.ace.tui.update_restart import (
    RestartBlocker,
    collect_restart_blockers,
    restart_after_update_when_ready,
    running_background_procs,
)
from sase.monitor_state import MONITOR_PROC_ORIGIN
from sase.ops import DurableOperationResult
from sase.procs import Proc, TUI_PROC_KIND
from sase.procs.service_meta import (
    SERVICE_HOST_ORIGIN,
    SERVICE_ONESHOT_ORIGIN,
    SERVICE_PROC_MODE_DAEMON,
    SERVICE_PROC_MODE_ONESHOT,
    SERVICE_PROC_SOURCE_BUILTIN,
    SERVICE_PROC_SOURCE_TRANSIENT,
    ProcServiceBlock,
)

_STARTED_AT = "2026-09-14T20:30:30.456885Z"
_RECEIVER_LABEL = "Telegram inbound long-poll receiver"
_TELEGRAM_RECEIVER_ORIGIN = "telegram-receiver"


class _App(SimpleNamespace):
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


class _PendingApp(_App):
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


def _projection(*rows: ObservedProc) -> ProcProjection:
    return recount_projection(ProcProjection(rows=tuple(rows), session_id="session-a"))


def _blocker_ids(app: _App) -> list[str]:
    return [item.identity for item in collect_restart_blockers(app)]


def _blocker_kinds(app: _App) -> list[str]:
    return [item.kind for item in collect_restart_blockers(app)]


def _session_row(
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


def _receiver_row(
    *,
    status: str = "running",
    label: str = _RECEIVER_LABEL,
    origin: str = _TELEGRAM_RECEIVER_ORIGIN,
    proc_id: str = "telegram-receiver",
    session_id: str | None = None,
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
            session_id=session_id,
        )
    )


def _ordinary_row(
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


def _tool_run_row(
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


def _install_row(
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


def _legacy_tui_row(
    *,
    proc_id: str = "legacy-tui",
    session_id: str | None = None,
    status: str = "running",
    label: str = "legacy TUI task",
) -> ObservedProc:
    return store_proc_row(
        Proc(
            proc_id=proc_id,
            label=label,
            kind=TUI_PROC_KIND,
            status=status,
            command=[],
            cwd="/tmp",
            origin="ace",
            created_at="2026-09-15T12:00:00Z",
            started_at="2026-09-15T12:00:00Z",
            log_path=f"/tmp/{proc_id}.log",
            message="running",
            session_id=session_id,
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
        display_name="monitor turn",
        origin=MONITOR_PROC_ORIGIN,
    )


def _monotonic(value: float):
    return lambda: value


@pytest.mark.parametrize("status", ["pending", "running", "settling"])
@pytest.mark.parametrize(
    "session_id", ["session-a", None], ids=["current", "unattributed"]
)
def test_tool_run_rows_do_not_block_restart(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    session_id: str | None,
) -> None:
    app = _App(_tool_run_row(status=status, session_id=session_id))
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", lambda: 100.0)

    restart_after_update_when_ready(app, "updated", deferred=False)

    assert app.restart_calls == [True]
    assert app.timers == []
    assert not any("restart queued until" in message for message, _ in app.messages)
    assert app.messages == [
        ("updated — restarting ACE to load new code.", "information")
    ]


def test_renamed_tool_run_argv_still_does_not_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _App(
        _tool_run_row(
            label="ad-hoc lint",
            command=["sase", "tool", "run", "lint"],
            proc_id="tool-run-adhoc",
        )
    )
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", lambda: 100.0)

    restart_after_update_when_ready(app, "updated", deferred=False)

    assert app.restart_calls == [True]
    assert app.timers == []


def test_ordinary_durable_work_does_not_block_restart() -> None:
    app = _App(
        _ordinary_row(),
        _receiver_row(),
        _oneshot_row(),
        _monitor_row(),
        _service_row(service=_daemon_block()),
        _service_row(proc_id="bgcmd-2", origin=SERVICE_ONESHOT_ORIGIN),
        _ordinary_row(proc_id="other-tui", session_id="session-b"),
    )

    assert collect_restart_blockers(app) == ()
    assert running_background_procs(app) == []


def test_visibility_cannot_control_restart_safety() -> None:
    receiver = _receiver_row()
    monitor = _monitor_row()
    app = _App(receiver, monitor)
    projection = app._proc_projection

    assert collect_restart_blockers(app) == ()
    assert app._proc_projection is projection
    assert projection.rows == (receiver, monitor)
    assert {row.proc_id for row in projection.active_rows()} == {
        receiver.proc_id,
        monitor.proc_id,
    }
    assert projection.active_count == 2
    assert projection.active_monitor_count == 1


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


def test_session_overlay_blocks_even_after_worker_status_settles() -> None:
    finished = _session_row(status="success")
    app = _App(overlay=(finished,))

    blockers = collect_restart_blockers(app)

    assert [item.identity for item in blockers] == [finished.proc_id]
    assert [item.kind for item in blockers] == ["session_worker"]
    assert [item.label for item in blockers] == ["local sync"]


def test_leftover_session_worker_key_blocks_without_overlay() -> None:
    app = _App(session_workers={"orphan-worker": SimpleNamespace()})

    blockers = collect_restart_blockers(app)

    assert blockers == (
        RestartBlocker(
            identity="orphan-worker",
            label="TUI task",
            kind="session_worker",
        ),
    )


def test_finished_submit_worker_still_blocks_until_map_pops() -> None:
    app = _App(submit_workers={"ph-1": SimpleNamespace(is_finished=True)})

    blockers = collect_restart_blockers(app)

    assert blockers == (
        RestartBlocker(
            identity="ph-1",
            label="durable submission",
            kind="submission",
        ),
    )


def test_submission_placeholder_and_durable_install_dedup() -> None:
    durable = _install_row(proc_id="plugin-install-1")
    durable.durable_proc_id = "plugin-install-1"
    placeholder = ObservedProc(
        proc_id="ph-install",
        proc_type="plugin.install",
        cl_name="",
        project_file="",
        status="running",
        message="submitting",
        started_at=datetime(2026, 9, 15, 12, 0, 0),
        display_name="plugin install sample",
        exclusive_scopes=frozenset({"plugin-install:sample"}),
        durable_proc_id="plugin-install-1",
    )
    app = _App(
        placeholder,
        durable,
        submit_workers={"ph-install": SimpleNamespace(is_finished=False)},
    )

    blockers = collect_restart_blockers(app)

    assert [item.identity for item in blockers] == ["ph-install"]
    assert [item.kind for item in blockers] == ["submission"]


@pytest.mark.parametrize(
    ("proc_type", "scopes"),
    [
        ("plugin.install", frozenset({"plugin-install:sample"})),
        ("plugin.uninstall", frozenset({"plugin-uninstall:sample"})),
        ("plugin.update", frozenset({"plugin-update:sample"})),
        ("sase-update", frozenset({"sase-update"})),
        ("command", frozenset({"plugin-install:sample"})),
        ("command", frozenset({"plugin-uninstall:sample"})),
    ],
)
def test_install_mutations_block_regardless_of_session(
    proc_type: str, scopes: frozenset[str]
) -> None:
    other_session = _install_row(
        proc_id="other-install",
        proc_type=proc_type,
        scopes=scopes,
        session_id="dead-session",
    )
    app = _App(other_session)

    blockers = collect_restart_blockers(app)

    assert [item.identity for item in blockers] == ["other-install"]
    assert [item.kind for item in blockers] == ["install"]
    assert is_install_mutation_row(other_session) is True


def test_plugin_install_is_not_an_update_lane_row() -> None:
    from sase.ace.tui._proc_observer_models import is_update_row

    row = _install_row()
    assert is_install_mutation_row(row) is True
    assert is_update_row(row) is False


def test_monitor_and_daemon_are_not_install_mutations() -> None:
    monitor = ObservedProc(
        proc_id="monitor-update",
        proc_type="sase-update",
        cl_name="",
        project_file="",
        status="running",
        message="monitoring",
        started_at=datetime(2026, 9, 15, 12, 0, 0),
        exclusive_scopes=frozenset({"sase-update"}),
        origin=MONITOR_PROC_ORIGIN,
    )
    daemon = _service_row(service=_daemon_block())
    daemon.proc_type = "sase-update"
    daemon.exclusive_scopes = frozenset({"sase-update"})

    assert is_install_mutation_row(monitor) is False
    assert is_install_mutation_row(daemon) is False
    assert collect_restart_blockers(_App(monitor, daemon)) == ()


def test_local_legacy_tui_blocks_and_other_tui_does_not() -> None:
    local = _legacy_tui_row(proc_id="local-tui", session_id="session-a")
    unattributed = _legacy_tui_row(proc_id="unattributed-tui", session_id=None)
    other = _legacy_tui_row(proc_id="other-tui", session_id="session-b")
    app = _App(local, unattributed, other)

    assert _blocker_ids(app) == ["local-tui", "unattributed-tui"]
    assert _blocker_kinds(app) == ["legacy_tui", "legacy_tui"]


def test_mixed_independent_work_waits_only_for_local_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session_row()
    app = _App(_tool_run_row(), _ordinary_row(), overlay=(session,))
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", lambda: 100.0)

    restart_after_update_when_ready(app, "updated", deferred=False)

    assert app.restart_calls == []
    assert [(delay, callable(callback)) for delay, callback in app.timers] == [
        (1.0, True)
    ]
    assert app.messages == [
        ("updated - restart queued until 1 TUI task finishes.", "information")
    ]

    app._session_overlay.clear()
    app.timers[0][1]()

    assert app.restart_calls == [True]
    assert app.messages[-1] == (
        "updated — restarting ACE to load new code.",
        "information",
    )
    assert app._proc_projection.rows[0].origin == "tool-run"


def test_mixed_kind_wait_copy_joins_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _App(
        _install_row(),
        overlay=(_session_row(),),
        submit_workers={"ph-1": SimpleNamespace(is_finished=False)},
    )
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", lambda: 100.0)

    restart_after_update_when_ready(app, "updated", deferred=False)

    assert app.messages == [
        (
            "updated - restart queued until 1 TUI task, 1 submission, "
            "and 1 installation change finish.",
            "information",
        )
    ]


def test_coalesced_request_with_zero_blockers_restarts_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session_row()
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
    session = _session_row()
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
    session = _session_row()
    app = _App(_ordinary_row(), overlay=(session,))
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
    first_row = _session_row()
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

    app._session_overlay = [_session_row(label="Other", proc_id="other-sync")]
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
    app = _PendingApp(overlay=(_session_row(),))
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", _monotonic(100.0))

    restart_after_update_when_ready(app, "updated", deferred=False, track_pending=False)

    assert app.pending == []
    assert app.timers != []
    assert getattr(app, "_pending_restart_chain", None) is None


def test_second_tracked_request_coalesces_into_one_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _PendingApp(overlay=(_session_row(),))
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


class _WatchingObserver:
    def __init__(self, *watched: str) -> None:
        self._watched = frozenset(watched)

    def is_watching(self, proc_id: str) -> bool:
        return proc_id in self._watched


class _DeliveryApp(_App, ProcCompletionActionsMixin):
    def __init__(
        self,
        *rows: ObservedProc,
        callbacks: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*rows, callbacks=callbacks, **kwargs)
        self._agents_loading = True
        self.hook_calls: list[str] = []

    def _update_proc_indicator(self) -> None:
        return None

    def _reload_and_reposition(self) -> None:
        return None


def _placeholder_row(
    *,
    proc_id: str = "ph-1",
    durable_proc_id: str = "durable-1",
    status: str = "running",
    label: str = "Sync workspace",
) -> ObservedProc:
    return ObservedProc(
        proc_id=proc_id,
        proc_type="sync",
        cl_name="",
        project_file="",
        status=status,
        message="submitting",
        started_at=datetime(2026, 9, 15, 12, 0, 0),
        display_name=label,
        durable_proc_id=durable_proc_id,
        session_id="session-a",
    )


def _synced_completion(proc_id: str) -> ProcCompletionRecord:
    return ProcCompletionRecord(
        proc_id=proc_id,
        operation="patch.sync",
        result=DurableOperationResult(
            operation="patch.sync",
            proc_id=proc_id,
            success=True,
            message="synced",
        ),
    )


@pytest.mark.parametrize("status", ["pending", "running", "settling"])
def test_callback_bearing_durable_row_blocks_restart(status: str) -> None:
    row = _ordinary_row(status=status)
    app = _App(row, callbacks={row.proc_id: object()})

    blockers = collect_restart_blockers(app)

    assert [item.identity for item in blockers] == [row.proc_id]
    assert [item.kind for item in blockers] == ["completion"]
    assert [item.label for item in blockers] == ["Sync workspace"]


def test_handoff_placeholder_and_durable_callback_dedup() -> None:
    placeholder = _placeholder_row()
    durable = _ordinary_row(proc_id="durable-1")
    app = _App(
        placeholder,
        callbacks={"durable-1": object()},
    )

    blockers = collect_restart_blockers(app)

    assert [item.identity for item in blockers] == ["durable-1"]
    assert [item.kind for item in blockers] == ["completion"]

    store_app = _App(durable, callbacks={"durable-1": object()})
    store_blockers = collect_restart_blockers(store_app)
    assert [item.identity for item in store_blockers] == ["durable-1"]
    assert [item.kind for item in store_blockers] == ["completion"]


def test_submit_worker_and_callback_under_placeholder_dedup() -> None:
    placeholder = _placeholder_row()
    app = _App(
        placeholder,
        submit_workers={"ph-1": SimpleNamespace(is_finished=False)},
        callbacks={"ph-1": object()},
    )

    blockers = collect_restart_blockers(app)

    assert [item.identity for item in blockers] == ["ph-1"]
    assert [item.kind for item in blockers] == ["submission"]


def test_unobserved_watched_proc_blocks_and_stale_keys_do_not() -> None:
    watched = _App(
        callbacks={"watched-1": object()},
        observer=_WatchingObserver("watched-1"),
    )
    blockers = collect_restart_blockers(watched)
    assert blockers == (
        RestartBlocker(
            identity="watched-1",
            label="TUI follow-up",
            kind="completion",
        ),
    )

    absent = _App(
        callbacks={"stale-1": object()},
        observer=_WatchingObserver(),
    )
    assert collect_restart_blockers(absent) == ()

    terminal = _App(
        _ordinary_row(status="success"),
        callbacks={"ordinary-work": object()},
        observer=_WatchingObserver("ordinary-work"),
    )
    assert collect_restart_blockers(terminal) == ()


def test_install_row_with_callback_is_reported_as_install() -> None:
    row = _install_row()
    app = _App(row, callbacks={row.proc_id: object()})

    blockers = collect_restart_blockers(app)

    assert [item.identity for item in blockers] == [row.proc_id]
    assert [item.kind for item in blockers] == ["install"]


@pytest.mark.parametrize("session_id", ["session-a", None], ids=["current", "none"])
def test_independent_rows_never_block_even_with_session_id(
    session_id: str | None,
) -> None:
    oneshot = _oneshot_row()
    oneshot.session_id = session_id
    monitor = _monitor_row()
    monitor.session_id = session_id
    daemon = _service_row(service=_daemon_block())
    daemon.session_id = session_id
    app = _App(
        _tool_run_row(session_id=session_id),
        oneshot,
        monitor,
        daemon,
    )

    assert collect_restart_blockers(app) == ()


def test_mixed_work_waits_only_for_callback_sync_then_delivers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync = _ordinary_row(status="running", proc_id="sync-1")
    tool = _tool_run_row()
    app = _DeliveryApp(
        sync,
        tool,
        callbacks={
            "sync-1": ProcCallbackConfig(
                on_complete=lambda _completion: app.hook_calls.append(
                    "reset_dollar_hooks"
                ),
                reload_on_complete=False,
                notify_on_complete=False,
            )
        },
    )
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", lambda: 100.0)

    restart_after_update_when_ready(app, "updated", deferred=False)

    assert app.restart_calls == []
    assert app.messages == [
        ("updated - restart queued until 1 TUI task finishes.", "information")
    ]
    assert app.hook_calls == []

    settled = _ordinary_row(status="success", proc_id="sync-1")
    app._apply_proc_observer_snapshot(
        ProcObserverSnapshot(
            projection=_projection(settled, tool),
            completions=(_synced_completion("sync-1"),),
        )
    )

    assert app.hook_calls == ["reset_dollar_hooks"]
    assert "sync-1" not in app._proc_completion_callbacks
    assert app.restart_calls == []

    app.timers[0][1]()

    assert app.restart_calls == [True]
    assert any(row.origin == "tool-run" for row in app._proc_projection.rows)
    assert app.messages[-1] == (
        "updated — restarting ACE to load new code.",
        "information",
    )


def test_restart_from_own_callback_does_not_wait_on_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _ordinary_row(status="running", proc_id="update-1")
    app = _DeliveryApp(row)
    app._proc_completion_callbacks["update-1"] = ProcCallbackConfig(
        on_complete=lambda _completion: restart_after_update_when_ready(
            app, "updated", deferred=False
        ),
        reload_on_complete=False,
        notify_on_complete=False,
    )
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", lambda: 100.0)

    app._apply_proc_observer_snapshot(
        ProcObserverSnapshot(
            projection=_projection(row),
            completions=(_synced_completion("update-1"),),
        )
    )

    assert "update-1" not in app._proc_completion_callbacks
    assert app.restart_calls == [True]
    assert app.timers == []
    assert not any("restart queued until" in message for message, _ in app.messages)


def test_callback_timeout_warning_names_the_proc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _ordinary_row()
    app = _App(row, callbacks={row.proc_id: object()})
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
        "Sync workspace still active."
    ]
