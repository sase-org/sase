"""Managed SASE-wide update action tests for the Plugins pane."""

from __future__ import annotations

from datetime import datetime
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace import update_receipt
from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals import plugins_browser_sase_update as pbsu
from sase.ace.tui.modals import plugins_browser_sase_update_procs as pbsup
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.ace.tui.proc_observer import ObservedProc, ProcProjection
from sase.uv_tool.render import UpdateOutcome as SaseUpdateOutcome
from sase.uv_tool.render import UpdateSummary
from sase.uv_tool.runner import ChangeKind
from tests.ace.tui._plugins_browser_pane_helpers import (
    _catalog,
    _not_uv_tool,
    _open_plugins_pane,
    _patch_catalog,
    _patch_catalog_recording,
    _patch_other_panes,
    _render,
    _spy_notify,
)
from tests.ace.tui._plugins_browser_pane_update_helpers import (
    _patch_sase_update_managed_fallback,
)


class _NoopProcObserver:
    def request_poll(self) -> None:
        return None

    def set_detail_proc(self, proc_id: str | None) -> None:
        del proc_id

    def stop(self, *, timeout: float = 1.0) -> None:
        del timeout


def _task(
    proc_id: str,
    proc_type: str,
    status: str = "running",
    *,
    session_id: str | None = None,
    session_live: bool = True,
) -> ObservedProc:
    return ObservedProc(
        proc_id=proc_id,
        proc_type=proc_type,
        cl_name=f"{proc_type}-cl",
        project_file="/tmp/project.sase",
        status=status,
        message=f"{proc_type} task",
        started_at=datetime(2026, 7, 9, 12, 0, 0),
        session_id=session_id,
        session_live=session_live,
    )


def _projection(*procs: ObservedProc) -> ProcProjection:
    rows = tuple(procs)
    projection = ProcProjection(rows=rows, session_id="session-a")
    return ProcProjection(
        rows=rows,
        active_count=len(projection.active_rows()),
        session_id="session-a",
    )


def _set_projection(app: object, *procs: ObservedProc) -> None:
    observer = getattr(app, "_proc_observer", None)
    stop = getattr(observer, "stop", None)
    if callable(stop):
        stop()
    app._proc_observer = _NoopProcObserver()
    app._proc_projection = _projection(*procs)


def test_restart_blockers_include_running_tracked_background_procs() -> None:
    blockers = pbsu._running_background_procs(
        SimpleNamespace(
            _proc_projection=_projection(
                _task("run-sync", "sync"),
                _task("run-mail", "mail"),
                _task("run-launch", "launch"),
                _task("done-sync", "sync", status="success"),
                _task("done-mail", "mail", status="error"),
                _task("done-update", "sase-update", status="success"),
            )
        )
    )

    assert {proc.proc_id for proc in blockers} == {
        "run-sync",
        "run-mail",
        "run-launch",
    }


def test_restart_blockers_include_session_overlay_rows() -> None:
    local = _task("session-sync", "sync")
    app = SimpleNamespace(
        _proc_projection=_projection(_task("done-sync", "sync", status="success")),
        _effective_proc_projection=lambda: _projection(
            _task("done-sync", "sync", status="success"),
            local,
        ),
    )

    blockers = pbsu._running_background_procs(app)

    assert [proc.proc_id for proc in blockers] == ["session-sync"]


def test_restart_blockers_fail_open_without_projection_rows() -> None:
    assert (
        pbsu._running_background_procs(
            SimpleNamespace(_proc_projection=SimpleNamespace(rows=None))
        )
        == []
    )
    assert pbsu._running_background_procs(SimpleNamespace()) == []


def test_restart_blockers_use_active_session_scoped_projection() -> None:
    blockers = pbsu._running_background_procs(
        SimpleNamespace(
            _proc_projection=_projection(
                _task("mine-running", "sync", session_id="session-a"),
                _task(
                    "mine-settling", "mail", status="settling", session_id="session-a"
                ),
                _task(
                    "dead-running",
                    "sync",
                    session_id="dead-session",
                    session_live=False,
                ),
                _task("other-running", "sync", session_id="session-b"),
                _task("unattributed-pending", "sync", status="pending"),
            )
        )
    )

    assert {proc.proc_id for proc in blockers} == {
        "mine-running",
        "mine-settling",
        "unattributed-pending",
    }


def test_restart_after_update_deadline_expires_with_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restart_calls: list[bool] = []
    messages: list[tuple[str, str]] = []
    app = SimpleNamespace(
        _proc_projection=_projection(_task("run-sync", "sync")),
        _restart_tui=lambda *, restart_axe: restart_calls.append(restart_axe),
        notify=lambda message, *, severity="information": messages.append(
            (message, severity)
        ),
    )

    class Host(pbsup.SaseUpdateProcMixin):
        def __init__(self) -> None:
            self.app = app

    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", lambda: 100.0)
    host = Host()
    host._restart_after_update_when_ready(
        "updated",
        deferred=True,
        deadline=99.0,
    )

    assert restart_calls == [True]
    assert any(
        severity == "warning" and "sync" in message for message, severity in messages
    )


async def test_updates_pane_sase_update_opens_preview_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    _patch_sase_update_managed_fallback(monkeypatch)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        assert [v.key for v in modal._variants] == ["update-sase"]
        assert modal._incoming_commits_loader is not None
        preview = _render(modal._preview_renderable())
        assert "uv tool upgrade sase" in preview
        assert "Upgrades sase core + every installed plugin" in preview


