"""Regression test for the ACE top-bar indicator cluster order."""

from __future__ import annotations

import pytest

import sase.ace.tui.widgets.alias_overrides_indicator as alias_overrides_indicator
import sase.ace.tui.widgets.launch_context_source as launch_context_source
import sase.ace.tui.widgets.provider_disables_indicator as provider_disables_indicator
from sase.ace.testing import AcePage
from sase.ace.tui.actions import update_toast
from sase.ace.tui.project_styles import project_accent
from sase.ace.tui.widgets import (
    AliasOverridesIndicator,
    CurrentProjectIndicator,
    LaunchContextBar,
    LLMOverrideIndicator,
    ProviderDisablesIndicator,
    UpdatesAvailableIndicator,
)
from sase.ace.tui.widgets.launch_context_source import CurrentProjectSnapshot
from sase.current_project import CurrentProject
from sase.llm_provider import TemporaryLLMOverride, TemporaryProviderDisable
from sase.llm_provider.config import (
    DEFAULT_MODEL_FIELD,
    launch_model_setting_override_key,
)
from sase.llm_provider.provider_disable import PROVIDER_DISABLE_WIRE_SCHEMA_VERSION
from sase.llm_provider.provider_priority import provider_routing_context_from_parts

# Expected left-to-right order of widgets inside ``#top-bar``. The ``#tab-bar``
# spacer (``width: 1fr``) anchors the right-aligned indicator cluster, so every
# widget after it forms that cluster. The launch-default model and current
# project chips no longer live here: they render in the labeled
# ``LaunchContextBar`` at the far right of each tab's status row, so the top
# bar keeps only the alert-style indicators (procs, monitors, updates, the
# violet non-``default`` alias override pill, provider disables, stashed
# prompts, notifications). Pinning the whole order keeps future reorders
# intentional.
EXPECTED_TOP_BAR_ORDER = [
    "tab-bar",
    "proc-indicator",
    "monitor-indicator",
    "updates-indicator",
    "alias-overrides-indicator",
    "provider-disables-indicator",
    "stashed-prompts-indicator",
    "notification-indicator",
]

# Expected left-to-right child order inside every ``LaunchContextBar``: the
# model label, the model view, the group separator, the project label, and
# the project view.
EXPECTED_LAUNCH_CONTEXT_BAR_ORDER = [
    "launch-model-label",
    "llm-override-indicator",
    "launch-separator",
    "launch-project-label",
    "current-project-indicator",
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
    indicator = page.app.query(CurrentProjectIndicator).first()
    indicator._cached_snapshot = CurrentProjectSnapshot(
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
        assert ids.index("updates-indicator") < ids.index("alias-overrides-indicator")
        # The launch-context chips left the top bar for the status rows.
        assert "llm-override-indicator" not in ids
        assert "current-project-indicator" not in ids


async def test_launch_context_cluster_closes_each_status_row() -> None:
    """Each tab's status row ends with the labeled cluster in child order."""

    async with AcePage() as page:
        for row_id in ("#agent-info-row", "#artifacts-header", "#axe-info-row"):
            row = page.query_one_widget(row_id)
            last = row.children[-1]
            assert isinstance(last, LaunchContextBar), row_id
            assert [child.id for child in last.children] == (
                EXPECTED_LAUNCH_CONTEXT_BAR_ORDER
            ), row_id
            model_view = last.query_one(LLMOverrideIndicator)
            project_view = last.query_one(CurrentProjectIndicator)
            assert model_view is not None
            assert project_view is not None


async def test_mixed_updates_indicator_keeps_narrow_top_bar_in_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        launch_context_source,
        "resolve_current_project",
        lambda **_kwargs: _current_project(),
    )
    monkeypatch.setattr(
        launch_context_source,
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
        assert project_indicator.render().plain == "+sase"
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
        launch_context_source,
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
        "peek_provider_routing_context",
        lambda *a, **k: provider_routing_context_from_parts(
            {"claude": _disable("claude")},
            None,
            captured_at=100.0,
        ),
    )
    monkeypatch.setattr(
        launch_context_source,
        "resolve_current_project",
        lambda **_kwargs: _current_project(),
    )
    monkeypatch.setattr(
        launch_context_source,
        "_enabled_project_keys",
        lambda: (_current_project().project_key,),
    )

    async with AcePage(size=(80, 30)) as page:
        top_bar = page.query_one_widget("#top-bar")
        default_indicator = page.app.query(LLMOverrideIndicator).first()
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

        assert default_indicator.render().plain == "CODEX(o3)@xhigh ∞"
        assert alias_indicator.render().plain == " @medium@max ∞ "
        assert provider_indicator.render().plain == " CLAUDE off ∞ "
        assert project_indicator.render().plain == "+sase"
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
