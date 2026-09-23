"""Mounted tests for the labeled top-bar indicator cluster."""

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
    TopBarIndicators,
    UpdatesAvailableIndicator,
)
from sase.ace.tui.widgets.top_bar import TopBar
from sase.llm_provider import TemporaryLLMOverride
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
)
from sase.llm_provider.provider_priority import provider_routing_context_from_parts


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
    ]


def _cluster_text(page: AcePage) -> str:
    cluster = page.app.query_one("#top-bar-indicators", TopBarIndicators)
    parts = [child.render().plain for child in cluster.children if child.display]
    return "".join(parts)


async def _drive_busy(page: AcePage, monkeypatch: pytest.MonkeyPatch) -> None:
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
    page.app.refresh(layout=True)
    await page.app.wait_for_refresh()
    await page.pause()


async def test_busy_cluster_renders_all_labels_wide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage(size=(180, 40)) as page:
        await _drive_busy(page, monkeypatch)
        text = _cluster_text(page)
        for label in (
            "procs:",
            "monitors:",
            "updates:",
            "overrides:",
            "provider:",
            "prompts:",
            "inbox:",
        ):
            assert label in text
        assert " · " in text
        assert "  ·  " not in text
        cluster = page.app.query_one("#top-bar-indicators", TopBarIndicators)
        assert cluster.density == "full"


async def test_show_hide_show_updates_separators() -> None:
    async with AcePage(size=(180, 40)) as page:
        updates = page.app.query_one("#updates-indicator", UpdatesAvailableIndicator)
        cluster = page.app.query_one("#top-bar-indicators", TopBarIndicators)
        # Initially only the inbox is visible.
        assert "inbox: 0" in _cluster_text(page)
        updates.set_available(3)
        await page.pause()
        assert "updates:" in _cluster_text(page)
        updates.set_available(0)
        await page.pause()
        assert "updates:" not in _cluster_text(page)
        assert updates.region.width == 0
        updates.set_available(2)
        await page.pause()
        assert "updates:" in _cluster_text(page)
        # Hidden separators collapse to zero width.
        for sep in cluster.separators():
            if not sep.display:
                assert sep.region.width == 0


async def test_busy_cluster_compacts_narrow_and_restores_wide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage(size=(180, 40)) as page:
        await _drive_busy(page, monkeypatch)
        cluster = page.app.query_one("#top-bar-indicators", TopBarIndicators)
        top_bar = page.app.query_one("#top-bar", TopBar)
        assert cluster.density == "full"
        await page._pilot.resize_terminal(80, 30)  # noqa: SLF001
        await page.pause()
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await page.pause()
        assert cluster.density == "compact"
        narrow_text = _cluster_text(page)
        assert "procs:" not in narrow_text
        assert " · " in narrow_text
        # Cluster stays within the top-bar bounds.
        assert cluster.region.x + cluster.region.width <= (
            top_bar.region.x + top_bar.region.width
        )
        await page._pilot.resize_terminal(180, 40)  # noqa: SLF001
        await page.pause()
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await page.pause()
        assert cluster.density == "full"
        assert "procs:" in _cluster_text(page)


async def test_newly_clickable_groups_run_home_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:
        calls: list[str] = []

        async def _record(name: str) -> None:
            calls.append(name)

        monkeypatch.setattr(page.app, "run_action", _record)
        page.app.query_one("#proc-indicator", ProcIndicator).set_count(1)
        page.app.query_one("#monitor-indicator", MonitorIndicator).set_count(1)
        page.app.query_one(
            "#stashed-prompts-indicator", StashedPromptsIndicator
        ).set_count(1)
        await page.pause()
        await page.app.query_one("#proc-indicator", ProcIndicator).on_click()
        await page.app.query_one("#monitor-indicator", MonitorIndicator).on_click()
        await page.app.query_one(
            "#stashed-prompts-indicator", StashedPromptsIndicator
        ).on_click()
        assert calls == ["open_tasks_panel", "open_tasks_panel", "open_prompt_stash"]
