"""ACE PNG regression for group-scoped uppercase-H lane collapse."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter
from tests.ace.tui.visual._ace_agents_png_snapshot_fixtures import (
    group_lane_collapse_precedence_agents,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_group_lane_collapse_precedes_status_banner_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 22, 7, 15, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=group_lane_collapse_precedence_agents(),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.press("o", "o")
        assert page.app._grouping_mode is GroupingMode.BY_STATUS

        roots = {
            agent.agent_name: agent
            for agent in page.app._agents_with_children
            if agent.agent_name in {"hu", "ht", "hs"} and not agent.is_child_row
        }
        hu = roots["hu"]
        ht_key = agent_fold_key(roots["ht"])
        hs_key = agent_fold_key(roots["hs"])
        assert ht_key is not None and hs_key is not None
        page.app._fold_manager.expand(ht_key)
        page.app._fold_manager.expand(hs_key)
        page.app._fold_manager.expand(hs_key)
        page.app._refilter_agents(refresh_content_index=False)
        page.app.current_idx = page.app._agents.index(hu)
        page.app._current_group_key = None
        page.app._refresh_agents_display(list_changed=True)
        await page.expect_state("agent_count", 5)
        await wait_for_visual_idle(page)

        footer = page.app.query_one("#keybinding-footer", KeybindingFooter)
        assert footer._last_layout_inputs is not None
        assert ("H", "collapse lanes") in footer._last_layout_inputs[0]

        await page.press("H")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        assert page.app._agents[page.app.current_idx] is hu
        assert page.app._fold_manager.get(ht_key) is FoldLevel.COLLAPSED
        assert page.app._fold_manager.get(hs_key) is FoldLevel.COLLAPSED
        running_registry = page.app._group_fold_registry.for_panel(None)
        assert not running_registry.is_collapsed(("Running",))
        assert footer._last_layout_inputs is not None
        assert ("H", "collapse group") in footer._last_layout_inputs[0]
        ace_png_visual.assert_page_png(
            page,
            "agents_group_lane_collapse_precedence_120x40",
            title="ACE group-wide lane collapse before status banner",
        )

        await page.press("H")
        await wait_for_visual_idle(page)
        assert running_registry.is_collapsed(("Running",))
