"""Regression test for the ACE top-bar indicator cluster order."""

from __future__ import annotations

import pytest

import sase.ace.tui.widgets.alias_overrides_indicator as alias_overrides_indicator
import sase.ace.tui.widgets.current_project_indicator as current_project_indicator
import sase.ace.tui.widgets.llm_override_indicator as llm_override_indicator
import sase.ace.tui.widgets.provider_disables_indicator as provider_disables_indicator
from sase.ace.testing import AcePage
from sase.ace.tui.actions import update_toast
from sase.ace.tui.project_styles import project_accent
from sase.ace.tui.widgets import (
    AliasOverridesIndicator,
    CurrentProjectIndicator,
    LLMOverrideIndicator,
    ProviderDisablesIndicator,
    UpdatesAvailableIndicator,
)
from sase.ace.tui.widgets.current_project_indicator import _CurrentProjectSnapshot
from sase.current_project import CurrentProject
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
# sits just right of it so the two override indicators read as a pair. The
# current-project chip mounts immediately after the provider-disables pill:
# both intervening override/disable pills render empty (zero width) in the
# normal case, so the chip sits visually flush against the model indicator
# without splitting the tested override pairing. Pinning the whole order keeps
# future reorders intentional.
EXPECTED_TOP_BAR_ORDER = [
    "tab-bar",
    "proc-indicator",
    "monitor-indicator",
    "updates-indicator",
    "agents-sync-indicator",
    "llm-override-indicator",
    "alias-overrides-indicator",
    "provider-disables-indicator",
    "current-project-indicator",
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


def _current_project() -> CurrentProject:
    return CurrentProject(
        project_key="gh_sase-org__sase",
        display_name="sase",
        origin="project",
        origin_ref="sase",
        workflow_type="gh",
    )


def _paint_current_project_chip(page: AcePage) -> CurrentProjectIndicator:
    """Force the current-project chip visible for narrow-terminal bounds tests."""

    project = _current_project()
    indicator = page.app.query_one(
        "#current-project-indicator",
        CurrentProjectIndicator,
    )
    indicator._cached_snapshot = _CurrentProjectSnapshot(
        project=project,
        accent=project_accent(project.project_key, among=(project.project_key,)),
    )
    indicator._cached_token = ("bounds-test",)
    indicator._cached_failed = False
    indicator._apply_content()
    return indicator


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
    monkeypatch.setattr(
        current_project_indicator,
        "resolve_current_project",
        lambda **_kwargs: _current_project(),
    )
    monkeypatch.setattr(
        current_project_indicator,
        "_enabled_project_keys",
        lambda: (_current_project().project_key,),
    )
    async with AcePage(size=(80, 30)) as page:
        top_bar = page.query_one_widget("#top-bar")
        indicator = page.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        indicator.set_available(3, core=True, agent_cli_count=2)
        project_indicator = _paint_current_project_chip(page)
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()

        assert indicator.render().plain == " ↑ 3 * CLI ↑ 2 "
        assert project_indicator.render().plain == " +sase "
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
        "peek_active_temporary_override",
        lambda *a, **k: default_override,
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
    monkeypatch.setattr(
        current_project_indicator,
        "resolve_current_project",
        lambda **_kwargs: _current_project(),
    )
    monkeypatch.setattr(
        current_project_indicator,
        "_enabled_project_keys",
        lambda: (_current_project().project_key,),
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
        project_indicator = _paint_current_project_chip(page)
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()

        assert default_indicator.render().plain == " CODEX(o3)@xhigh ∞ "
        assert alias_indicator.render().plain == " @medium@max ∞ "
        assert provider_indicator.render().plain == " CLAUDE off ∞ "
        assert project_indicator.render().plain == " +sase "
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
