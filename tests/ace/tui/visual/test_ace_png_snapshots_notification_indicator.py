"""ACE TUI PNG visual snapshots for the per-tab notification indicator.

Between the three badges every built-in glyph, every kind default, and the
last-resort mark reaches a golden; the tab strip's own icons are covered by
``notification_beads_tab_120x40``, which is too narrow to hold one tab of every
kind at once.

These goldens are *not* a tofu audit for the glyph set, despite reading like
one. The rasterizer is pointed at the bundled Fira Code with system fonts
skipped, so it has no fallback at all, and Fira Code 6.2 carries only ``◆``,
``#``, ``•`` and ``▪`` out of the set. Every other glyph rasterizes as a
replacement box here while rendering fine in a real terminal, which falls back.
This predates tab icons: the indicator's ``✉`` has been a box in these goldens
for as long as it has been drawn. What the snapshots do pin is everything
around the glyph — chip order, spacing, color, and weight.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.notification_modal_tags import (
    MUTED_TAB_KEY,
    SNOOZED_TAB_KEY,
    NotificationTagTab,
)
from sase.ace.tui.widgets.notification_indicator import NotificationIndicator
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    DEFAULT_VISUAL_NOTIFICATION_BADGE,
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

# The tabs ACE ships knowing about, each on its built-in glyph.
_BUILTIN_TABS = [
    NotificationTagTab(tag="hitl", label="Gates", count=2, kind="hitl"),
    NotificationTagTab(tag="errors", label="Errors", count=3, kind="errors"),
    NotificationTagTab(tag="beads", label="Beads", count=1, kind="panel"),
    NotificationTagTab(tag=None, label="General", count=4, kind="general"),
]

# Tabs ACE has never heard of, so each falls through to a kind default — and
# the last one, arriving with no kind at all, to the generic mark.
_KIND_TABS = [
    NotificationTagTab(tag="deploys", label="Deploys", count=2, kind="panel"),
    NotificationTagTab(tag="done", label="Done", count=3, kind="tag"),
    NotificationTagTab(tag=MUTED_TAB_KEY, label="Muted", count=1, kind="muted"),
    NotificationTagTab(tag="mystery", label="Mystery", count=5, kind=""),
]

_SNOOZED_TABS = [
    NotificationTagTab(
        tag=SNOOZED_TAB_KEY,
        label="Snoozed",
        count=4,
        kind="snoozed",
    )
]


async def _drive_indicator(
    page: AcePage,
    tabs: list[NotificationTagTab],
    expected: str,
) -> None:
    """Drive the top-bar indicator to *expected* and settle the frame."""
    await wait_for_startup(page)
    await page.press(page.artifacts_digit("patches"))
    await page.expect_state("artifacts_subtab", "patches")
    await page.expect_state("tab", "patches")
    await wait_for_svg_contains(page, "visual_auth")
    indicator = page.app.query_one("#notification-indicator", NotificationIndicator)
    indicator.set_tabs(tabs)
    await wait_for_state(
        page,
        lambda: indicator.render().plain == expected,
        description="notification indicator badge",
    )
    page.app.refresh(layout=True)
    await page.app.wait_for_refresh()
    await wait_for_visual_idle(page)


async def test_default_visual_notification_indicator_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared visual stub must land as ``⚑1 ✉18`` before any capture."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        indicator = page.app.query_one("#notification-indicator", NotificationIndicator)
        assert indicator.render().plain == DEFAULT_VISUAL_NOTIFICATION_BADGE


async def test_notification_indicator_chips_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each populated tab contributes a self-identifying icon chip."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _drive_indicator(page, _BUILTIN_TABS, " ⚑2 ✖3 ◈1 ✉4 ")
        ace_png_visual.assert_page_png(
            page,
            "notification_indicator_chips_120x40",
            title="ACE notification indicator icon chips",
        )


async def test_notification_indicator_kind_chips_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown tabs still get a glyph that says what kind of tab they are."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _drive_indicator(page, _KIND_TABS, " ◆2 #3 ⊘1 •5 ")
        ace_png_visual.assert_page_png(
            page,
            "notification_indicator_kind_chips_120x40",
            title="ACE notification indicator kind-default chips",
        )


async def test_notification_indicator_snoozed_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A snoozed-only backlog reads as a dim moon, never the old ``z``."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _drive_indicator(page, _SNOOZED_TABS, " ☾4 ")
        ace_png_visual.assert_page_png(
            page,
            "notification_indicator_snoozed_120x40",
            title="ACE notification indicator snoozed badge",
        )
