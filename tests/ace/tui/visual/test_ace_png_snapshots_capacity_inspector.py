"""PNG snapshots for the keyboard-first capacity inspector."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.modals.capacity_inspector_modal import CapacityInspectorModal
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    agents,
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._capacity_inspector_fixtures import (
    blocked_report,
    busy_report,
    over_limit_report,
    screenshot_report,
)
from tests.ace.tui.visual._provider_usage_indicator_fixtures import quiet_top_bar
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def _capture_inspector(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    *,
    report: Any,
    name: str,
    size: tuple[int, int],
    running_nodes: int | None = 6,
    highlighted_id: str | None = None,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 12, 12, 3, 0))
    quiet_top_bar(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=size,
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")

        def clock() -> float:
            return float(report.computed_at) + 3

        page.app.push_screen(
            CapacityInspectorModal(
                report,
                running_nodes=running_nodes,
                clock=clock,
            )
        )
        await page.expect_modal("CapacityInspectorModal")
        if highlighted_id is not None:
            modal = page.app.screen_stack[-1]
            options = modal.query_one("#capacity-inspector-options", OptionList)
            index = next(
                i
                for i, option in enumerate(options.options)
                if option.id == highlighted_id
            )
            options.highlighted = index
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            name,
            title=f"ACE capacity inspector {name}",
        )


async def test_capacity_inspector_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _capture_inspector(
        ace_png_visual,
        monkeypatch,
        report=screenshot_report(),
        name="capacity_inspector_120x40",
        size=(120, 40),
    )


async def test_capacity_inspector_busy_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _capture_inspector(
        ace_png_visual,
        monkeypatch,
        report=busy_report(),
        name="capacity_inspector_busy_120x40",
        size=(120, 40),
        running_nodes=9,
        highlighted_id="agent:/holder-heavy",
    )


async def test_capacity_inspector_over_limit_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _capture_inspector(
        ace_png_visual,
        monkeypatch,
        report=over_limit_report(),
        name="capacity_inspector_over_limit_120x40",
        size=(120, 40),
    )


async def test_capacity_inspector_blocked_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _capture_inspector(
        ace_png_visual,
        monkeypatch,
        report=blocked_report(),
        name="capacity_inspector_blocked_120x40",
        size=(120, 40),
    )


async def test_capacity_inspector_busy_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _capture_inspector(
        ace_png_visual,
        monkeypatch,
        report=busy_report(),
        name="capacity_inspector_busy_80x32",
        size=(80, 32),
        running_nodes=9,
        highlighted_id="agent:/holder-heavy",
    )
