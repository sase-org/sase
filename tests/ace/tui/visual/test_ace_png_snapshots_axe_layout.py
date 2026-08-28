"""ACE TUI PNG snapshots for responsive AXE sidebar layout."""

from __future__ import annotations

import pytest
from textual.containers import VerticalScroll

from sase.ace.testing import AcePage
from sase.ace.tui.app import _MIN_BGCMD_LIST_WIDTH
from sase.ace.tui.widgets import KeybindingFooter
from tests.ace.tui.visual._ace_axe_png_snapshot_fixtures import axe_long_label_data
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _widget_plain(page: AcePage, selector: str) -> str:
    rendered = page.app.query_one(selector).render()
    return rendered.plain if hasattr(rendered, "plain") else str(rendered)


def _axe_long_label_summary_populated(page: AcePage) -> bool:
    try:
        text = "\n".join(
            (
                _widget_plain(page, "#axe-status-section"),
                _widget_plain(page, "#axe-output-section"),
            )
        )
    except Exception:
        return False
    return all(part in text for part in ("review_pipeline", "success", "1.0s"))


async def _pin_axe_output_top(page: AcePage) -> None:
    page.app._axe_pinned_to_bottom = False
    scroll = page.app.query_one("#axe-output-scroll", VerticalScroll)
    scroll.styles.overflow_y = "hidden"
    scroll._scroll_to(y=0, animate=False, force=True)  # noqa: SLF001
    await wait_for_state(
        page,
        lambda: int(scroll.scroll_y) == 0,
        description="AXE output scroll pinned to top",
    )


async def test_axe_long_label_widening_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Long lumberjack/chop labels widen the sidebar without wrapping."""
    patch_startup_loaders(monkeypatch, axe_data=axe_long_label_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")

        sidebar = page.app.query_one("#bgcmd-list-container")
        width = sidebar.styles.width
        assert width is not None, "expected sidebar to have a width set"
        sidebar_width = int(width.value)
        assert sidebar_width > _MIN_BGCMD_LIST_WIDTH, (
            f"expected sidebar to widen past {_MIN_BGCMD_LIST_WIDTH}, "
            f"got {sidebar_width}"
        )
        # The AXE footer repaint can lag the tab change under xdist; settle
        # only the footer so the dashboard golden stays focused on layout.
        footer = page.app.query_one("#keybinding-footer", KeybindingFooter)
        footer.update_axe_bindings(axe_current_view=page.app._axe_current_view)
        await wait_for_state(
            page,
            lambda: _axe_long_label_summary_populated(page),
            description="populated AXE long-label status summary",
        )
        await _pin_axe_output_top(page)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_long_label_widened_120x40",
            title="ACE axe long-label widened sidebar",
        )


async def test_axe_constrained_width_no_wrap_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Narrow terminal with long labels proves no-wrap + ellipsis behavior."""
    patch_startup_loaders(monkeypatch, axe_data=axe_long_label_data())

    # 60x30 is small enough that the sidebar gets clamped to its minimum and
    # the long lumberjack/chop labels can't fit — they must ellipsize on a
    # single line rather than wrap.
    async with AcePage(query='"visual"', patches=patches(), size=(60, 30)) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_state(
            page,
            lambda: _axe_long_label_summary_populated(page),
            description="populated AXE long-label status summary",
        )
        await _pin_axe_output_top(page)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_constrained_width_no_wrap_60x30",
            title="ACE axe constrained width no-wrap",
        )
