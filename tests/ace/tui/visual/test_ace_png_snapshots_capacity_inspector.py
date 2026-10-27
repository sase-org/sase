"""PNG snapshot coverage for the keyboard-first capacity inspector."""

from __future__ import annotations

from datetime import datetime

import pytest

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
from tests.ace.tui.visual._provider_usage_indicator_fixtures import quiet_top_bar
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture
from tests.test_machine_capacity_report import (
    _report_from_records,
    _screenshot_records,
)

pytestmark = pytest.mark.visual


async def test_capacity_inspector_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 12, 12, 3, 0))
    quiet_top_bar(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(120, 40),
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")

        report = _report_from_records(_screenshot_records())
        page.app._machine_capacity_report = report
        page.app.push_screen(CapacityInspectorModal(report, running_nodes=6))
        await page.expect_modal("CapacityInspectorModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "capacity_inspector_120x40",
            title="ACE machine capacity inspector",
        )
