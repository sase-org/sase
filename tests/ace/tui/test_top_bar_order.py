"""Regression test for the ACE top-bar indicator cluster order."""

from __future__ import annotations

from sase.ace.testing import AcePage

# Expected left-to-right order of widgets inside ``#top-bar``. The ``#tab-bar``
# spacer (``width: 1fr``) anchors the right-aligned indicator cluster, so every
# widget after it forms that cluster. The updates badge must sit immediately to
# the left of the model (LLM override) indicator; pinning the whole order keeps
# future reorders intentional.
EXPECTED_TOP_BAR_ORDER = [
    "tab-bar",
    "task-indicator",
    "updates-indicator",
    "llm-override-indicator",
    "inactive-indicator",
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