async def test_updates_pane_sase_update_loads_receipt_on_plan_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    _patch_sase_update_managed_fallback(monkeypatch)
    action_thread = threading.get_ident()
    receipt_threads: list[int] = []

    def _load_receipt(_install: object | None) -> None:
        receipt_threads.append(threading.get_ident())

    monkeypatch.setattr(pbsu, "load_receipt_for_summary", _load_receipt)

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")

        assert len(receipt_threads) == 1
        assert receipt_threads[0] != action_thread


async def test_updates_pane_sase_update_disabled_when_not_uv_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._uv_tool = _not_uv_tool()
        messages = _spy_notify(monkeypatch, pane)
        pane.action_update_sase()
        await page.pause()
        assert messages and messages[0][1] == "warning"
        assert "uv tool install" in messages[0][0]


async def test_updates_pane_sase_update_confirm_executes_and_refreshes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    _patch_sase_update_managed_fallback(monkeypatch)
    receipt_file = tmp_path / "pending_update_toast.json"
    monkeypatch.setattr(update_receipt, "_PENDING_UPDATE_TOAST_FILE", receipt_file)
    executed: list[object | None] = []

    def _fake_run(install: object | None) -> tuple[UpdateSummary, float]:
        executed.append(install)
        return (
            UpdateSummary(
                outcomes=(
                    SaseUpdateOutcome(
                        name="sase",
                        role="primary",
                        kind=ChangeKind.UPGRADED,
                        old_version="0.5.0",
                        new_version="0.6.0",
                    ),
                )
            ),
            0.2,
        )

    monkeypatch.setattr(pbp, "run_sase_update_summary", _fake_run)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        timer_callbacks: list[Any] = []
        original_set_timer = page.app.set_timer

        def _set_timer(
            delay: float, callback: Any, *args: Any, **kwargs: Any
        ) -> object:
            if delay == 1.0:
                timer_callbacks.append(callback)
                return SimpleNamespace(stop=lambda: None)
            return original_set_timer(delay, callback, *args, **kwargs)

        monkeypatch.setattr(page.app, "set_timer", _set_timer)
        background = _task("sync-feature-a", "sync")
        background.display_name = "sync feature_a"
        _set_projection(page.app, background)
        submitted_workers: list[Any] = []
        original_submit_session_worker = page.app._submit_session_worker

        def _submit_session_worker(*args: Any, **kwargs: Any) -> object | None:
            proc = original_submit_session_worker(*args, **kwargs)
            if proc is not None:
                submitted_workers.append(page.app._session_workers[proc.proc_id])
            return proc

        monkeypatch.setattr(
            page.app,
            "_submit_session_worker",
            _submit_session_worker,
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

        await page.wait_for(lambda _s: bool(submitted_workers), timeout=15.0)
        await submitted_workers[0].wait()
        await page.wait_for(
            lambda _s: bool(executed) and bool(timer_callbacks), timeout=15.0
        )
        assert restart_calls == []
        assert calls  # initial load happened; changed update does not need a reload
        assert any(
            "restart queued until 1 proc finishes" in message
            for message, _severity in messages
        )

        background.status = "success"
        background.message = "sync done"
        background.output = "sync done"
        background.finished_at = datetime(2026, 7, 9, 12, 0, 5)
        timer_callbacks.pop(0)()
        await page.wait_for(lambda _s: bool(restart_calls), timeout=15.0)

        assert restart_calls == [True]
        assert any("restarting ACE" in message for message, _severity in messages)
        assert not any("will be stopped" in message for message, _severity in messages)
        receipt = update_receipt.read_and_clear_pending_update_toast()
        assert receipt is not None
        assert receipt.primary is not None
        assert receipt.primary.old == "0.5.0"
        assert receipt.primary.new == "0.6.0"


async def test_updates_pane_sase_update_noop_closes_without_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    _patch_sase_update_managed_fallback(monkeypatch)
    executed: list[int] = []

    def _fake_run(_install: object | None) -> tuple[UpdateSummary, float]:
        executed.append(1)
        return (UpdateSummary(outcomes=()), 0.1)

    monkeypatch.setattr(pbp, "run_sase_update_summary", _fake_run)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

        # Confirming closes the Admin Center immediately; the no-op proc then
        # completes on the main TUI without a restart.
        await page.wait_for(lambda _s: bool(executed) and bool(messages))
        await page.expect_no_modal()
        assert restart_calls == []
        assert messages == [
            (
                "Nothing to update: sase, core, and plugins are current.",
                "error",
            )
        ]


async def test_updates_pane_sase_update_managed_confirm_closes_admin_center(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    _patch_sase_update_managed_fallback(monkeypatch)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        submitted: list[int] = []
        monkeypatch.setattr(
            pane, "_submit_sase_update_proc", lambda: submitted.append(1)
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

        # The proc is submitted first, then the Admin Center closes immediately.
        await page.wait_for(lambda _s: bool(submitted))
        await page.expect_no_modal()
        assert submitted == [1]


async def test_updates_pane_sase_update_cancel_keeps_admin_center_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    _patch_sase_update_managed_fallback(monkeypatch)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        submitted: list[int] = []
        monkeypatch.setattr(
            pane, "_submit_sase_update_proc", lambda: submitted.append(1)
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_cancel()

        # Cancelling dismisses only the confirm modal; the Admin Center stays.
        await page.expect_modal("ConfigCenterModal")
        assert submitted == []
