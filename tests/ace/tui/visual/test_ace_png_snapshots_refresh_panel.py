"""sase's TUI PNG visual snapshot for the Refresh panel chooser."""

from __future__ import annotations

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.actions.event_refresh._freshness import freshness_label
from sase.ace.tui.actions.refresh_panel import FULL_HISTORY_MIGRATION_BANNER
from sase.ace.tui.modals.refresh_panel_modal import (
    RefreshChoice,
    RefreshPanelModal,
    RefreshRow,
    UsageRowStatus,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

THIS_TAB_CHIP = freshness_label(12.0)
FULL_HISTORY_CHIP = freshness_label(7200.0)
USAGE_CHIP = "6m"
AUTO_REFRESH_LABEL = "auto-refresh every 10s · next in 4s"


def _rows() -> tuple[RefreshRow, ...]:
    return (
        RefreshRow(
            choice="this_tab",
            key="r",
            aliases=("R", "enter", "1"),
            title="This tab",
            target="Agents",
            subtitle="Reload the visible inbox from the index.",
            chip=THIS_TAB_CHIP,
            tone="primary",
        ),
        RefreshRow(
            choice="full_history",
            key="f",
            aliases=("2",),
            title="Full history",
            target="Agents",
            subtitle="Rescan every source artifact. Slower.",
            chip=FULL_HISTORY_CHIP,
        ),
        RefreshRow(
            choice="usage",
            key="u",
            aliases=("3",),
            title="Usage windows",
            target="providers",
            subtitle="Re-probe provider subscription limits.",
            chip="",
        ),
        RefreshRow(
            choice="everything",
            key="a",
            aliases=("4",),
            title="Everything",
            target="",
            subtitle="Every surface, full history, and usage.",
            chip="heavier",
            tone="accent",
        ),
    )


def _ready_usage() -> UsageRowStatus:
    return UsageRowStatus(
        provider_count=3,
        chip=USAGE_CHIP,
        unavailable_reason=None,
    )


def _modal(
    *,
    initial_choice: RefreshChoice = "this_tab",
    banner: str | None = None,
) -> RefreshPanelModal:
    return RefreshPanelModal(
        tab_label="Agents",
        rows=_rows(),
        auto_refresh_label=AUTO_REFRESH_LABEL,
        initial_choice=initial_choice,
        banner=banner,
        load_usage_status=_ready_usage,
    )


def _row_plain(modal: RefreshPanelModal, choice: RefreshChoice) -> str:
    return modal.query_one(f"#refresh-panel-row-{choice}", Static).render().plain


async def _open_refresh_panel(page: AcePage, modal: RefreshPanelModal) -> None:
    page.app.push_screen(modal)
    await page.expect_modal("RefreshPanelModal")
    await wait_for_state(
        page,
        lambda: (
            "3 providers" in _row_plain(modal, "usage")
            and USAGE_CHIP in _row_plain(modal, "usage")
        ),
        description="usage row patched with fixed freshness",
    )


async def test_refresh_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")

        await _open_refresh_panel(page, _modal())
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "refresh_panel_120x40",
            title="ACE Refresh panel",
        )


async def test_refresh_panel_full_history_banner_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")

        modal = _modal(
            initial_choice="full_history",
            banner=FULL_HISTORY_MIGRATION_BANNER,
        )
        await _open_refresh_panel(page, modal)
        await wait_for_state(
            page,
            lambda: (
                modal.query_one(
                    "#refresh-panel-row-full_history",
                    Static,
                ).has_class("refresh-panel-row-selected")
                and FULL_HISTORY_MIGRATION_BANNER
                in modal.query_one("#refresh-panel-banner", Static).render().plain
            ),
            description="full-history cursor and ,y migration banner",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "refresh_panel_full_history_banner_120x40",
            title="ACE Refresh panel full-history migration",
        )
