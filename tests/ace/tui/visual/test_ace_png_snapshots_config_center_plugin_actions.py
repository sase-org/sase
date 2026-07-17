"""ACE TUI PNG visual snapshots for Config Center plugin action previews."""

from __future__ import annotations

import pytest
from textual.containers import VerticalScroll

from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.updates.incoming_commits import (
    CommitSummary,
    IncomingCommits,
    RepoIncomingCommits,
)
from tests.ace.tui.test_plugins_browser_pane import (
    _highlight,
    _not_uv_tool,
    _ready_preview,
    _uninstall_ready,
    _update_ready,
)
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    _build_view,
    _config_layers,
    _config_schema,
    _open_plugins_modal,
    _patch_config_view,
    _patch_plugins_catalog,
    _patch_xprompt_sources,
    _wait_for_plugins_detail,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_config_center_plugins_install_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The install confirm-preview modal: exact uv argv + source toggle."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)
    monkeypatch.setattr(
        pbp, "_plan_install_preview", lambda name, *, offline: _ready_preview(name)
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        _highlight(pane, "nvim")  # a not-installed plugin
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        # Wait for the debounced detail repaint to actually land on nvim so the
        # panel behind the modal is deterministic (not the default github row).
        await page.wait_for(lambda _s: pane._detail_name == "nvim")
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_install_preview_120x40",
            title="ACE SASE Admin Center — Plugins install (confirm preview)",
        )


async def test_config_center_plugins_marked_install_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Updates tab with a marked install row and marked-count hints."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        pane.action_toggle_install_mark()
        await page.wait_for(lambda _s: pane._marked_install == {"nvim"})
        # Toggling a mark advances the highlight to the next installable row.
        await page.wait_for(lambda _s: pane._detail_name == "acme")
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_marked_install_120x40",
            title="ACE SASE Admin Center — Updates tab (marked install)",
        )


async def test_config_center_plugins_not_uv_tool_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-uv-tool install surfaces the unavailable banner; no ``i install``."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch, uv_tool=_not_uv_tool())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        await page.wait_for(lambda _s: pane._detail_name == "github")
        await _wait_for_plugins_detail(page, pane)
        await page.wait_for(
            lambda _s: (
                bool(pane._incoming_commit_cache) and not pane._incoming_commit_loading
            )
        )

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_not_uv_tool_120x40",
            title="ACE SASE Admin Center — Updates tab (install unavailable)",
        )


async def test_config_center_plugins_update_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The single-plugin update confirm-preview modal: exact uv upgrade argv."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)
    plan = _update_ready(("github",))
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=plan),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        _highlight(pane, "github")  # installed + update available
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_update()
        await page.expect_modal("PluginActionConfirmModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_update_preview_120x40",
            title="ACE SASE Admin Center — Plugins update (confirm preview)",
        )


async def test_config_center_plugins_long_update_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A compact update preview contains its scrollable incoming commits."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)
    plan = _update_ready(("github",))
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=plan),
    )
    long_group = RepoIncomingCommits(
        "github",
        IncomingCommits(
            total=40,
            commits=tuple(
                CommitSummary(f"{index:07x}", f"Plugin update change {index}")
                for index in range(40)
            ),
            source="git",
        ),
    )
    monkeypatch.setattr(
        pbp,
        "_fetch_incoming_commit_groups",
        lambda *_args, **_kwargs: (long_group,),
    )

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(100, 24)
    ) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        _highlight(pane, "github")
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_update()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        scroll = modal.query_one("#plugin-action-commits", VerticalScroll)
        await page.wait_for(lambda _s: int(scroll.max_scroll_y) > 0)
        await page.wait_for(lambda _s: scroll.border_subtitle == "ctrl+d/u scroll")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_long_update_preview_100x24",
            title="ACE SASE Admin Center — Plugins update (long compact preview)",
        )


async def test_config_center_plugins_uninstall_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The uninstall confirm-preview modal: exact uv re-install (minus target)."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)
    plan = _uninstall_ready("github")
    monkeypatch.setattr(
        pbp,
        "_plan_uninstall_preview",
        lambda query, *, offline: pbp._UninstallPreview(plan=plan),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        _highlight(pane, "github")  # installed
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_uninstall()
        await page.expect_modal("PluginActionConfirmModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_uninstall_preview_120x40",
            title="ACE SASE Admin Center — Plugins uninstall (confirm preview)",
        )
