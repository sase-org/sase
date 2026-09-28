"""ACE PNG coverage for the Agents o/O layout ladder (sase-1bc.8).

Merged and All-tabs views with several tabs, and the grouping modal in
its two-segment (R6) and three-segment modes — with the ``agent_tabs``
flag on.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.feature_flags import override_flags
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture
from tests.ace.tui.visual.test_ace_png_snapshots_agent_tab_strip import (
    _agent,
    _install_tab_view,
    _open_agents,
)

pytestmark = pytest.mark.visual


async def test_agents_panel_layout_merged_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _agent("one"),
            _agent("two"),
            _agent("three", tab="sase"),
        ],
    )
    _install_tab_view(monkeypatch)
    with override_flags(agent_tabs=True):
        async with AcePage(query='"visual"', patches=patches()) as page:
            await _open_agents(page)
            await page.press("o", "o")
            await page.expect_no_modal()
            await wait_for_visual_idle(page)
            await wait_for_svg_contains(page, "main")
            ace_png_visual.assert_page_png(
                page,
                "agents_panel_layout_merged_120x40",
                title="ACE agents merged panel on the default tab",
            )


async def test_agents_panel_layout_all_tabs_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _agent("one"),
            _agent("two"),
            _agent("three", tab="sase"),
        ],
    )
    _install_tab_view(monkeypatch)
    with override_flags(agent_tabs=True):
        async with AcePage(query='"visual"', patches=patches()) as page:
            await _open_agents(page)
            await page.press("o", "o")
            await page.expect_no_modal()
            await page.press("o", "o")
            await page.expect_no_modal()
            await wait_for_visual_idle(page)
            await wait_for_svg_contains(page, "every tab")
            await wait_for_svg_contains(page, "[sase]")
            ace_png_visual.assert_page_png(
                page,
                "agents_panel_layout_all_tabs_120x40",
                title="ACE agents all-tabs panel with row tab chips",
            )


async def test_agents_panel_layout_modal_two_segment_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_agent("one"), _agent("two")])
    _install_tab_view(monkeypatch)
    with override_flags(agent_tabs=True):
        async with AcePage(query='"visual"', patches=patches()) as page:
            await _open_agents(page)
            await page.press("o")
            await page.expect_modal("AgentGroupingModal")
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "Split by tribe")
            # R6: with one tab the All-tabs segment is not offered.
            assert "All tabs" not in page.screen
            ace_png_visual.assert_page_png(
                page,
                "agents_panel_layout_modal_two_segment_120x40",
                title="ACE agents grouping modal with two layout segments",
            )


async def test_agents_panel_layout_modal_three_segment_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _agent("one"),
            _agent("two", tab="sase"),
        ],
    )
    _install_tab_view(monkeypatch)
    with override_flags(agent_tabs=True):
        async with AcePage(query='"visual"', patches=patches()) as page:
            await _open_agents(page)
            await page.press("o")
            await page.expect_modal("AgentGroupingModal")
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "All tabs")
            ace_png_visual.assert_page_png(
                page,
                "agents_panel_layout_modal_three_segment_120x40",
                title="ACE agents grouping modal with three layout segments",
            )
