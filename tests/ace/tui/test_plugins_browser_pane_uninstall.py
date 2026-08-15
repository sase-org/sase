"""Uninstall action tests for the Plugins pane."""

from __future__ import annotations

import pytest

from sase.ace import update_receipt
from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.plugins.operations import (
    AlreadyAbsent,
    UninstallOutcome,
    UninstallUnknown,
)
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
    _uninstall_ready,
)


async def test_plugins_pane_uninstall_opens_preview_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    plan = _uninstall_ready("github")
    monkeypatch.setattr(
        pbp,
        "_plan_uninstall_preview",
        lambda query, *, offline: pbp._UninstallPreview(plan=plan),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "github")  # installed
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_uninstall()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        # Uninstall offers a single variant; no source toggle.
        assert [v.key for v in modal._variants] == ["uninstall"]
        preview = _render(modal._preview_renderable())
        assert "uv tool install" in preview
        assert "Removes github" in preview
        assert "other plugins stay installed" in preview


async def test_plugins_pane_uninstall_hint_gated_on_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        # Installed: uninstall offered.
        _highlight(pane, "github")
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        assert "x rm" in pane._hints()
        _highlight(pane, "telegram")
        await page.wait_for(lambda _s: pane._highlighted_name() == "telegram")
        assert "x rm" in pane._hints()
        # Not installed: no uninstall hint (install is offered instead).
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        assert "x rm" not in pane._hints()


async def test_plugins_pane_uninstall_not_installed_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    planned: list[int] = []
    monkeypatch.setattr(
        pbp, "_plan_uninstall_preview", lambda *a, **k: planned.append(1)
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "nvim")  # not installed
        pane.action_uninstall()
        await page.pause()
        assert not planned  # short-circuited before planning
        assert messages and "not installed" in messages[0][0]
        assert messages[0][1] == "warning"


async def test_plugins_pane_uninstall_disabled_when_not_uv_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    planned: list[int] = []
    monkeypatch.setattr(
        pbp, "_plan_uninstall_preview", lambda *a, **k: planned.append(1)
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._uv_tool = _not_uv_tool()
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "github")  # installed
        pane.action_uninstall()
        await page.pause()
        assert pane._uninstall_plan_worker is None
        assert not planned
        assert messages and messages[0][1] == "warning"
        assert "uv tool install" in messages[0][0]
        # Uninstall affordance is dropped from the hints.
        assert "x rm" not in pane._hints()
        # The summary banner reports the broader unavailable state.
        assert "unavailable" in pane._summary_text().plain


async def test_plugins_pane_uninstall_already_absent_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    preview = pbp._UninstallPreview(plan=AlreadyAbsent(name="github"))
    monkeypatch.setattr(pbp, "_plan_uninstall_preview", lambda *a, **k: preview)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "github")  # installed -> proceeds to plan
        pane.action_uninstall()
        await page.wait_for(lambda _s: bool(messages))
        message, severity = messages[0]
        assert "github is not installed" in message
        assert "nothing to uninstall" in message
        assert severity == "information"


async def test_plugins_pane_uninstall_unknown_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    preview = pbp._UninstallPreview(
        plan=UninstallUnknown(query="github", suggestions=())
    )
    monkeypatch.setattr(pbp, "_plan_uninstall_preview", lambda *a, **k: preview)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "github")  # installed -> proceeds to plan
        pane.action_uninstall()
        await page.wait_for(lambda _s: bool(messages))
        message, severity = messages[0]
        assert "No plugin named 'github'" in message
        assert severity == "error"


async def test_plugins_pane_uninstall_confirm_executes_and_restarts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    receipt_file = tmp_path / "pending_update_toast.json"
    monkeypatch.setattr(update_receipt, "_PENDING_UPDATE_TOAST_FILE", receipt_file)
    plan = _uninstall_ready("github")
    monkeypatch.setattr(
        pbp,
        "_plan_uninstall_preview",
        lambda query, *, offline: pbp._UninstallPreview(plan=plan),
    )
    outcome = UninstallOutcome(
        plan=plan,
        change_set=UvChangeSet(
            changes=(
                UvPackageChange(
                    name="sase-github",
                    kind=ChangeKind.REMOVED,
                    old_version="1.2.0",
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
            message="Uninstalled github in 1s",
        )
        initial = len(calls)
        messages = _spy_notify(monkeypatch, pane)
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        _highlight(pane, "github")
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_uninstall()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()
        await page.wait_for(lambda _s: bool(restart_calls))
        [(args, kwargs)] = submissions
        assert args == (["sase", "plugin", "uninstall", "github", "--json"],)
        assert kwargs["request"] == {"plugin": "github"}
        assert restart_calls == [True]
        assert len(calls) == initial
        assert any("restarting ACE" in message for message, _severity in messages)
        receipt = update_receipt.read_and_clear_pending_update_toast()
        assert receipt is not None
        assert receipt.plugins
        assert receipt.plugins[0].name == "sase-github"
        assert receipt.plugins[0].old == "1.2.0"
        assert receipt.plugins[0].new is None


async def test_plugins_pane_uninstall_no_change_refreshes_without_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    plan = _uninstall_ready("github")
    monkeypatch.setattr(
        pbp,
        "_plan_uninstall_preview",
        lambda query, *, offline: pbp._UninstallPreview(plan=plan),
    )
    outcome = UninstallOutcome(
        plan=plan,
        change_set=UvChangeSet(),
        elapsed=0.1,
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _complete_durable_update(
            monkeypatch,
            page.app,
            outcome=outcome,
            message="Plugins already up to date.",
        )
        initial = len(calls)
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        _highlight(pane, "github")
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_uninstall()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

        await page.wait_for(lambda _s: len(calls) > initial)
        assert restart_calls == []
