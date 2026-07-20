"""Regression test for the ACE top-bar indicator cluster order."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions import update_toast
from sase.ace.tui.widgets import UpdatesAvailableIndicator

# Expected left-to-right order of widgets inside ``#top-bar``. The ``#tab-bar``
# spacer (``width: 1fr``) anchors the right-aligned indicator cluster, so every
# widget after it forms that cluster. The updates badge must sit immediately to
# the left of the model (LLM override) indicator; the non-default override pill
# sits just right of it so the two override indicators read as a pair. Pinning
# the whole order keeps future reorders intentional.
EXPECTED_TOP_BAR_ORDER = [
    "tab-bar",
    "task-indicator",
    "updates-indicator",
    "llm-override-indicator",
    "alias-overrides-indicator",
    "stashed-prompts-indicator",
    "notification-indicator",
]


async def test_top_bar_places_updates_indicator_left_of_model() -> None:
    async with AcePage() as page:
        top_bar = page.query_one_widget("#top-bar")
        ids = [child.id for child in top_bar.children]

        assert ids == EXPECTED_TOP_BAR_ORDER
        # Pin the relative order this change is about so a regression points at
        # the intended invariant directly.
        assert ids.index("updates-indicator") < ids.index("llm-override-indicator")


async def test_mixed_updates_indicator_keeps_narrow_top_bar_in_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: None,
    )
    async with AcePage(size=(80, 30)) as page:
        top_bar = page.query_one_widget("#top-bar")
        indicator = page.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        indicator.set_available(3, core=True, agent_cli_count=2)
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()

        assert indicator.render().plain == " ↑ 3 * CLI ↑ 2 "
        visible_regions = [
            child.region for child in top_bar.children if child.region.width > 0
        ]
        assert [region.x for region in visible_regions] == sorted(
            region.x for region in visible_regions
        )
        assert max(region.x + region.width for region in visible_regions) <= (
            top_bar.region.x + top_bar.region.width
        )
