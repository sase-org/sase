"""Tests for the plugin action confirmation modal."""

from __future__ import annotations

import os
import threading

import pytest
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionPreviewComponent,
    PluginActionPreviewSection,
    PluginActionVariant,
)
from sase.updates.incoming_commits import (
    CommitSummary,
    IncomingCommits,
    RepoIncomingCommits,
)
from tests.ace.tui._plugins_browser_pane_helpers import _render


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


def _modal_variant() -> PluginActionVariant:
    return PluginActionVariant(
        key="update",
        label="update",
        argv=("uv", "tool", "install", "sase-nvim"),
        summary="Upgrades nvim",
    )


async def test_plugin_action_modal_without_loader_has_no_commits_box() -> None:
    async with AcePage() as page:
        modal = PluginActionConfirmModal(
            title="Update nvim",
            intro="Confirm",
            variants=(_modal_variant(),),
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")

        assert len(modal.query("#plugin-action-commits")) == 0
        await page.wait_for(
            lambda _s: len(modal.query("#plugin-action-preview-scroll")) > 0
        )
        preview = modal.query_one("#plugin-action-preview-scroll", VerticalScroll)
        await page.pause()
        assert int(preview.max_scroll_y) == 0
        assert preview.border_subtitle == ""
        assert not modal.has_class("has-scrollable-preview")
        await page.press("ctrl+d")
        await page.press("ctrl+u")
        assert page.app.screen is modal


def test_plugin_action_modal_renders_components_and_shortens_home() -> None:
    home = os.environ.get("HOME", "/home/test")
    modal = PluginActionConfirmModal(
        title="Update everything",
        intro="Confirm",
        variants=(
            PluginActionVariant(
                key="update",
                label="update",
                argv=(f"{home}/.local/bin/updater", "--all"),
                summary="Updates selected components",
                sections=(
                    PluginActionPreviewSection(
                        title="Components",
                        components=(
                            PluginActionPreviewComponent(
                                "will-update", "1.0 → 2.0", "update"
                            ),
                            PluginActionPreviewComponent(
                                "already-current", "2.0", "current"
                            ),
                            PluginActionPreviewComponent(
                                "manual-only", "vendor action required", "skipped"
                            ),
                        ),
                        commands=(
                            f"{home}/projects/tool/bin/update --all",
                            f"fallback: {home}/projects/tool/bin/repair",
                        ),
                        counts=("1 command", "1 skipped"),
                    ),
                ),
            ),
        ),
    )

    rendered = _render(modal._preview_renderable())

    assert "↑ will-update" in rendered
    assert "✓ already-current" in rendered
    assert "• manual-only" in rendered
    assert "Components · 1 command · 1 skipped" in rendered
    assert "~/.local/bin/updater --all" in rendered
    assert "~/projects/tool/bin/update --all" in rendered
    assert "fallback:" in rendered
    assert f"{home}/projects/tool" not in rendered


async def test_plugin_action_modal_scrolls_overflowing_preview() -> None:
    variant = PluginActionVariant(
        key="update",
        label="update",
        argv=(),
        summary="Updates many components",
        details=tuple(f"preview detail {index}" for index in range(80)),
    )

    async with AcePage(size=(100, 24)) as page:
        modal = PluginActionConfirmModal(
            title="Comprehensive update",
            intro="Confirm",
            variants=(variant,),
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")

        await page.wait_for(
            lambda _s: len(modal.query("#plugin-action-preview-scroll")) > 0
        )
        scroll = modal.query_one("#plugin-action-preview-scroll", VerticalScroll)
        await page.wait_for(lambda _s: int(scroll.max_scroll_y) > 0)
        await page.wait_for(lambda _s: modal.has_class("has-scrollable-preview"))
        await page.wait_for(lambda _s: scroll.border_subtitle == "ctrl+d/u scroll")

        half_page = max(1, scroll.scrollable_content_region.height // 2)
        max_scroll_y = int(scroll.max_scroll_y)
        assert scroll.scroll_y == 0

        await page.press("ctrl+d")
        await page.pause()
        assert scroll.scroll_y == min(half_page, max_scroll_y)

        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == 0

        await page.press("ctrl+d")
        await page.pause()
        assert scroll.scroll_y == min(half_page, max_scroll_y)

        near_bottom = max(0, max_scroll_y - half_page + 1)
        scroll.scroll_to(y=near_bottom, animate=False)
        await page.pause()
        assert scroll.scroll_y == near_bottom
        await page.press("ctrl+d")
        await page.pause()
        assert scroll.scroll_y == max_scroll_y
        await page.press("ctrl+d")
        await page.pause()
        assert scroll.scroll_y == max_scroll_y

        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == max(0, max_scroll_y - half_page)
        near_top = min(max_scroll_y, max(0, half_page - 1))
        scroll.scroll_to(y=near_top, animate=False)
        await page.pause()
        assert scroll.scroll_y == near_top
        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == 0
        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == 0


async def test_plugin_action_modal_loads_grouped_incoming_commits() -> None:
    groups = (
        RepoIncomingCommits(
            "sase",
            IncomingCommits(
                total=2,
                commits=(
                    CommitSummary("abc1234", "Newest core change"),
                    CommitSummary("def5678", "Older core change"),
                ),
                source="github",
            ),
        ),
        RepoIncomingCommits(
            "github",
            IncomingCommits(
                total=1,
                commits=(CommitSummary("fff0000", "Plugin change"),),
                source="github",
            ),
        ),
    )

    async with AcePage() as page:
        modal = PluginActionConfirmModal(
            title="Update SASE",
            intro="Confirm",
            variants=(_modal_variant(),),
            incoming_commits_loader=lambda: groups,
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")
        await page.wait_for(lambda _s: len(modal.query("#plugin-action-commits")) > 0)

        body = modal.query_one("#plugin-action-commits-body", Static)
        await page.wait_for(
            lambda _s: (
                "↑ sase — 2 incoming commits" in _render(body.content)
                and "↑ github — 1 incoming commit" in _render(body.content)
            )
        )
        rendered = _render(body.content)
        assert "2 repositories · 3 incoming commits" in rendered
        assert rendered.count("↑ sase — 2 incoming commits") == 1
        assert rendered.count("↑ github — 1 incoming commit") == 1
        scroll = modal.query_one("#plugin-action-commits", VerticalScroll)
        preview = modal.query_one("#plugin-action-preview-scroll", VerticalScroll)
        await page.pause()
        assert scroll.region.y < preview.region.y
        assert int(scroll.max_scroll_y) == 0
        assert scroll.border_subtitle == ""
        await page.press("ctrl+d")
        await page.press("ctrl+u")
        assert scroll.scroll_y == 0


async def test_plugin_action_modal_summarizes_long_grouped_incoming_commits() -> None:
    groups = (
        RepoIncomingCommits(
            "sase",
            IncomingCommits(
                total=300,
                commits=tuple(
                    CommitSummary(f"{idx:07x}", f"SASE change {idx}")
                    for idx in range(250)
                ),
                source="git",
            ),
        ),
        RepoIncomingCommits(
            "sase-core",
            IncomingCommits(
                total=2,
                commits=(
                    CommitSummary("abc1234", "Core change"),
                    CommitSummary("def5678", "Core follow-up"),
                ),
                source="git",
            ),
        ),
        RepoIncomingCommits(
            "github",
            IncomingCommits(
                total=1,
                commits=(CommitSummary("fff0000", "Plugin change"),),
                source="git",
            ),
        ),
    )

    async with AcePage(size=(100, 24)) as page:
        modal = PluginActionConfirmModal(
            title="Update SASE",
            intro="Confirm",
            variants=(_modal_variant(),),
            incoming_commits_loader=lambda: groups,
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")
        await page.wait_for(lambda _s: len(modal.query("#plugin-action-commits")) > 0)

        body = modal.query_one("#plugin-action-commits-body", Static)
        await page.wait_for(lambda _s: "SASE change 0" in _render(body.content))
        rendered = _render(body.content)
        first_detail = rendered.index("SASE change 0")
        assert "3 repositories · 303 incoming commits" in rendered
        assert rendered.index("↑ sase — 300 incoming commits") < first_detail
        assert first_detail < rendered.index("↑ sase-core — 2 incoming commits")
        assert rendered.count("↑ sase-core — 2 incoming commits") == 1
        assert rendered.count("↑ github — 1 incoming commit") == 1
        assert "+50 more" in rendered


async def test_plugin_action_modal_empty_incoming_commits_hides_box() -> None:
    async with AcePage() as page:
        modal = PluginActionConfirmModal(
            title="Update SASE",
            intro="Confirm",
            variants=(_modal_variant(),),
            incoming_commits_loader=lambda: (),
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")
        await page.wait_for(lambda _s: len(modal.query("#plugin-action-commits")) > 0)

        scroll = modal.query_one("#plugin-action-commits", VerticalScroll)
        await page.wait_for(lambda _s: not scroll.display)
        await page.press("ctrl+d")
        await page.press("ctrl+u")
        assert scroll.scroll_y == 0


async def test_plugin_action_modal_explicit_empty_incoming_commits_state() -> None:
    message = "No repository commit ranges are available for provider updates."
    async with AcePage() as page:
        modal = PluginActionConfirmModal(
            title="Update providers",
            intro="Confirm",
            variants=(_modal_variant(),),
            incoming_commits_empty_message=message,
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")
        await page.wait_for(lambda _s: len(modal.query("#plugin-action-commits")) > 0)

        scroll = modal.query_one("#plugin-action-commits", VerticalScroll)
        body = modal.query_one("#plugin-action-commits-body", Static)
        assert scroll.display
        assert message in _render(body.content)


async def test_plugin_action_modal_incoming_commits_loader_error() -> None:
    def loader() -> tuple[RepoIncomingCommits, ...]:
        raise RuntimeError("boom")

    async with AcePage() as page:
        modal = PluginActionConfirmModal(
            title="Update SASE",
            intro="Confirm",
            variants=(_modal_variant(),),
            incoming_commits_loader=loader,
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")
        await page.wait_for(lambda _s: len(modal.query("#plugin-action-commits")) > 0)

        body = modal.query_one("#plugin-action-commits-body", Static)
        await page.wait_for(
            lambda _s: "incoming commits unavailable (boom)" in _render(body.content)
        )


async def test_plugin_action_modal_renders_partial_repository_failure() -> None:
    groups = (
        RepoIncomingCommits(
            "sase",
            IncomingCommits(
                total=1,
                commits=(CommitSummary("abc1234", "Available change"),),
                source="git",
            ),
        ),
        RepoIncomingCommits(
            "github",
            IncomingCommits(
                total=0,
                commits=(),
                source="unavailable",
                error="offline mode",
            ),
        ),
    )
    async with AcePage() as page:
        modal = PluginActionConfirmModal(
            title="Update SASE",
            intro="Confirm",
            variants=(_modal_variant(),),
            incoming_commits_loader=lambda: groups,
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")
        await page.wait_for(
            lambda _s: len(modal.query("#plugin-action-commits-body")) > 0
        )
        body = modal.query_one("#plugin-action-commits-body", Static)
        await page.wait_for(lambda _s: "Available change" in _render(body.content))
        rendered = _render(body.content)
        assert "2 repositories · 1 incoming commit · 1 unavailable" in rendered
        assert "github: incoming commits unavailable (offline mode)" in rendered


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("n", None),
        ("y", PluginActionConfirmResult("update")),
    ],
)
async def test_plugin_action_modal_stays_decidable_while_commits_load(
    key: str,
    expected: PluginActionConfirmResult | None,
) -> None:
    started = threading.Event()
    release = threading.Event()

    def loader() -> tuple[RepoIncomingCommits, ...]:
        started.set()
        release.wait(timeout=5)
        return ()

    async with AcePage() as page:
        results: list[PluginActionConfirmResult | None] = []
        modal = PluginActionConfirmModal(
            title="Update SASE",
            intro="Confirm",
            variants=(_modal_variant(),),
            incoming_commits_loader=loader,
        )
        page.app.push_screen(modal, results.append)
        await page.expect_modal("PluginActionConfirmModal")
        await page.wait_for(lambda _s: started.is_set())
        body = modal.query_one("#plugin-action-commits-body", Static)
        assert "checking incoming commits" in _render(body.content)

        await page.press(key)
        await page.wait_for(lambda _s: bool(results))
        assert results == [expected]
        release.set()


@pytest.mark.parametrize("size", [(100, 24), (120, 40)])
async def test_plugin_action_modal_scrolls_incoming_commits(
    size: tuple[int, int],
) -> None:
    groups = (
        RepoIncomingCommits(
            "sase",
            IncomingCommits(
                total=60,
                commits=tuple(
                    CommitSummary(f"{idx:07x}", f"Incoming SASE change {idx}")
                    for idx in range(60)
                ),
                source="git",
            ),
        ),
        RepoIncomingCommits(
            "github",
            IncomingCommits(
                total=8,
                commits=tuple(
                    CommitSummary(f"f{idx:06x}", f"Incoming plugin change {idx}")
                    for idx in range(8)
                ),
                source="git",
            ),
        ),
    )

    async with AcePage(size=size) as page:
        modal = PluginActionConfirmModal(
            title="Update SASE",
            intro="Confirm",
            variants=(_modal_variant(),),
            incoming_commits_loader=lambda: groups,
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")
        await page.wait_for(lambda _s: len(modal.query("#plugin-action-commits")) > 0)

        scroll = modal.query_one("#plugin-action-commits", VerticalScroll)
        await page.wait_for(lambda _s: int(scroll.max_scroll_y) > 0)
        await page.wait_for(lambda _s: scroll.border_subtitle == "ctrl+d/u scroll")
        preview = modal.query_one("#plugin-action-preview-scroll", VerticalScroll)
        assert int(preview.max_scroll_y) == 0
        assert preview.border_subtitle == ""

        container = modal.query_one("#plugin-action-container")
        buttons = modal.query_one("#plugin-action-buttons")
        bounds = container.content_region
        for child in (scroll, buttons):
            assert child.region.x >= bounds.x
            assert child.region.y >= bounds.y
            assert child.region.right <= bounds.right
            assert child.region.bottom <= bounds.bottom

        half_page = max(1, scroll.scrollable_content_region.height // 2)
        max_scroll_y = int(scroll.max_scroll_y)
        assert scroll.scroll_y == 0

        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == 0

        await page.press("ctrl+d")
        await page.pause()
        assert scroll.scroll_y == min(half_page, max_scroll_y)

        near_bottom = max(0, max_scroll_y - half_page + 1)
        scroll.scroll_to(y=near_bottom, animate=False)
        await page.pause()
        assert scroll.scroll_y == near_bottom
        await page.press("ctrl+d")
        await page.pause()
        assert scroll.scroll_y == max_scroll_y
        await page.press("ctrl+d")
        await page.pause()
        assert scroll.scroll_y == max_scroll_y

        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == max(0, max_scroll_y - half_page)
        near_top = min(max_scroll_y, max(0, half_page - 1))
        scroll.scroll_to(y=near_top, animate=False)
        await page.pause()
        assert scroll.scroll_y == near_top
        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == 0
        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == 0


async def test_plugin_action_modal_scrolls_both_regions_in_reading_order() -> None:
    groups = (
        RepoIncomingCommits(
            "sase",
            IncomingCommits(
                total=60,
                commits=tuple(
                    CommitSummary(f"{idx:07x}", f"Incoming change {idx}")
                    for idx in range(60)
                ),
                source="git",
            ),
        ),
    )
    variant = PluginActionVariant(
        key="update",
        label="update",
        argv=(),
        summary="Updates many components",
        details=tuple(f"execution detail {index}" for index in range(80)),
    )

    async with AcePage(size=(100, 24)) as page:
        modal = PluginActionConfirmModal(
            title="Comprehensive update",
            intro="Confirm",
            variants=(variant,),
            incoming_commits_loader=lambda: groups,
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")
        await page.wait_for(lambda _s: len(modal.query("#plugin-action-commits")) > 0)
        commits = modal.query_one("#plugin-action-commits", VerticalScroll)
        preview = modal.query_one("#plugin-action-preview-scroll", VerticalScroll)
        await page.wait_for(
            lambda _s: int(commits.max_scroll_y) > 0 and int(preview.max_scroll_y) > 0
        )

        commits.scroll_to(y=commits.max_scroll_y, animate=False)
        await page.pause()
        assert preview.scroll_y == 0
        await page.press("ctrl+d")
        await page.pause()
        assert preview.scroll_y > 0

        await page.press("ctrl+u")
        await page.pause()
        assert preview.scroll_y == 0
        commits_before = commits.scroll_y
        await page.press("ctrl+u")
        await page.pause()
        assert commits.scroll_y < commits_before
