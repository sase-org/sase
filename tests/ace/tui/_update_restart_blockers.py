"""Blocker classification tests for ACE update restarts."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from sase.ace.tui._proc_observer_models import is_install_mutation_row
from sase.ace.tui.proc_observer import ObservedProc, store_proc_row
from sase.ace.tui.update_restart import (
    RestartBlocker,
    collect_restart_blockers,
    restart_after_update_when_ready,
    running_background_procs,
)
from sase.monitor_state import MONITOR_PROC_ORIGIN
from sase.procs import Proc, TUI_PROC_KIND
from sase.procs.service_meta import (
    SERVICE_HOST_ORIGIN,
    SERVICE_ONESHOT_ORIGIN,
    ProcServiceBlock,
)
from ._update_restart_helpers import (
    App,
    daemon_block,
    install_row,
    monitor_row,
    oneshot_row,
    ordinary_row,
    service_row,
    session_row,
    tool_run_row,
)

_STARTED_AT = "2026-09-14T20:30:30.456885Z"
_RECEIVER_LABEL = "Telegram inbound long-poll receiver"
_TELEGRAM_RECEIVER_ORIGIN = "telegram-receiver"


def _blocker_ids(app: App) -> list[str]:
    return [item.identity for item in collect_restart_blockers(app)]


def _blocker_kinds(app: App) -> list[str]:
    return [item.kind for item in collect_restart_blockers(app)]


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


@pytest.mark.parametrize("status", ["pending", "running", "settling"])
@pytest.mark.parametrize(
    "session_id", ["session-a", None], ids=["current", "unattributed"]
)
def test_tool_run_rows_do_not_block_restart(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    session_id: str | None,
) -> None:
    app = App(tool_run_row(status=status, session_id=session_id))
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
    app = App(
        tool_run_row(
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
    app = App(
        ordinary_row(),
        _receiver_row(),
        oneshot_row(),
        monitor_row(),
        service_row(service=daemon_block()),
        service_row(proc_id="bgcmd-2", origin=SERVICE_ONESHOT_ORIGIN),
        ordinary_row(proc_id="other-tui", session_id="session-b"),
    )

    assert collect_restart_blockers(app) == ()
    assert running_background_procs(app) == []


def test_visibility_cannot_control_restart_safety() -> None:
    receiver = _receiver_row()
    monitor = monitor_row()
    app = App(receiver, monitor)
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
    app = App(
        service_row(
            proc_id="service-gateway", service=daemon_block() if marked else None
        ),
        service_row(
            proc_id="service-scheduler",
            service=daemon_block("scheduler") if marked else None,
        ),
        monitor_row(),
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
    finished = session_row(status="success")
    app = App(overlay=(finished,))

    blockers = collect_restart_blockers(app)

    assert [item.identity for item in blockers] == [finished.proc_id]
    assert [item.kind for item in blockers] == ["session_worker"]
    assert [item.label for item in blockers] == ["local sync"]


def test_leftover_session_worker_key_blocks_without_overlay() -> None:
    app = App(session_workers={"orphan-worker": SimpleNamespace()})

    blockers = collect_restart_blockers(app)

    assert blockers == (
        RestartBlocker(
            identity="orphan-worker",
            label="TUI task",
            kind="session_worker",
        ),
    )


def test_finished_submit_worker_still_blocks_until_map_pops() -> None:
    app = App(submit_workers={"ph-1": SimpleNamespace(is_finished=True)})

    blockers = collect_restart_blockers(app)

    assert blockers == (
        RestartBlocker(
            identity="ph-1",
            label="durable submission",
            kind="submission",
        ),
    )


def test_submission_placeholder_and_durable_install_dedup() -> None:
    durable = install_row(proc_id="plugin-install-1")
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
    app = App(
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
    other_session = install_row(
        proc_id="other-install",
        proc_type=proc_type,
        scopes=scopes,
        session_id="dead-session",
    )
    app = App(other_session)

    blockers = collect_restart_blockers(app)

    assert [item.identity for item in blockers] == ["other-install"]
    assert [item.kind for item in blockers] == ["install"]
    assert is_install_mutation_row(other_session) is True


def test_plugin_install_is_not_an_update_lane_row() -> None:
    from sase.ace.tui._proc_observer_models import is_update_row

    row = install_row()
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
    daemon = service_row(service=daemon_block())
    daemon.proc_type = "sase-update"
    daemon.exclusive_scopes = frozenset({"sase-update"})

    assert is_install_mutation_row(monitor) is False
    assert is_install_mutation_row(daemon) is False
    assert collect_restart_blockers(App(monitor, daemon)) == ()


def test_local_legacy_tui_blocks_and_other_tui_does_not() -> None:
    local = _legacy_tui_row(proc_id="local-tui", session_id="session-a")
    unattributed = _legacy_tui_row(proc_id="unattributed-tui", session_id=None)
    other = _legacy_tui_row(proc_id="other-tui", session_id="session-b")
    app = App(local, unattributed, other)

    assert _blocker_ids(app) == ["local-tui", "unattributed-tui"]
    assert _blocker_kinds(app) == ["legacy_tui", "legacy_tui"]


def test_mixed_independent_work_waits_only_for_local_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = session_row()
    app = App(tool_run_row(), ordinary_row(), overlay=(session,))
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
    app = App(
        install_row(),
        overlay=(session_row(),),
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
