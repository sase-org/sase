"""Regression test for the ACE top-bar indicator cluster order."""

from __future__ import annotations

import pytest

import sase.ace.tui.widgets.alias_overrides_indicator as alias_overrides_indicator
import sase.ace.tui.widgets.llm_override_indicator as llm_override_indicator
from sase.ace.testing import AcePage
from sase.ace.tui.actions import update_toast
from sase.ace.tui.widgets import (
    AliasOverridesIndicator,
    LLMOverrideIndicator,
    UpdatesAvailableIndicator,
)
from sase.llm_provider import TemporaryLLMOverride

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
    "agents-sync-indicator",
    "llm-override-indicator",
    "alias-overrides-indicator",
    "stashed-prompts-indicator",
    "notification-indicator",
]


def _override(
    provider: str,
    model: str,
    *,
    effort: str | None = None,
) -> TemporaryLLMOverride:
    return TemporaryLLMOverride(
        provider=provider,
        model=model,
        raw_model=f"{provider}/{model}",
        created_at=100.0,
        expires_at=None,
        source="test",
        effort=effort,
    )


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


async def test_override_pills_keep_narrow_top_bar_in_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_override = _override("codex", "o3", effort="xhigh")
    alias_override = _override("claude", "opus", effort="max")
    monkeypatch.setattr(
        llm_override_indicator,
        "get_active_temporary_override",
        lambda: default_override,
    )
    monkeypatch.setattr(
        alias_overrides_indicator,
        "get_active_alias_overrides",
        lambda: {
            "default": default_override,
            "coder": alias_override,
        },
    )

    async with AcePage(size=(80, 30)) as page:
        top_bar = page.query_one_widget("#top-bar")
        default_indicator = page.app.query_one(
            "#llm-override-indicator",
            LLMOverrideIndicator,
        )
        alias_indicator = page.app.query_one(
            "#alias-overrides-indicator",
            AliasOverridesIndicator,
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()

        assert default_indicator.render().plain == " CODEX(o3)@xhigh ∞ "
        assert alias_indicator.render().plain == " @coder@max ∞ "
        visible_children = [
            child for child in top_bar.children if child.region.width > 0
        ]
        assert [child.id for child in top_bar.children] == EXPECTED_TOP_BAR_ORDER
        assert [child.region.x for child in visible_children] == sorted(
            child.region.x for child in visible_children
        )
        assert max(
            child.region.x + child.region.width for child in visible_children
        ) <= (top_bar.region.x + top_bar.region.width)
