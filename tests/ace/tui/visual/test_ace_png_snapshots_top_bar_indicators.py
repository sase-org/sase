"""PNG visual snapshots for the labeled top-bar indicator cluster.

Two goldens pin the full Busy cluster: all seven groups visible at a wide
size (full labels) and the same state at a narrow size (compact, labels
dropped together). Until-cleared overrides keep the frame deterministic.
"""

from __future__ import annotations

import pytest

import sase.ace.tui.widgets.alias_overrides_indicator as alias_overrides_indicator
import sase.ace.tui.widgets.provider_disables_indicator as provider_disables_indicator
from sase.ace.testing import AcePage
from sase.ace.tui.modals.notification_modal_tags import NotificationTagTab
from sase.ace.tui.widgets import (
    AliasOverridesIndicator,
    MonitorIndicator,
    NotificationIndicator,
    ProcIndicator,
    ProviderDisablesIndicator,
    StashedPromptsIndicator,
    UpdatesAvailableIndicator,
)
from sase.llm_provider import TemporaryLLMOverride
from sase.llm_provider.provider_disable import PROVIDER_DISABLE_WIRE_SCHEMA_VERSION
from sase.llm_provider.provider_priority import provider_routing_context_from_parts
from sase.llm_provider.provider_disable import TemporaryProviderDisable
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _override() -> TemporaryLLMOverride:
    return TemporaryLLMOverride(
        provider="claude",
        model="opus",
        raw_model="claude/opus",
        created_at=100.0,
        expires_at=None,
        source="test",
        effort="max",
    )


def _disable() -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider="claude",
        created_at=100.0,
        expires_at=None,
        source="test",
    )


def _tabs() -> list[NotificationTagTab]:
    return [
        NotificationTagTab(tag="hitl", label="Gates", count=5, kind="hitl"),
        NotificationTagTab(tag="beads", label="Beads", count=1, kind="panel"),
        NotificationTagTab(tag=None, label="General", count=18, kind="general"),
    ]


async def _drive_busy(page: AcePage) -> None:
    await wait_for_startup(page)
    await page.press(page.artifacts_digit("patches"))
    await page.expect_state("artifacts_subtab", "patches")
    await page.expect_state("tab", "patches")
    await wait_for_svg_contains(page, "visual_auth")
    page.app.query_one("#proc-indicator", ProcIndicator).set_count(2)
    page.app.query_one("#monitor-indicator", MonitorIndicator).set_count(1)
    page.app.query_one("#updates-indicator", UpdatesAvailableIndicator).set_available(
        3, core=True, agent_cli_count=2
    )
    page.app.query_one("#alias-overrides-indicator", AliasOverridesIndicator).refresh()
    page.app.query_one(
        "#provider-disables-indicator", ProviderDisablesIndicator
    ).refresh()
    page.app.query_one("#stashed-prompts-indicator", StashedPromptsIndicator).set_count(
        4
    )
    page.app.query_one("#notification-indicator", NotificationIndicator).set_tabs(
        _tabs()
    )
    await wait_for_state(
        page,
        lambda: (
            "procs:"
            in page.app.query_one("#proc-indicator", ProcIndicator).render().plain
        ),
        description="busy top-bar cluster",
    )
    page.app.refresh(layout=True)
    await page.app.wait_for_refresh()
    await wait_for_visual_idle(page)


async def test_top_bar_indicators_full_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All seven groups visible at a wide size with full labels."""
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        alias_overrides_indicator,
        "get_active_alias_overrides",
        lambda: {"medium": _override()},
    )
    monkeypatch.setattr(
        provider_disables_indicator,
        "peek_provider_routing_context",
        lambda *a, **k: provider_routing_context_from_parts(
            {"claude": _disable()}, None, captured_at=100.0
        ),
    )

    async with AcePage(query='"visual"', patches=patches(), size=(200, 40)) as page:
        await _drive_busy(page)
        ace_png_visual.assert_page_png(
            page,
            "top_bar_indicators_full_200x40",
            title="ACE labeled top-bar indicators full",
        )


async def test_top_bar_indicators_compact_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same busy state at a narrow size with labels dropped together."""
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        alias_overrides_indicator,
        "get_active_alias_overrides",
        lambda: {"medium": _override()},
    )
    monkeypatch.setattr(
        provider_disables_indicator,
        "peek_provider_routing_context",
        lambda *a, **k: provider_routing_context_from_parts(
            {"claude": _disable()}, None, captured_at=100.0
        ),
    )

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await wait_for_svg_contains(page, "visual_auth")
        page.app.query_one("#proc-indicator", ProcIndicator).set_count(2)
        page.app.query_one("#monitor-indicator", MonitorIndicator).set_count(1)
        page.app.query_one(
            "#updates-indicator", UpdatesAvailableIndicator
        ).set_available(3, core=True, agent_cli_count=2)
        page.app.query_one(
            "#alias-overrides-indicator", AliasOverridesIndicator
        ).refresh()
        page.app.query_one(
            "#provider-disables-indicator", ProviderDisablesIndicator
        ).refresh()
        page.app.query_one(
            "#stashed-prompts-indicator", StashedPromptsIndicator
        ).set_count(4)
        page.app.query_one("#notification-indicator", NotificationIndicator).set_tabs(
            _tabs()
        )
        await wait_for_state(
            page,
            lambda: (
                page.app.query_one("#proc-indicator", ProcIndicator)
                .render()
                .plain.strip()
                != ""
            ),
            description="busy compact top-bar cluster",
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "top_bar_indicators_compact_120x40",
            title="ACE labeled top-bar indicators compact",
        )
