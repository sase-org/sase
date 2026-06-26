"""Install action tests for the Plugins pane and action confirm modal."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionVariant,
)
from sase.plugins.operations import InstallNotFound, InstallOutcome, InstallReady
from sase.uv_tool.runner import ChangeKind, UvChangeSet, UvPackageChange
from tests.ace.tui._plugins_browser_pane_helpers import (
    _catalog,
    _highlight,
    _not_uv_tool,
    _open_plugins_pane,
    _patch_catalog,
    _patch_catalog_recording,
    _patch_other_panes,
    _ready_preview,
    _render,
    _spy_notify,
)


async def test_plugins_pane_install_opens_preview_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    monkeypatch.setattr(
        pbp, "_plan_install_preview", lambda name, *, offline: _ready_preview(name)
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        # Both source variants are offered; index is the default (first).
        assert [v.key for v in modal._variants] == ["index", "git"]
        preview = _render(modal._preview_renderable())
        assert "uv tool install" in preview
        assert "Installs nvim" in preview
        assert "from index" in preview


async def test_plugins_pane_install_hint_only_for_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        assert "i install" in pane._hints()
        _highlight(pane, "github")  # already installed
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        assert "i install" not in pane._hints()


async def test_plugins_pane_install_already_installed_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    planned: list[int] = []
    monkeypatch.setattr(pbp, "_plan_install_preview", lambda *a, **k: planned.append(1))
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "github")  # installed
        pane.action_install()
        await page.pause()
        assert not planned  # short-circuited before planning
        assert messages and "already installed" in messages[0][0]


async def test_plugins_pane_install_disabled_when_not_uv_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    planned: list[int] = []
    monkeypatch.setattr(pbp, "_plan_install_preview", lambda *a, **k: planned.append(1))
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._uv_tool = _not_uv_tool()
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "nvim")
        pane.action_install()
        await page.pause()
        assert pane._plan_worker is None
        assert not planned
        assert messages and messages[0][1] == "warning"
        assert "uv tool install" in messages[0][0]
        # Affordances surface the disabled state.
        assert "i install" not in pane._hints()
        assert "unavailable" in pane._summary_text().plain


async def test_plugins_pane_install_not_found_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    preview = pbp._InstallPreview(
        index_plan=InstallNotFound(query="nvim", suggestions=())
    )
    monkeypatch.setattr(pbp, "_plan_install_preview", lambda name, *, offline: preview)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "nvim")
        pane.action_install()
        await page.wait_for(lambda _s: bool(messages))
        message, severity = messages[0]
        assert "No plugin named 'nvim'" in message
        assert severity == "error"


async def test_plugins_pane_install_confirm_executes_and_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    monkeypatch.setattr(
        pbp, "_plan_install_preview", lambda name, *, offline: _ready_preview(name)
    )
    executed: list[InstallReady] = []

    def _fake_execute(plan: InstallReady, **_kw: object) -> InstallOutcome:
        executed.append(plan)
        return InstallOutcome(
            plan=plan,
            change_set=UvChangeSet(
                changes=(
                    UvPackageChange(
                        name="sase-nvim", kind=ChangeKind.ADDED, new_version="2.0.0"
                    ),
                )
            ),
            groups=(),
            elapsed=1.5,
        )

    monkeypatch.setattr(pbp, "execute_install", _fake_execute)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        initial = len(calls)
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()  # accept the default index variant
        # The tracked task runs execute_install, then refreshes the catalog.
        await page.wait_for(lambda _s: bool(executed) and len(calls) > initial)
        assert executed[0].spec.display_name == "nvim"
        assert executed[0].spec.source == "catalog"


async def test_plugins_pane_install_git_variant_executed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    monkeypatch.setattr(
        pbp, "_plan_install_preview", lambda name, *, offline: _ready_preview(name)
    )
    executed: list[InstallReady] = []

    def _fake_execute(plan: InstallReady, **_kw: object) -> InstallOutcome:
        executed.append(plan)
        return InstallOutcome(
            plan=plan, change_set=UvChangeSet(), groups=(), elapsed=0.2
        )

    monkeypatch.setattr(pbp, "execute_install", _fake_execute)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_toggle_source()  # index -> git
        modal.action_confirm()
        await page.wait_for(lambda _s: bool(executed))
        assert executed[0].spec.source == "git"


async def test_plugin_action_modal_toggle_and_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    variants = [
        PluginActionVariant(
            key="index",
            label="from index",
            argv=("uv", "tool", "install", "sase-nvim"),
            summary="Installs nvim  (from catalog)",
        ),
        PluginActionVariant(
            key="git",
            label="from git",
            argv=("uv", "tool", "install", "git+https://example/sase-nvim"),
            summary="Installs nvim  (from git)",
        ),
    ]
    async with AcePage() as page:
        results: list[PluginActionConfirmResult | None] = []
        modal = PluginActionConfirmModal(
            title="Install nvim", intro="Confirm", variants=variants
        )
        page.app.push_screen(modal, results.append)
        await page.expect_modal("PluginActionConfirmModal")
        assert modal._index == 0
        modal.action_toggle_source()
        assert modal._index == 1
        modal.action_confirm()
        await page.wait_for(lambda _s: bool(results))
        assert results[0] == PluginActionConfirmResult("git")


async def test_plugin_action_modal_cancel_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    variants = [
        PluginActionVariant(
            key="update",
            label="update",
            argv=("uv", "tool", "install", "sase-nvim"),
            summary="Upgrades nvim",
        )
    ]
    async with AcePage() as page:
        results: list[PluginActionConfirmResult | None] = []
        modal = PluginActionConfirmModal(
            title="Update nvim", intro="Confirm", variants=variants
        )
        page.app.push_screen(modal, results.append)
        await page.expect_modal("PluginActionConfirmModal")
        # A single variant offers no source toggle.
        assert len(modal._variants) == 1
        modal.action_cancel()
        await page.wait_for(lambda _s: bool(results))
        assert results[0] is None
