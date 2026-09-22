"""sase's TUI PNG visual snapshots for the updates badge states."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import UpdatesAvailableIndicator
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


async def test_updates_indicator_routine_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Routine updates use the deep moss chip with lime ink."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await wait_for_svg_contains(page, "visual_auth")
        indicator = page.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        indicator.set_available(3)
        await wait_for_state(
            page,
            lambda: indicator.render().plain == " ⬆ 3 ",
            description="routine updates indicator",
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "updates_indicator_routine_120x40",
            title="ACE routine updates indicator",
        )


async def test_updates_indicator_core_rebuild_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pending core update adds the lime core tag on the same chip."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await wait_for_svg_contains(page, "visual_auth")
        indicator = page.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        indicator.set_available(3, core=True)
        await wait_for_state(
            page,
            lambda: indicator.render().plain == " ⬆ 3  core ",
            description="core-rebuild updates indicator",
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "updates_indicator_core_rebuild_120x40",
            title="ACE core rebuild updates indicator",
        )


async def test_updates_indicator_agent_cli_only_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent-CLI-only updates use the sage segment on moss."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await wait_for_svg_contains(page, "visual_auth")
        indicator = page.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        indicator.set_available(0, agent_cli_count=2)
        await wait_for_state(
            page,
            lambda: indicator.render().plain == " CLI ⬆ 2 ",
            description="agent-CLI-only updates indicator",
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "updates_indicator_agent_cli_only_120x40",
            title="ACE agent-CLI-only updates indicator",
        )


async def test_updates_indicator_mixed_routine_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed routine updates join lime and sage segments on one chip."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await wait_for_svg_contains(page, "visual_auth")
        indicator = page.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        indicator.set_available(3, agent_cli_count=2)
        await wait_for_state(
            page,
            lambda: indicator.render().plain == " ⬆ 3  CLI ⬆ 2 ",
            description="mixed routine updates indicator",
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "updates_indicator_mixed_routine_120x40",
            title="ACE mixed routine updates indicator",
        )


async def test_updates_indicator_mixed_core_rebuild_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed core updates keep the core tag plus the sage CLI segment."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await wait_for_svg_contains(page, "visual_auth")
        indicator = page.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        indicator.set_available(3, core=True, agent_cli_count=2)
        await wait_for_state(
            page,
            lambda: indicator.render().plain == " ⬆ 3  core  CLI ⬆ 2 ",
            description="mixed core-rebuild updates indicator",
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "updates_indicator_mixed_core_rebuild_120x40",
            title="ACE mixed core-rebuild updates indicator",
        )


async def test_updates_indicator_with_neighbors_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed + core badge next to proc/monitor gears and the alias pill."""
    import sase.ace.tui.widgets.alias_overrides_indicator as alias_overrides_indicator

    from sase.ace.tui.widgets import ProcIndicator, MonitorIndicator
    from sase.llm_provider import TemporaryLLMOverride

    patch_startup_loaders(monkeypatch)
    alias_override = TemporaryLLMOverride(
        provider="claude",
        model="opus",
        raw_model="claude/opus",
        created_at=100.0,
        expires_at=None,
        source="test",
        effort="max",
    )
    monkeypatch.setattr(
        alias_overrides_indicator,
        "get_active_alias_overrides",
        lambda: {"medium": alias_override},
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await wait_for_svg_contains(page, "visual_auth")
        indicator = page.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        proc_indicator = page.app.query_one("#proc-indicator", ProcIndicator)
        monitor_indicator = page.app.query_one("#monitor-indicator", MonitorIndicator)
        proc_indicator.set_count(1)
        monitor_indicator.set_count(1)
        indicator.set_available(3, core=True, agent_cli_count=2)
        await wait_for_state(
            page,
            lambda: indicator.render().plain == " ⬆ 3  core  CLI ⬆ 2 ",
            description="mixed core-rebuild updates indicator with neighbors",
        )
        await wait_for_state(
            page,
            lambda: (
                proc_indicator.render().plain.strip() != ""
                and monitor_indicator.render().plain.strip() != ""
            ),
            description="proc and monitor gear chips visible",
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "updates_indicator_with_neighbors_120x40",
            title="ACE updates indicator with neighbors",
        )
