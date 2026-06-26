"""Update action tests for the Plugins pane."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.plugins.operations import NoPlugins, UpdateOutcome, UpdateReady, UpdateUnknown
from sase.uv_tool.render import UpdateOutcome as SaseUpdateOutcome
from sase.uv_tool.render import UpdateSummary
from sase.uv_tool.runner import ChangeKind, UvChangeSet, UvPackageChange
from tests.ace.tui._plugins_browser_pane_helpers import (
    _catalog,
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


async def test_updates_pane_sase_update_opens_preview_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        assert [v.key for v in modal._variants] == ["update-sase"]
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
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
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
        initial = len(calls)
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

        await page.wait_for(lambda _s: bool(executed) and len(calls) > initial)
        assert pane._sase_update_restart_hint is True
        assert any("Updated sase" in message for message, _severity in messages)


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
        # Installed + update available: emphasized hint, plus update-all.
        _highlight(pane, "github")
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        assert "u update ↑" in pane._hints()
        assert "U update-all" in pane._hints()
        # Installed but current: hint present, not emphasized.
        _highlight(pane, "telegram")
        await page.wait_for(lambda _s: pane._highlighted_name() == "telegram")
        telegram_hints = pane._hints()
        assert "u update" in telegram_hints
        assert "↑" not in telegram_hints
        # Not installed: no single-update hint (install is offered instead).
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        assert "u update" not in pane._hints()


async def test_plugins_pane_update_not_installed_toasts(
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
        assert not planned  # short-circuited before planning
        assert messages and "not installed" in messages[0][0]
        assert messages[0][1] == "warning"


async def test_plugins_pane_update_disabled_when_not_uv_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    planned: list[int] = []
    monkeypatch.setattr(pbp, "_plan_update_preview", lambda *a, **k: planned.append(1))
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._uv_tool = _not_uv_tool()
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
        assert "U update-all" not in pane._hints()
        # Update-all is gated too.
        pane.action_update_all()
        await page.pause()
        assert not planned


async def test_plugins_pane_update_all_no_plugins_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=NoPlugins()),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        pane.action_update_all()
        await page.wait_for(lambda _s: bool(messages))
        assert "No plugins are installed" in messages[0][0]


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


async def test_plugins_pane_update_confirm_executes_and_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    plan = _update_ready(("github",))
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=plan),
    )
    executed: list[UpdateReady] = []

    def _fake_execute(plan_arg: UpdateReady, **_kw: object) -> UpdateOutcome:
        executed.append(plan_arg)
        return UpdateOutcome(
            plan=plan_arg,
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

    monkeypatch.setattr(pbp, "execute_update", _fake_execute)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        initial = len(calls)
        _highlight(pane, "github")
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_update()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()
        # The tracked task runs execute_update, then refreshes the catalog.
        await page.wait_for(lambda _s: bool(executed) and len(calls) > initial)
        assert executed[0].targets == ("sase-github",)
        assert not executed[0].all_plugins


async def test_plugins_pane_update_all_executes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    plan = _update_ready(("github", "telegram"), all_plugins=True)
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=plan),
    )
    executed: list[UpdateReady] = []

    def _fake_execute(plan_arg: UpdateReady, **_kw: object) -> UpdateOutcome:
        executed.append(plan_arg)
        return UpdateOutcome(plan=plan_arg, change_set=UvChangeSet(), elapsed=0.3)

    monkeypatch.setattr(pbp, "execute_update", _fake_execute)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_update_all()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        # A single variant; the preview names every installed plugin.
        assert [v.key for v in modal._variants] == ["update"]
        preview = _render(modal._preview_renderable())
        assert "every installed plugin" in preview
        modal.action_confirm()
        await page.wait_for(lambda _s: bool(executed))
        assert executed[0].all_plugins
