"""Regression test for the ACE top-bar indicator cluster order."""

from __future__ import annotations

import pytest

import sase.ace.tui.widgets.alias_overrides_indicator as alias_overrides_indicator
import sase.ace.tui.widgets.llm_override_indicator as llm_override_indicator
import sase.ace.tui.widgets.provider_disables_indicator as provider_disables_indicator
from sase.ace.testing import AcePage
from sase.ace.tui.actions import update_toast
from sase.ace.tui.widgets import (
    AliasOverridesIndicator,
    LLMOverrideIndicator,
    ProviderDisablesIndicator,
    UpdatesAvailableIndicator,
)
from sase.llm_provider import TemporaryLLMOverride, TemporaryProviderDisable
from sase.llm_provider.config import (
    DEFAULT_MODEL_FIELD,
    launch_model_setting_override_key,
)
from sase.llm_provider.provider_disable import PROVIDER_DISABLE_WIRE_SCHEMA_VERSION

# Expected left-to-right order of widgets inside ``#top-bar``. The ``#tab-bar``
# spacer (``width: 1fr``) anchors the right-aligned indicator cluster, so every
# widget after it forms that cluster. The updates badge must sit immediately to
# the left of the model (LLM override) indicator; the non-default override pill
# sits just right of it so the two override indicators read as a pair. Pinning
# the whole order keeps future reorders intentional.
EXPECTED_TOP_BAR_ORDER = [
    "tab-bar",
    "proc-indicator",
    "updates-indicator",
    "agents-sync-indicator",
    "llm-override-indicator",
    "alias-overrides-indicator",
    "provider-disables-indicator",
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


def _disable(provider: str) -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=None,
        source="test",
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
            launch_model_setting_override_key(DEFAULT_MODEL_FIELD): default_override,
            "medium": alias_override,
        },
    )
    monkeypatch.setattr(
        provider_disables_indicator,
        "peek_active_provider_disables",
        lambda: {"claude": _disable("claude")},
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
        provider_indicator = page.app.query_one(
            "#provider-disables-indicator",
            ProviderDisablesIndicator,
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()

        assert default_indicator.render().plain == " CODEX(o3)@xhigh ∞ "
        assert alias_indicator.render().plain == " @medium@max ∞ "
        assert provider_indicator.render().plain == " CLAUDE off ∞ "
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
