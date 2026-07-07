"""SASE-wide update action tests for the Plugins pane."""

from __future__ import annotations

import pytest

from sase.ace import update_receipt
from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.dev_update.models import DevUpdatePlan, DevUpdateResult
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
    _dev_plan,
    _dev_result,
    _editable_catalog,
    _patch_sase_update_managed_fallback,
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
        monkeypatch.setattr(page.app, "_count_running_tasks", lambda: 2)
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

        await page.wait_for(lambda _s: bool(executed) and bool(restart_calls))
        assert restart_calls == [True]
        assert calls  # initial load happened; changed update does not need a reload
        assert any("restarting ACE" in message for message, _severity in messages)
        assert any("2 background tasks" in message for message, _severity in messages)
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

        # Confirming closes the Admin Center immediately; the no-op task then
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


async def test_updates_pane_sase_update_dev_preview_and_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_editable_catalog())
    receipt_file = tmp_path / "pending_update_toast.json"
    monkeypatch.setattr(update_receipt, "_PENDING_UPDATE_TOAST_FILE", receipt_file)
    plan = _dev_plan()
    monkeypatch.setattr(
        pbp,
        "_make_sase_dev_update_preview",
        lambda _receipt: pbp._DevUpdatePreview(plan=plan, subject="sase"),
    )
    executed: list[DevUpdatePlan] = []

    def _fake_execute(plan_arg: DevUpdatePlan) -> DevUpdateResult:
        executed.append(plan_arg)
        return _dev_result(plan_arg)

    monkeypatch.setattr(pbp, "_execute_tui_dev_update", _fake_execute)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
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
        assert modal._incoming_commits_loader is not None
        preview = _render(modal._preview_renderable())
        assert "fetch + fast-forward origin/main" in preview
        assert "Reinstall uv-tool editable Python packages" in preview
        modal.action_confirm()

        await page.wait_for(lambda _s: bool(executed) and bool(restart_calls))
        assert executed == [plan]
        assert restart_calls == [True]
        receipt = update_receipt.read_and_clear_pending_update_toast()
        assert receipt is not None
        assert receipt.plugins
        assert receipt.plugins[0].name == "sase-github"
        assert receipt.plugins[0].old == "0.1.0+1.gabc123def"
        assert receipt.plugins[0].new == "0.1.0+2.gdef456abc"


async def test_updates_pane_sase_update_dev_skipped_reason_is_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_editable_catalog())
    plan = _dev_plan(status="skipped")
    monkeypatch.setattr(
        pbp,
        "_make_sase_dev_update_preview",
        lambda _receipt: pbp._DevUpdatePreview(plan=plan, subject="sase"),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        pane.action_update_sase()

        await page.wait_for(lambda _s: bool(messages))
        assert page.app.screen.__class__.__name__ == "ConfigCenterModal"
        assert messages[0][1] == "error"
        assert "checkout has local changes" in messages[0][0]


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
            pane, "_submit_sase_update_task", lambda: submitted.append(1)
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

        # The task is submitted first, then the Admin Center closes immediately.
        await page.wait_for(lambda _s: bool(submitted))
        await page.expect_no_modal()
        assert submitted == [1]


async def test_updates_pane_sase_update_dev_confirm_closes_admin_center(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_editable_catalog())
    plan = _dev_plan()
    monkeypatch.setattr(
        pbp,
        "_make_sase_dev_update_preview",
        lambda _receipt: pbp._DevUpdatePreview(plan=plan, subject="sase"),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        submitted: list[int] = []
        monkeypatch.setattr(
            pane,
            "_submit_dev_update_task",
            lambda *_a, **_kw: submitted.append(1),
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

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
            pane, "_submit_sase_update_task", lambda: submitted.append(1)
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_cancel()

        # Cancelling dismisses only the confirm modal; the Admin Center stays.
        await page.expect_modal("ConfigCenterModal")
        assert submitted == []
