"""ACE PNG snapshots for family panel gate shell metadata and output."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from textual.containers import VerticalScroll

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent_family_members import concrete_family_shell_rows
from tests.ace.tui.visual._ace_agents_png_snapshot_family_panel_fixtures import (
    _gate_family_agents,
    _selected_gate_agent,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_family_gate_shells_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 8, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=_gate_family_agents(tmp_path),
    )

    async with AcePage(
        query='"visual-family-root"',
        size=(120, 40),
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        container = page.app._agents[page.app.current_idx]
        assert container.is_family_container_row is True
        shells = concrete_family_shell_rows(container)
        assert [shell.is_gate for shell in shells] == [
            False,
            False,
            True,
            True,
            True,
            True,
        ]
        assert [shell.gate_state for shell in shells if shell.is_gate] == [
            "pending",
            "settling",
            "answered",
            "failed",
        ]
        assert_page_svg_contains(page, "Shells:")
        assert_page_svg_contains(page, "pending")
        assert_page_svg_contains(page, "settling")
        assert_page_svg_contains(page, "answered")
        assert_page_svg_contains(page, "failed")
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_shells_gate_120x40",
            title="ACE family panel shell metadata with gate rows",
        )


async def test_family_gate_shells_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 8, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=_gate_family_agents(tmp_path),
    )

    async with AcePage(
        query='"visual-family-root"',
        size=(90, 40),
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "visual-family")
        assert_page_svg_contains(page, "⋔")
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_shells_gate_90x40",
            title="ACE family panel gate shells narrow",
        )


async def test_selected_gate_shell_output_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 8, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=[_selected_gate_agent(tmp_path)],
    )

    async with AcePage(
        query='"visual-standalone-gate-run"',
        size=(120, 40),
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        selected = page.app._agents[page.app.current_idx]
        assert selected.is_gate is True
        assert selected.gate_state == "settling"
        assert_page_svg_contains(page, "Run deployment preview")
        scroll = page.query_one_widget("#agent-prompt-scroll", VerticalScroll)
        scroll.scroll_to(y=16, animate=False, immediate=True)
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "gate output line 01")
        assert_page_svg_contains(page, "truncated")
        ace_png_visual.assert_page_png(
            page,
            "agents_family_gate_output_120x40",
            title="ACE selected gate shell with long output",
        )
