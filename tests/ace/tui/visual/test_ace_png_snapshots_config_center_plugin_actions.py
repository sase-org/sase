"""ACE TUI PNG visual snapshots for Config Center plugin action previews."""

from __future__ import annotations

import os

import pytest
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionPreviewComponent,
    PluginActionPreviewSection,
    PluginActionVariant,
)
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
from tests.ace.tui._plugins_browser_pane_helpers import _render
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
    patches,
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

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_plugins_modal(page)
        _highlight(pane, "nvim")  # a not-installed plugin
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        # Wait for the debounced detail repaint to actually land on nvim so the
        # panel behind the modal is deterministic (not the default github row).
        await page.wait_for(lambda _s: pane._detail_key == "plugin:nvim")
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

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_plugins_modal(page)
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        pane.action_toggle_install_mark()
        await page.wait_for(lambda _s: pane._marked_install == {"nvim"})
        # Toggling a mark advances the highlight to the next installable row.
        await page.wait_for(lambda _s: pane._detail_key == "plugin:acme")
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

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_plugins_modal(page)
        await page.wait_for(lambda _s: pane._detail_key == "plugin:github")
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

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
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

    async with AcePage(query='"visual"', patches=patches(), size=(100, 24)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_plugins_modal(page)
        _highlight(pane, "github")
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_update()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        await page.wait_for(lambda _s: len(modal.query("#plugin-action-commits")) > 0)
        await page.wait_for(
            lambda _s: len(modal.query("#plugin-action-commits-body")) > 0
        )
        await page.wait_for(
            lambda _s: (
                "github — 40 incoming commits"
                in _render(
                    modal.query_one("#plugin-action-commits-body", Static).content
                )
            )
        )
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

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
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


async def test_config_center_comprehensive_update_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wide comprehensive preview leads with grouped incoming commits."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)
    user_home = os.environ.get("HOME", "/home/visual")
    incoming_groups = (
        RepoIncomingCommits(
            "sase",
            IncomingCommits(
                total=4,
                commits=(
                    CommitSummary("aa10001", "Keep captured update plans immutable"),
                    CommitSummary("aa10000", "Add comprehensive update receipts"),
                    CommitSummary("aa0ffff", "Coalesce update status refreshes"),
                    CommitSummary("aa0fffe", "Harden editable checkout planning"),
                ),
                source="git",
            ),
        ),
        RepoIncomingCommits(
            "sase-core",
            IncomingCommits(
                total=2,
                commits=(
                    CommitSummary("bb20001", "Expose grouped update candidates"),
                    CommitSummary("bb20000", "Preserve repository range order"),
                ),
                source="git",
            ),
        ),
    )

    async with AcePage(query='"visual"', patches=patches(), size=(120, 32)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await _open_plugins_modal(page)
        modal = PluginActionConfirmModal(
            title="Comprehensive update",
            intro="Confirm the snapshot-gated SASE and provider work below.",
            variants=(
                PluginActionVariant(
                    key="comprehensive-update",
                    label="comprehensive update",
                    argv=(),
                    summary="Runs one tracked comprehensive update.",
                    sections=(
                        PluginActionPreviewSection(
                            title="SASE, core & plugins",
                            summary="Updates editable checkouts, then reconciles packages.",
                            components=(
                                PluginActionPreviewComponent(
                                    "sase", "origin/main · 8 incoming commits", "update"
                                ),
                                PluginActionPreviewComponent(
                                    "sase-core",
                                    "origin/main · 4 incoming commits",
                                    "update",
                                ),
                                PluginActionPreviewComponent(
                                    "sase", "0.7.1 → 0.7.2", "update"
                                ),
                                PluginActionPreviewComponent(
                                    "sase-core", "0.5.0 → 0.5.1", "update"
                                ),
                                PluginActionPreviewComponent(
                                    "bugyi-chops", "0.12.0 → latest", "update"
                                ),
                                PluginActionPreviewComponent(
                                    "sase-github", "already current", "current"
                                ),
                                PluginActionPreviewComponent(
                                    "sase-telegram", "already current", "current"
                                ),
                                PluginActionPreviewComponent(
                                    "sase-nvim",
                                    "checkout has local changes",
                                    "skipped",
                                ),
                            ),
                            commands=(
                                f"git -C {user_home}/projects/sase fetch origin main",
                                f"git -C {user_home}/projects/sase merge --ff-only origin/main",
                                f"git -C {user_home}/projects/sase-core fetch origin main",
                                f"git -C {user_home}/projects/sase-core merge --ff-only origin/main",
                                f"uv tool install --editable {user_home}/projects/sase --upgrade-package bugyi-chops",
                                f"fallback: uv tool install --force {user_home}/projects/sase",
                            ),
                            counts=("2 checkouts", "4 steps", "1 skipped"),
                        ),
                        PluginActionPreviewSection(
                            title="Agent CLIs",
                            components=(
                                PluginActionPreviewComponent(
                                    "Claude Code", "1.0.0 → 1.1.0", "update"
                                ),
                                PluginActionPreviewComponent(
                                    "Codex CLI", "Homebrew update is manual", "skipped"
                                ),
                            ),
                            commands=(
                                f"Claude Code: {user_home}/.local/bin/claude update",
                            ),
                            counts=("1 command", "1 skipped"),
                        ),
                    ),
                ),
            ),
            panel_title="Confirm comprehensive update",
            icon="↑",
            incoming_commits_loader=lambda: incoming_groups,
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")

        await page.wait_for(
            lambda _s: len(modal.query("#plugin-action-commits-body")) > 0
        )
        await page.wait_for(
            lambda _s: (
                "2 repositories · 6 incoming commits"
                in _render(
                    modal.query_one("#plugin-action-commits-body", Static).content
                )
            )
        )
        scroll = modal.query_one("#plugin-action-preview-scroll", VerticalScroll)
        await page.wait_for(lambda _s: int(scroll.max_scroll_y) > 0)
        await page.wait_for(lambda _s: scroll.border_subtitle == "ctrl+d/u scroll")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_comprehensive_update_preview_120x32",
            title="ACE SASE Admin Center — Comprehensive update (confirm preview)",
        )
