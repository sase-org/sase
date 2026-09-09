"""ACE TUI PNG snapshot: top-bar indicators plus usage attention at 60 columns."""

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
from sase.llm_provider.provider_priority import provider_routing_context_from_parts
from sase.llm_provider.usage.hints import CapacityHint
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


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
    project = _current_project()
    indicator = page.app.query_one(
        "#current-project-indicator",
        CurrentProjectIndicator,
    )
    indicator._cached_snapshot = _CurrentProjectSnapshot(
        project=project,
        accent=project_accent(project.project_key, among=(project.project_key,)),
    )
    indicator._cached_token = ("visual-usage-indicator",)
    indicator._cached_failed = False
    indicator._apply_content()
    return indicator


async def test_top_bar_usage_attention_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    default_override = _override("codex", "o3", effort="xhigh")
    alias_override = _override("claude", "opus", effort="max")
    monkeypatch.setattr(
        update_toast, "get_cached_update_status", lambda **_kwargs: None
    )
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
        "peek_provider_routing_context",
        lambda *a, **k: provider_routing_context_from_parts(
            {"claude": _disable("claude")},
            None,
            captured_at=100.0,
        ),
    )
    monkeypatch.setattr(
        provider_disables_indicator,
        "cached_usage_peek",
        lambda: ((), frozenset()),
    )
    monkeypatch.setattr(
        provider_disables_indicator,
        "refresh_usage_peek_cache",
        lambda **_kwargs: ((), frozenset()),
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

    usage_items = (
        CapacityHint(
            kind="rejected",
            label="0% left · Week · all",
            provider="grok",
            window_key="weekly",
            scope="Week · all",
            remaining_percent=0.0,
        ),
        CapacityHint(
            kind="low",
            label="12% left · Shared 5h",
            provider="codex",
            window_key="shared",
            scope="Shared 5h",
            remaining_percent=12.5,
        ),
    )

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(80, 24),
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        updates = page.app.query_one("#updates-indicator", UpdatesAvailableIndicator)
        updates.set_available(3, core=True, agent_cli_count=2)
        provider_indicator = page.app.query_one(
            "#provider-disables-indicator",
            ProviderDisablesIndicator,
        )
        provider_indicator._usage_items = usage_items
        provider_indicator._usage_open_provider = "grok"
        page.app.query_one("#llm-override-indicator", LLMOverrideIndicator)
        page.app.query_one("#alias-overrides-indicator", AliasOverridesIndicator)
        _paint_current_project_chip(page)
        provider_indicator.update(
            ProviderDisablesIndicator._build_content(
                {"claude": _disable("claude")},
                usage_items=usage_items,
                width=80,
                now=100.0,
            )
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "top_bar_usage_attention_80x24",
            title="ACE top bar with routing pills and usage attention at 80 columns",
        )
