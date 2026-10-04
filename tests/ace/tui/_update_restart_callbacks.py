"""Completion callback and delivery tests for ACE update restarts."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions._proc_action_completion import ProcCompletionActionsMixin
from sase.ace.tui.actions._proc_action_types import ProcCallbackConfig
from sase.ace.tui.proc_observer import (
    ObservedProc,
    ProcCompletionRecord,
    ProcObserverSnapshot,
    ProcProjection,
    recount_projection,
)
from sase.ace.tui.update_restart import (
    RestartBlocker,
    collect_restart_blockers,
    restart_after_update_when_ready,
)
from sase.ops import DurableOperationResult
from ._update_restart_helpers import (
    App,
    daemon_block,
    install_row,
    monitor_row,
    oneshot_row,
    ordinary_row,
    service_row,
    tool_run_row,
)


def _projection(*rows: ObservedProc) -> ProcProjection:
    return recount_projection(ProcProjection(rows=tuple(rows), session_id="session-a"))


class _WatchingObserver:
    def __init__(self, *watched: str) -> None:
        self._watched = frozenset(watched)

    def is_watching(self, proc_id: str) -> bool:
        return proc_id in self._watched


class _DeliveryApp(App, ProcCompletionActionsMixin):
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
    row = ordinary_row(status=status)
    app = App(row, callbacks={row.proc_id: object()})

    blockers = collect_restart_blockers(app)

    assert [item.identity for item in blockers] == [row.proc_id]
    assert [item.kind for item in blockers] == ["completion"]
    assert [item.label for item in blockers] == ["Sync workspace"]


def test_handoff_placeholder_and_durable_callback_dedup() -> None:
    placeholder = _placeholder_row()
    durable = ordinary_row(proc_id="durable-1")
    app = App(
        placeholder,
        callbacks={"durable-1": object()},
    )

    blockers = collect_restart_blockers(app)

    assert [item.identity for item in blockers] == ["durable-1"]
    assert [item.kind for item in blockers] == ["completion"]

    store_app = App(durable, callbacks={"durable-1": object()})
    store_blockers = collect_restart_blockers(store_app)
    assert [item.identity for item in store_blockers] == ["durable-1"]
    assert [item.kind for item in store_blockers] == ["completion"]


def test_submit_worker_and_callback_under_placeholder_dedup() -> None:
    placeholder = _placeholder_row()
    app = App(
        placeholder,
        submit_workers={"ph-1": SimpleNamespace(is_finished=False)},
        callbacks={"ph-1": object()},
    )

    blockers = collect_restart_blockers(app)

    assert [item.identity for item in blockers] == ["ph-1"]
    assert [item.kind for item in blockers] == ["submission"]


def test_unobserved_watched_proc_blocks_and_stale_keys_do_not() -> None:
    watched = App(
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

    absent = App(
        callbacks={"stale-1": object()},
        observer=_WatchingObserver(),
    )
    assert collect_restart_blockers(absent) == ()

    terminal = App(
        ordinary_row(status="success"),
        callbacks={"ordinary-work": object()},
        observer=_WatchingObserver("ordinary-work"),
    )
    assert collect_restart_blockers(terminal) == ()


def test_install_row_with_callback_is_reported_as_install() -> None:
    row = install_row()
    app = App(row, callbacks={row.proc_id: object()})

    blockers = collect_restart_blockers(app)

    assert [item.identity for item in blockers] == [row.proc_id]
    assert [item.kind for item in blockers] == ["install"]


@pytest.mark.parametrize("session_id", ["session-a", None], ids=["current", "none"])
def test_independent_rows_never_block_even_with_session_id(
    session_id: str | None,
) -> None:
    oneshot = oneshot_row()
    oneshot.session_id = session_id
    monitor = monitor_row()
    monitor.session_id = session_id
    daemon = service_row(service=daemon_block())
    daemon.session_id = session_id
    app = App(
        tool_run_row(session_id=session_id),
        oneshot,
        monitor,
        daemon,
    )

    assert collect_restart_blockers(app) == ()


def test_mixed_work_waits_only_for_callback_sync_then_delivers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync = ordinary_row(status="running", proc_id="sync-1")
    tool = tool_run_row()
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

    settled = ordinary_row(status="success", proc_id="sync-1")
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
    row = ordinary_row(status="running", proc_id="update-1")
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
    row = ordinary_row()
    app = App(row, callbacks={row.proc_id: object()})
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
