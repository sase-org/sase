"""ACE TUI PNG visual snapshots for Agents-tab neighbor interactions."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets import AgentList, KeybindingFooter
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    hood_neighbor_agents,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _neighbor_panel_reveal_agents() -> list[Agent]:
    """Single neighbor target inside a collapsed, reorderable tribe panel."""
    project_file = "/workspace/sase/visual_project.sase"
    started = datetime(2026, 7, 18, 16, 30, 0)
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-neighbor-origin",
            project_file=project_file,
            status="RUNNING",
            start_time=started,
            raw_suffix="20260718-163000-neighbor-origin",
            agent_name="visual.jump.plan",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-neighbor-target",
            project_file=project_file,
            status="DONE",
            start_time=started,
            stop_time=datetime(2026, 7, 18, 16, 36, 0),
            raw_suffix="20260718-163100-neighbor-target",
            agent_name="visual.jump.code",
            tribe="alpha",
            agent_clan="visual-workers",
            agent_clan_generation="20260718-163100",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-neighbor-unrelated",
            project_file=project_file,
            status="WAITING",
            start_time=started,
            raw_suffix="20260718-163200-neighbor-unrelated",
            agent_name="unrelated.agent",
            tribe="zeta",
        ),
    ]


def _folded_clan_neighbor_modal_agents() -> list[Agent]:
    """Two hidden hood neighbors, one also inside a collapsed tribe panel."""
    agents = _neighbor_panel_reveal_agents()
    peer = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-neighbor-peer",
        project_file="/workspace/sase/visual_project.sase",
        status="WAITING",
        start_time=datetime(2026, 7, 18, 16, 32, 0),
        raw_suffix="20260718-163200-neighbor-peer",
        agent_name="visual.jump.review",
        tribe="beta",
        agent_clan="visual-reviewers",
        agent_clan_generation="20260718-163200",
    )
    return [agents[0], agents[1], peer, agents[2]]


_LANE_STARTED = datetime(2026, 7, 18, 15, 0, 0)
_LANE_NOW = datetime(2026, 7, 18, 15, 30, 0)


def _lane_agent(
    name: str,
    *,
    index: int,
    status: str,
    **overrides: object,
) -> Agent:
    started = _LANE_STARTED + timedelta(minutes=index)
    values: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": f"visual-lane-{index:02d}",
        "project_file": "/workspace/sase/visual_project.sase",
        "status": status,
        "start_time": started,
        "run_start_time": started,
        "stop_time": None
        if status in {"RUNNING", "WAITING"}
        else started + timedelta(minutes=3),
        "raw_suffix": f"2026071815{index:02d}00-lane-{index:02d}",
        "agent_name": name,
        "llm_provider": "codex",
        "model": "gpt-5",
    }
    values.update(overrides)
    return Agent(**values)  # type: ignore[arg-type]


def _single_lane_neighbor_agents() -> list[Agent]:
    """A single-agent lane with two hood groups of neighbors."""
    rows = [
        _lane_agent("visual.lane.plan", index=0, status="RUNNING"),
        _lane_agent("visual.lane.code", index=1, status="DONE"),
        _lane_agent("visual.lane.review", index=2, status="WAITING"),
        _lane_agent("visual.lane.docs", index=3, status="DONE"),
        _lane_agent("visual.lane.verify", index=4, status="DONE"),
        _lane_agent("visual.other.bench", index=5, status="DONE"),
    ]
    _apply_status_overrides(rows)
    return sort_and_reorder(rows, [])


def _lane_neighbor_agents_with_plan(tmp_path: Path) -> list[Agent]:
    """``_single_lane_neighbor_agents`` whose lane also renders SASE CONTEXT."""
    relative_plan_path = Path("sase/repos/plans/202607/lane neighbor placement.md")
    plan_path = tmp_path / relative_plan_path
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        "---\n"
        "tier: tale\n"
        "title: Lane neighbor placement\n"
        "goal: >\n"
        "  Keep a lane's numbered neighbors reachable without scrolling past the\n"
        "  context, slow-call, and error sections.\n"
        "size: medium\n"
        "---\n"
        "# Plan\n",
        encoding="utf-8",
    )
    rows = [
        _lane_agent(
            "visual.lane.plan",
            index=0,
            status="RUNNING",
            plan_path=relative_plan_path.as_posix(),
            sdd_plan_path=relative_plan_path.as_posix(),
            plan_committed=True,
            plan_action="tale",
            workspace_dir=str(tmp_path),
        ),
        _lane_agent("visual.lane.code", index=1, status="DONE"),
        _lane_agent("visual.lane.review", index=2, status="WAITING"),
        _lane_agent("visual.lane.docs", index=3, status="DONE"),
        _lane_agent("visual.lane.verify", index=4, status="DONE"),
        _lane_agent("visual.other.bench", index=5, status="DONE"),
    ]
    _apply_status_overrides(rows)
    return sort_and_reorder(rows, [])


def _family_lane_neighbor_agents() -> list[Agent]:
    """A dotted family lane whose siblings share the enclosing ``visual`` hood."""
    root = _lane_agent(
        "visual.worker--plan",
        index=0,
        status="DONE",
        role_suffix="--plan",
        agent_family="visual.worker",
        agent_family_role="plan",
        plan_chain_root=True,
        workspace_num=4,
    )
    rows = [root]
    for index, role in enumerate(("impl", "review"), start=1):
        rows.append(
            _lane_agent(
                f"visual.worker--{role}",
                index=index,
                status="DONE",
                parent_timestamp=root.raw_suffix,
                role_suffix=f"--{role}",
                agent_family="visual.worker",
                agent_family_role=role,
                workspace_num=4 + index,
            )
        )
    rows.append(_lane_agent("visual.helper", index=3, status="RUNNING"))
    rows.append(_lane_agent("visual.notes", index=4, status="WAITING"))
    _apply_status_overrides(rows)
    return sort_and_reorder(rows, [])


def _family_container_index(page: AcePage) -> int:
    return next(
        index
        for index, agent in enumerate(page.app._agents)
        if agent.is_family_container_row
    )


async def test_agents_neighbor_badge_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=hood_neighbor_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        await wait_for_svg_contains(page, "neighbors: ")
        await wait_for_visual_idle(page)
        neighbor_index = page.app._agent_neighbor_index()
        assert neighbor_index.neighbor_count(page.app.current_idx) == 3
        assert_page_svg_contains(page, "neighbors: ")

        ace_png_visual.assert_page_png(
            page,
            "agents_neighbor_badge_120x40",
            title="ACE agents neighbor badge",
        )


async def test_agents_neighbor_jump_expands_target_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = _neighbor_panel_reveal_agents()
    target = agents[1]
    patch_startup_loaders(monkeypatch, agents=agents)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)

        await page.press("J")
        assert page.app._panel_group.focused_key == "alpha"
        await page.press("h")
        await page.wait_for(
            lambda _screen: page.app._resolve_focused_panel() is not None
        )
        await page.press("h")
        await page.wait_for(lambda _screen: "alpha" in page.app._collapsed_panel_keys)
        assert page.app._panel_group.panel_keys == [None, "zeta", "alpha"]
        await page.press("J")
        assert page.app._panel_group.focused_key is None
        assert page.app._agents[page.app.current_idx].identity == agents[0].identity

        page.app.action_start_sibling_mode()
        await page.wait_for(
            lambda _screen: "alpha" not in page.app._collapsed_panel_keys
        )
        await wait_for_visual_idle(page)

        assert page.app._panel_group.panel_keys == [None, "alpha", "zeta"]
        assert page.app._panel_group.focused_key == "alpha"
        assert page.app._agents[page.app.current_idx].identity == target.identity
        target_widget = page.app.query_one("#agent-list-panel-1", AgentList)
        assert target_widget.highlighted is not None

        ace_png_visual.assert_page_png(
            page,
            "agents_neighbor_jump_expanded_panel_120x40",
            title="ACE folded-clan neighbor jump expanded panel",
        )


async def test_agent_neighbor_modal_folded_clan_and_tribe_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = _folded_clan_neighbor_modal_agents()
    patch_startup_loaders(monkeypatch, agents=agents)

    async with AcePage(query='"visual"', patches=patches(), size=(70, 32)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")

        await page.press("J")
        assert page.app._panel_group.focused_key == "alpha"
        await page.press("h")
        await page.wait_for(
            lambda _screen: page.app._resolve_focused_panel() is not None
        )
        await page.press("h")
        await page.wait_for(lambda _screen: "alpha" in page.app._collapsed_panel_keys)
        await page.press("J")
        assert page.app._panel_group.focused_key is None

        page.app.action_start_sibling_mode()
        await page.expect_modal("AgentNeighborModal")
        await wait_for_svg_contains(page, "visual.jump.code")
        await wait_for_visual_idle(page)

        modal = page.app.screen_stack[-1]
        choices = vars(modal)["_choices"]
        assert [choice.agent_name for choice in choices] == [
            "visual.jump.review",
            "visual.jump.code",
        ]
        assert [choice.panel_label for choice in choices] == ["@beta", "@alpha"]
        assert [choice.global_idx for choice in choices] == [None, None]

        ace_png_visual.assert_page_png(
            page,
            "agent_neighbor_folded_clan_modal_70x32",
            title="ACE folded-clan neighbor chooser",
        )


async def test_agent_neighbor_modal_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=hood_neighbor_agents())

    async with AcePage(query='"visual"', patches=patches(), size=(60, 30)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        page.app.action_start_sibling_mode()
        await page.expect_modal("AgentNeighborModal")
        await wait_for_svg_contains(page, "Neighbors of visual.code.plan")
        await wait_for_visual_idle(page)
        modal = page.app.screen_stack[-1]
        assert modal.__class__.__name__ == "AgentNeighborModal"
        choices = vars(modal)["_choices"]
        assert [choice.global_idx for choice in choices] == [1, 2, 3]
        assert [choice.hood for choice in choices] == [
            "visual.code",
            "visual.code",
            "visual",
        ]
        assert_page_svg_contains(page, "Neighbors of visual.code.plan")
        assert_page_svg_contains(page, "visual.code.implementation")

        ace_png_visual.assert_page_png(
            page,
            "agent_neighbor_modal_60x30",
            title="ACE agent neighbor modal narrow",
        )


async def test_agent_neighbor_modal_dismissed_descendant_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-parent",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 23, 13, 0, 0),
        raw_suffix="20260523-130000-parent",
        agent_name="visual.root",
        tribe="api",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-child",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 5, 23, 13, 8, 0),
        stop_time=datetime(2026, 5, 23, 13, 12, 30),
        raw_suffix="20260523-130800-child",
        agent_name="visual.root.visible",
        tribe="api",
    )
    dismissed = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-dismissed",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 5, 23, 13, 16, 0),
        stop_time=datetime(2026, 5, 23, 13, 17, 5),
        raw_suffix="20260523-131600-dismissed",
        agent_name="visual.root.dismissed",
        tribe="api",
    )
    patch_startup_loaders(monkeypatch, agents=[parent, child])

    async with AcePage(query='"visual"', patches=patches(), size=(60, 30)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 2)
        page.app._dismissed_agent_objects = [dismissed]
        page.app._dismissed_agents = {dismissed.identity}
        page.app._dismiss_revive_epoch += 1
        # Refresh the uncovered base screen before pushing the modal. Textual
        # does not repaint background screens after they are covered, so an
        # info-panel update performed after the push leaves the header badge
        # at its pre-dismissal count.
        page.app._update_agents_info_panel()
        page.app._refresh_agent_footer_bindings_only()
        info_panel = page.app.query_one("#agent-info-panel")
        await page.wait_for(
            lambda _state: getattr(info_panel, "_neighbor_count", 0) == 2
        )
        await wait_for_visual_idle(page)
        page.app.action_start_sibling_mode()
        await page.expect_modal("AgentNeighborModal")
        # The direct private-state mutation above bypasses the normal action
        # path that refreshes the footer. Repaint it explicitly, then wait on
        # footer state specifically: the modal's "2 descendants" text can
        # otherwise satisfy a broad SVG poll while the footer is still stale.
        footer = page.app.query_one("#keybinding-footer", KeybindingFooter)
        await page.wait_for(
            lambda _screen: (
                footer._last_layout_inputs is not None
                and any(
                    label == "neighbors (2)"
                    for _key, label in footer._last_layout_inputs[0]
                )
            )
        )
        # ``_last_layout_inputs`` is updated before Textual necessarily paints
        # the footer or the separate header badge. Prove both two-neighbor
        # surfaces reached the exported frame before the final convergence
        # barrier.
        await wait_for_svg_contains(page, "neighbors (2)")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "Descendants")
        assert_page_svg_contains(page, "visual.root.dismissed")
        assert_page_svg_contains(page, "dismissed")

        ace_png_visual.assert_page_png(
            page,
            "agent_neighbor_modal_descendants_dismissed_60x30",
            title="ACE agent neighbor modal dismissed descendant",
        )


async def test_agents_lane_neighbors_section_fold_levels_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, _LANE_NOW)
    patch_startup_loaders(monkeypatch, agents=_single_lane_neighbor_agents())

    async with AcePage(query='"visual"', patches=patches(), size=(160, 50)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 6)
        lane = next(
            agent
            for agent in page.app._agents
            if agent.agent_name == "visual.lane.plan"
        )
        lane_identity = lane.identity
        page.app.current_idx = page.app._agents.index(lane)
        await wait_for_svg_contains(page, "NEIGHBORS")
        await wait_for_visual_idle(page)

        # A startup refresh may replace and reorder the Agent instances while
        # preserving their stable identities. Re-resolve the row after the
        # startup frame settles so the numeric selection cannot drift onto a
        # different lane under contention.
        lane = next(
            agent for agent in page.app._agents if agent.identity == lane_identity
        )
        page.app.current_idx = page.app._agents.index(lane)
        await wait_for_visual_idle(page)

        assert page.app._agents[page.app.current_idx].identity == lane_identity
        jump_map = page.app._member_jump_maps[lane.identity]
        assert [target.number for target in jump_map.targets] == ["0", "1", "2"]
        assert {target.role for target in jump_map.targets} == {"neighbor"}
        assert_page_svg_contains(page, "NEIGHBORS")
        assert_page_svg_contains(page, "visual.lane hood")
        assert_page_svg_contains(page, "more neighbors")

        ace_png_visual.assert_page_png(
            page,
            "agents_lane_neighbors_section_first_level_160x50",
            title="ACE lane neighbors section first fold level",
        )

        await page.press("z", "z")
        assert page.app.panel_fold_level is FoldLevel.EXPANDED
        await wait_for_svg_contains(page, "visual hood")
        await wait_for_visual_idle(page)

        expanded_map = page.app._member_jump_maps[lane.identity]
        assert [target.number for target in expanded_map.targets] == list("01234")
        assert_page_svg_contains(page, ".bench")

        ace_png_visual.assert_page_png(
            page,
            "agents_lane_neighbors_section_expanded_160x50",
            title="ACE lane neighbors section expanded",
        )

        await page.press("4")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].agent_name
                == "visual.other.bench"
            )
        )


async def test_agents_lane_neighbors_above_sase_context_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, _LANE_NOW)
    patch_startup_loaders(monkeypatch, agents=_lane_neighbor_agents_with_plan(tmp_path))

    async with AcePage(query='"visual"', patches=patches(), size=(160, 50)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 6)
        lane = next(
            agent
            for agent in page.app._agents
            if agent.agent_name == "visual.lane.plan"
        )
        page.app.current_idx = page.app._agents.index(lane)
        await wait_for_svg_contains(page, "NEIGHBORS")
        await wait_for_svg_contains(page, "SASE CONTEXT")
        await wait_for_visual_idle(page)

        assert page.app._agents[page.app.current_idx] is lane
        assert_page_svg_contains(page, "NEIGHBORS")
        assert_page_svg_contains(page, "SASE CONTEXT")
        svg_plain = page.export_svg(title="ACE lane neighbors above context").replace(
            "&#160;", " "
        )
        assert svg_plain.index("NEIGHBORS") < svg_plain.index("SASE CONTEXT")

        ace_png_visual.assert_page_png(
            page,
            "agents_lane_neighbors_above_context_160x50",
            title="ACE lane neighbors above SASE CONTEXT",
        )


async def test_agents_family_lane_neighbors_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, _LANE_NOW)
    patch_startup_loaders(monkeypatch, agents=_family_lane_neighbor_agents())

    async with AcePage(query='"visual"', patches=patches(), size=(160, 50)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await wait_for_visual_idle(page)

        page.app.current_idx = _family_container_index(page)
        await wait_for_svg_contains(page, "FAMILY MEMBERS")
        # Expanding inserts member rows above the container, so the selection
        # has to be re-resolved before the lane panel is captured.
        await page.press("l")
        page.app.current_idx = _family_container_index(page)
        await wait_for_svg_contains(page, "also listed under FAMILY MEMBERS")
        await wait_for_visual_idle(page)

        lane = page.app._agents[page.app.current_idx]
        assert lane.is_family_container_row is True
        jump_map = page.app._member_jump_maps[lane.identity]
        assert [target.role for target in jump_map.targets] == [
            "member",
            "member",
            "member",
            "neighbor",
            "neighbor",
        ]
        assert [target.number for target in jump_map.targets] == list("01234")
        assert_page_svg_contains(page, "NEIGHBORS")
        assert_page_svg_contains(page, "also listed under FAMILY MEMBERS")

        ace_png_visual.assert_page_png(
            page,
            "agents_family_lane_neighbors_160x50",
            title="ACE family lane neighbors section",
        )
