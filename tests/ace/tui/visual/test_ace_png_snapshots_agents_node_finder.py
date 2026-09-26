"""sase's TUI PNG visual snapshots for the Agents-tab Node Finder modal."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._node_finder_snapshot import (
    build_node_finder_snapshot,
)
from sase.ace.tui.modals.node_finder_modal import NodeFinderModal
from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.modals.node_finder_preview_loader import NodeFinderPreviewPayload
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.node_finder import (
    NodeFinderReason,
    node_finder_action_text,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_clan_fixtures import (
    clan_tree_agents,
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

_VISUAL_NOW = datetime(2026, 7, 17, 12, 0, 0)


def _stub_loader(agent: Any) -> NodeFinderPreviewPayload:
    """Deterministic Tier 1 payload so goldens never shift on disk state."""
    return NodeFinderPreviewPayload(
        identity=agent.identity,
        source_name=agent.agent_name or "stub",
        prompt="Stub prompt head: the finder preview keeps this fixed.",
        reply="Stub reply tail: the finder preview keeps this fixed.",
        reply_omitted_lines=0,
        reply_omitted_chars=0,
        token=(("stub", 1, 1),),
    )


async def _open_finder(page: AcePage) -> NodeFinderModal:
    snapshot = build_node_finder_snapshot(page.app)
    modal = NodeFinderModal(snapshot, has_back=True, preview_loader=_stub_loader)
    page.app.push_screen(modal)
    await page.expect_modal("NodeFinderModal")
    await wait_for_visual_idle(page)
    return modal


def _bulk_agents(count: int = 70) -> list[Agent]:
    """Deterministic clan big enough for two-character hint prefixes."""
    started = datetime(2026, 7, 17, 9, 0, 0)
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-bulk-clan",
            project_file="/workspace/sase/visual_project.sase",
            status="RUNNING",
            start_time=started,
            raw_suffix=f"20260717090000-bulk-{index:03d}",
            agent_name=f"bulk.node.{index:02d}",
            agent_clan="bulk",
            agent_clan_generation="20260717090000",
            tribe=None,
        )
        for index in range(count)
    ]


def _clan_agents_with_i_hidden_row() -> list[Agent]:
    """Return the clan fixture with one running ``%hide``-style member."""
    agents = clan_tree_agents()
    hidden = next(agent for agent in agents if agent.agent_name == "research.waiting")
    hidden.hidden = True
    return agents


async def test_node_finder_hints_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, _VISUAL_NOW)
    patch_startup_loaders(monkeypatch, agents=clan_tree_agents())

    async with AcePage(query='"visual"', patches=patches(), size=(160, 48)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await wait_for_visual_idle(page)

        modal = await _open_finder(page)
        assert modal._search_mode is False
        assert_page_svg_contains(page, "Jump to Node")

        ace_png_visual.assert_page_png(
            page,
            "node_finder_hints_160x48",
            title="ACE Node Finder hints",
        )


async def test_node_finder_search_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, _VISUAL_NOW)
    patch_startup_loaders(monkeypatch, agents=clan_tree_agents())

    async with AcePage(query='"visual"', patches=patches(), size=(160, 48)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await wait_for_visual_idle(page)

        modal = await _open_finder(page)
        await page.press("tab")
        for key in ("f", "a", "m"):
            await page.press(key)
        await wait_for_visual_idle(page)
        await page.wait_for(
            lambda _screen: (
                modal._view.query == "fam" and modal._pending_refilter_query is None
            )
        )
        assert modal._search_mode is True

        ace_png_visual.assert_page_png(
            page,
            "node_finder_search_160x48",
            title="ACE Node Finder search",
        )


async def test_node_finder_pending_prefix_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, _VISUAL_NOW)
    patch_startup_loaders(monkeypatch, agents=_bulk_agents())

    async with AcePage(query='"visual"', patches=patches(), size=(160, 48)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")

        # Expand the bulk clan and park selection on a member row: the clan
        # container's detail worker never settles over 70 members, while a
        # member detail is cheap. The finder snapshot is unaffected.
        container = next(
            agent for agent in page.app._agents_with_children if agent.is_clan_container
        )
        clan_key = agent_fold_key(container)
        assert clan_key is not None
        page.app._fold_manager.expand(clan_key)
        page.app._fold_manager.expand(clan_key)
        page.app._refilter_agents()
        await page.pause()
        await page.press("j")
        await wait_for_visual_idle(page)

        modal = await _open_finder(page)
        two_key = next(hint for hint in modal._view.hint_to_identity if len(hint) == 2)
        await page.press(two_key[0])
        await wait_for_visual_idle(page)
        assert modal._pending == two_key[0]

        ace_png_visual.assert_page_png(
            page,
            "node_finder_pending_prefix_160x48",
            title="ACE Node Finder pending prefix",
        )


async def test_node_finder_query_hidden_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, _VISUAL_NOW)
    patch_startup_loaders(monkeypatch, agents=clan_tree_agents())

    async with AcePage(query='"visual"', patches=patches(), size=(160, 48)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")

        # status:FAILED matches no fixture row, so every list row carries ⊘
        # (plus ▸ under the collapsed clan) and the preview shows the
        # clears-query action line.
        page.app._record_explicit_agents_query_commit("status:FAILED")
        page.app._refilter_agents()
        await page.pause()
        await wait_for_visual_idle(page)

        modal = await _open_finder(page)
        assert modal._snapshot.query == "status:FAILED"
        assert modal._snapshot.query_hidden_count == modal._snapshot.node_count
        option_list = modal.query_one("#node-finder-list", OptionList)
        row = modal._view.rows[option_list.highlighted or 0]
        assert NodeFinderReason.QUERY in row.reasons
        assert "clears the Agents query" in node_finder_action_text(
            row, modal._view.query
        )
        assert_page_svg_contains(page, "⊘")

        ace_png_visual.assert_page_png(
            page,
            "node_finder_query_hidden_160x48",
            title="ACE Node Finder query hidden",
        )


async def test_node_finder_i_hidden_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, _VISUAL_NOW)
    patch_startup_loaders(monkeypatch, agents=_clan_agents_with_i_hidden_row())

    async with AcePage(query='"visual"', patches=patches(), size=(160, 48)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")

        modal = await _open_finder(page)
        hidden_row = next(
            row
            for row in modal._snapshot.rows
            if NodeFinderReason.NON_RUN in row.reasons
        )
        assert hidden_row.name == "research.waiting"
        assert modal._snapshot.hidden_by_i_count == 1
        assert "shows agents hidden by I" in node_finder_action_text(
            hidden_row, modal._view.query
        )
        assert_page_svg_contains(page, "◌")

        ace_png_visual.assert_page_png(
            page,
            "node_finder_hidden_by_i_160x48",
            title="ACE Node Finder hidden by I",
        )


async def test_node_finder_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, _VISUAL_NOW)
    patch_startup_loaders(monkeypatch, agents=clan_tree_agents())

    async with AcePage(query='"visual"', patches=patches(), size=(100, 40)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await wait_for_visual_idle(page)

        await _open_finder(page)
        assert_page_svg_contains(page, "Jump to Node")

        ace_png_visual.assert_page_png(
            page,
            "node_finder_narrow_100x40",
            title="ACE Node Finder narrow",
        )


async def test_node_finder_no_results_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, _VISUAL_NOW)
    patch_startup_loaders(monkeypatch, agents=clan_tree_agents())

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await wait_for_visual_idle(page)

        await _open_finder(page)
        await page.press("tab")
        for key in ("z", "z", "z", "q"):
            await page.press(key)
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "No nodes match")

        ace_png_visual.assert_page_png(
            page,
            "node_finder_no_results_120x40",
            title="ACE Node Finder no results",
        )
