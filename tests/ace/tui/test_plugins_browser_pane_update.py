"""Selected-plugin update action tests for the Plugins pane."""

from __future__ import annotations

import pytest

from sase.ace import update_receipt
from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.dev_update.models import DevUpdatePlan, DevUpdateResult
from sase.plugins.operations import UpdateOutcome, UpdateUnknown
from sase.uv_tool.runner import ChangeKind, UvChangeSet, UvPackageChange
from tests.ace.tui._plugins_browser_pane_helpers import (
    _catalog,
    _complete_durable_update,
    _highlight,
    _not_uv_tool,
    _open_plugins_pane,
    _patch_catalog,
    _patch_catalog_recording,
    _patch_other_panes,
    _render,
    _spy_notify,
    _update_ready,
)
from tests.ace.tui._plugins_browser_pane_update_helpers import (
    _dev_plan,
    _dev_result,
    _editable_catalog,
)


async def test_plugins_pane_update_opens_preview_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    plan = _update_ready(("github",))
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=plan),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "github")  # installed, update available
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_update()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        # Update offers a single variant; no index/git source toggle.
        assert [v.key for v in modal._variants] == ["update"]
        assert modal._incoming_commits_loader is not None
        preview = _render(modal._preview_renderable())
        assert "--upgrade-package" in preview
        assert "Upgrades sase-github" in preview
        assert "sase core stays pinned" in preview


async def test_plugins_pane_update_hint_gated_on_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        # Comprehensive update is always offered; selected plugin update is
        # offered only when the highlighted plugin has an available update.
        _highlight(pane, "github")
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        assert "u update" in pane._hints()
        assert "U upd ↑" in pane._hints()
        assert "U all" not in pane._hints()
        assert "S sase" not in pane._hints()
        # Installed but current: no selected-plugin update hint.
        _highlight(pane, "telegram")
        await page.wait_for(lambda _s: pane._highlighted_name() == "telegram")
        telegram_hints = pane._hints()
        assert "u update" in telegram_hints
        assert "U upd" not in telegram_hints
        assert "↑" not in telegram_hints
        # Not installed: comprehensive update remains, selected-plugin update is hidden.
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        assert "u update" in pane._hints()
        assert "U upd" not in pane._hints()


async def test_plugins_pane_update_not_installed_noops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    planned: list[int] = []
    monkeypatch.setattr(pbp, "_plan_update_preview", lambda *a, **k: planned.append(1))
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "nvim")  # not installed
        pane.action_update()
        await page.pause()
        assert not planned
        assert pane._update_plan_worker is None
        assert messages == []


async def test_plugins_pane_update_current_plugin_noops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    planned: list[int] = []
    monkeypatch.setattr(pbp, "_plan_update_preview", lambda *a, **k: planned.append(1))
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "telegram")  # installed but already current
        pane.action_update()
        await page.pause()
        assert not planned
        assert pane._update_plan_worker is None
        assert messages == []


async def test_plugins_pane_update_disabled_when_not_uv_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog(), uv_tool=_not_uv_tool())
    planned: list[int] = []
    monkeypatch.setattr(pbp, "_plan_update_preview", lambda *a, **k: planned.append(1))
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "github")  # installed + update available
        pane.action_update()
        await page.pause()
        assert pane._update_plan_worker is None
        assert not planned
        assert messages and messages[0][1] == "warning"
        assert "uv tool install" in messages[0][0]
        # Update affordances are dropped from the hints.
        assert "u update" not in pane._hints()
        assert "U upd" not in pane._hints()
        assert not planned


async def test_plugins_pane_update_unknown_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    preview = pbp._UpdatePreview(plan=UpdateUnknown(query="github", suggestions=()))
    monkeypatch.setattr(pbp, "_plan_update_preview", lambda *a, **k: preview)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "github")  # installed -> proceeds to plan
        pane.action_update()
        await page.wait_for(lambda _s: bool(messages))
        message, severity = messages[0]
        assert "No plugin named 'github'" in message
        assert severity == "error"


async def test_plugins_pane_update_confirm_executes_and_writes_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    receipt_file = tmp_path / "pending_update_toast.json"
    monkeypatch.setattr(update_receipt, "_PENDING_UPDATE_TOAST_FILE", receipt_file)
    plan = _update_ready(("github",))
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=plan),
    )
    outcome = UpdateOutcome(
        plan=plan,
        change_set=UvChangeSet(
            changes=(
                UvPackageChange(
                    name="sase-github",
                    kind=ChangeKind.UPGRADED,
                    old_version="1.2.0",
                    new_version="1.3.0",
                ),
            )
        ),
        elapsed=1.0,
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        submissions = _complete_durable_update(
            monkeypatch,
            page.app,
            outcome=outcome,
            message="Updated 1 plugin in 1s",
        )
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        _highlight(pane, "github")
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_update()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()
        await page.wait_for(lambda _s: bool(restart_calls))
        [(args, kwargs)] = submissions
        assert args == (["sase", "plugin", "update", "sase-github", "--json"],)
        assert kwargs["request"] == {"plugin": "sase-github"}
        assert restart_calls == [True]
        assert calls  # initial load happened
        receipt = update_receipt.read_and_clear_pending_update_toast()
        assert receipt is not None
        assert receipt.primary is None
        assert receipt.plugins
        assert receipt.plugins[0].name == "sase-github"
        assert receipt.plugins[0].old == "1.2.0"
        assert receipt.plugins[0].new == "1.3.0"


async def test_plugins_pane_editable_update_uses_dev_preview_and_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_editable_catalog())
    plan = _dev_plan()
    monkeypatch.setattr(
        pbp,
        "_make_plugin_dev_update_preview",
        lambda query, *, all_plugins, receipt: pbp._DevUpdatePreview(
            plan=plan,
            subject=str(query),
        ),
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
        _highlight(pane, "github")
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        assert "v0.1.0+1.gabc123def → v0.1.0+2.gdef456abc  dev" in (
            pane._row_text(pane._highlighted_row()).plain  # type: ignore[union-attr]
        )
        pane.action_update()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        assert modal._incoming_commits_loader is not None
        preview = _render(modal._preview_renderable())
        assert "$ sase update" in preview
        assert "fetch + fast-forward origin/main" in preview
        modal.action_confirm()

        await page.wait_for(lambda _s: bool(executed) and bool(restart_calls))
        assert executed == [plan]
        assert restart_calls == [True]


async def test_plugins_pane_editable_update_skipped_reason_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_editable_catalog())
    plan = _dev_plan(status="skipped")
    monkeypatch.setattr(
        pbp,
        "_make_plugin_dev_update_preview",
        lambda query, *, all_plugins, receipt: pbp._DevUpdatePreview(
            plan=plan,
            subject=str(query),
        ),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "github")
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_update()

        await page.wait_for(lambda _s: bool(messages))
        assert messages[0][1] == "warning"
        assert "checkout has local changes" in messages[0][0]
