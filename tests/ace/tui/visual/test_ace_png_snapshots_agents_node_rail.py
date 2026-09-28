"""ACE PNG visual snapshots for the Agents-tab node rail (rail-wiring)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.widgets import AgentDetail, AgentList
from sase.ace.tui.widgets._agent_list_render_rail import NODE_RAIL_WIDTH
from sase.gate_turn.state import gate_member_status_bucket
from sase.monitor_state import monitor_state_bucket
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_png_snapshot_waits import wait_for_state
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_STARTED = datetime(2026, 9, 27, 10, 0, 0)
_PROJECT = "/workspace/sase/rail_project.sase"
_OTHER_PROJECT = "/workspace/sase/rail_other.sase"


def _agent(
    name: str,
    status: str,
    minute: int,
    *,
    tribe: str = "sase",
    project: str = _PROJECT,
    **fields,
) -> Agent:
    started = _STARTED + timedelta(minutes=minute)
    return Agent(
        agent_type=fields.pop("agent_type", AgentType.RUNNING),
        cl_name=f"rail-{name}",
        project_file=project,
        status=status,
        start_time=started,
        run_start_time=started,
        raw_suffix=f"2026092710{minute:02d}00-rail-{name}",
        agent_name=fields.pop("agent_name", f"rail.{name}"),
        tribe=tribe,
        llm_provider="codex",
        model="gpt-5",
        **fields,
    )


def _by_project_agents(tmp_path: Path) -> list[Agent]:
    """Mixed rows: needs-you, failed unread, clan, done, monitor, gate."""
    generation = "20260927101000"
    clan_root = _agent(
        "clan",
        "RUNNING",
        10,
        agent_session="rail.clan",
        agent_session_role="root",
        role_suffix="--root",
        agent_name="rail.clan--root",
        agent_clan="rail",
        agent_clan_generation=generation,
    )
    clan_code = _agent(
        "clan-code",
        "RUNNING",
        12,
        parent_timestamp=clan_root.raw_suffix,
        role_suffix="--code",
        agent_name="rail.clan--code",
        agent_session="rail.clan",
        agent_session_role="code",
        agent_clan="rail",
        agent_clan_generation=generation,
    )
    clan_grandchild = _agent(
        "clan-step",
        "DONE",
        14,
        parent_timestamp=clan_code.raw_suffix,
        role_suffix="--step",
        agent_name="rail.clan--step",
        agent_session="rail.clan",
        agent_session_role="step",
        agent_clan="rail",
        agent_clan_generation=generation,
    )
    session_root = _agent(
        "family",
        "DONE",
        20,
        agent_session="rail.family",
        agent_session_role="root",
        role_suffix="--plan",
        agent_name="rail.family--plan",
    )
    session_code = _agent(
        "family-code",
        "DONE",
        22,
        parent_timestamp=session_root.raw_suffix,
        agent_name="rail.family--code",
        agent_session="rail.family",
        agent_session_role="code",
    )
    monitor = _agent(
        "family-mon",
        "MONITORED",
        24,
        status_bucket=monitor_state_bucket("completed"),
        parent_timestamp=session_code.raw_suffix,
        agent_name="rail.family--mon",
        agent_session="rail.family",
        agent_session_role="monitor",
        monitor_id="railmon12345678",
        monitor_state="completed",
        monitor_start_status="MONITORING",
        monitor_stop_status="MONITORED",
        monitor_label="just check",
        monitor_command="just check",
        monitor_cwd="/workspace/sase",
    )
    gate = _agent(
        "family-gate",
        "WAITING",
        26,
        status_bucket=gate_member_status_bucket("pending", "WAITING"),
        parent_timestamp=session_code.raw_suffix,
        agent_name="rail.family--gate",
        agent_session="rail.family",
        agent_session_role="gate",
        gate_id="rail-gate-visual-1234567890",
        gate_kind="approval",
        gate_state="pending",
        gate_start_status="WAITING",
        gate_stop_status="ANSWERED",
        gate_accent="#0BCDEC",
        gate_label="Approve rail handoff",
    )
    return [
        _agent("asking", "QUESTION", 0),
        _agent("failed", "FAILED", 1),
        clan_root,
        clan_code,
        clan_grandchild,
        _agent("running", "RUNNING", 4),
        _agent("done-read", "DONE", 5),
        _agent("done-unread", "DONE", 6),
        session_root,
        session_code,
        monitor,
        gate,
        _agent("other-one", "RUNNING", 30, project=_OTHER_PROJECT),
        _agent("other-two", "DONE", 31, project=_OTHER_PROJECT),
        _agent("epic-scout", "RUNNING", 40, tribe="epic"),
    ]


async def _goto_agents(page: AcePage, count: int) -> AgentDetail:
    await wait_for_startup(page)
    await page.press("shift+tab")
    await page.expect_state("tab", "agents")
    await page.expect_state("agent_count", count)
    await wait_for_visual_idle(page)
    return page.app.query_one("#agent-detail-panel", AgentDetail)


async def _enter_rail(page: AcePage, detail: AgentDetail) -> None:
    # The first toggle after a fold plus programmatic refreshes is
    # intermittently swallowed before any deck state changes (a follow-up is
    # filed on the phase bead); retry the keypress a bounded number of times.
    # Post-conditions below still prove the railed product state strictly.
    for _ in range(3):
        await page.press("ctrl+s")
        try:
            await wait_for_state(
                page,
                lambda: detail.is_node_rail is True,
                description="Node panel is railed",
            )
            break
        except AssertionError:
            continue
    assert detail.is_node_rail is True
    await wait_for_visual_idle(page)
    container = page.app.query_one("#agent-list-container")
    assert container.region.width == NODE_RAIL_WIDTH


def _mark_unread(page: AcePage, agent_name: str) -> None:
    target = next(agent for agent in page.app._agents if agent.agent_name == agent_name)
    page.app._unread_completed_agent_ids.add(target.identity)
    page.app._manual_unread_agent_ids.add(target.identity)


async def _expand_clan_and_session(page: AcePage) -> None:
    """Expand the clan container and session root so children render."""
    container = next(
        agent for agent in page.app._agents_with_children if agent.is_clan_container
    )
    clan_key = agent_fold_key(container)
    assert clan_key is not None
    page.app._fold_manager.expand(clan_key)
    page.app._fold_manager.expand(clan_key)
    root = next(
        agent
        for agent in page.app._agents_with_children
        if agent.agent_name == "rail.family--plan"
    )
    root_key = agent_fold_key(root)
    assert root_key is not None
    page.app._fold_manager.expand(root_key)
    page.app._fold_manager.expand(root_key)
    page.app._refilter_agents(refresh_content_index=False)
    page.app._refresh_agents_display(list_changed=True)
    await wait_for_visual_idle(page)


def _scroll_sase_to_agent(page: AcePage, agent_name: str) -> None:
    """Scroll the sase rail panel so *agent_name*'s row is in view."""
    sase = next(
        widget
        for widget in page.app.query_one("#agent-list-container")
        .query(AgentList)
        .results(AgentList)
        if widget.id == "agent-list-panel-sase"
    )
    row = next(
        index
        for index, (local_idx, _attempt) in enumerate(sase._row_entries)
        if local_idx >= 0 and sase._agents[local_idx].agent_name == agent_name
    )
    sase.scroll_to(y=max(0, row - 2))


async def test_agents_node_rail_by_project_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 9, 27, 10, 45, 0))
    patch_startup_loaders(monkeypatch, agents=_by_project_agents(tmp_path))
    async with AcePage(query='"visual"', patches=patches()) as page:
        detail = await _goto_agents(page, 10)
        _mark_unread(page, "rail.failed")
        _mark_unread(page, "rail.done-unread")
        await _expand_clan_and_session(page)
        # Fold the second project lane so the rail shows a folded banner.
        other_idx = next(
            i
            for i, agent in enumerate(page.app._agents)
            if agent.agent_name == "rail.other-one"
        )
        page.app.current_idx = other_idx
        page.app._refresh_agents_display(list_changed=True)
        await wait_for_visual_idle(page)
        await page.press("H")
        await wait_for_state(
            page,
            lambda: len(page.app._group_fold_registry.collapsed) == 1,
            description="Other project lane is folded",
        )
        await wait_for_visual_idle(page)
        await _enter_rail(page, detail)
        # Bring the monitor and gate rows into view with an overflow count.
        _scroll_sase_to_agent(page, "rail.family--gate")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_node_rail_by_project_120x40",
            title="ACE agents node rail by project",
        )


async def test_agents_node_rail_by_status_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 9, 27, 10, 45, 0))
    patch_startup_loaders(monkeypatch, agents=_by_project_agents(tmp_path))
    async with AcePage(query='"visual"', patches=patches()) as page:
        detail = await _goto_agents(page, 10)
        _mark_unread(page, "rail.failed")
        _mark_unread(page, "rail.done-unread")
        await _expand_clan_and_session(page)
        await page.press("o", "s")
        await wait_for_visual_idle(page)
        assert page.app._grouping_mode is GroupingMode.BY_STATUS
        await _enter_rail(page, detail)
        ace_png_visual.assert_page_png(
            page,
            "agents_node_rail_by_status_120x40",
            title="ACE agents node rail by status",
        )


async def test_agents_node_rail_jump_hints_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 9, 27, 10, 45, 0))
    patch_startup_loaders(monkeypatch, agents=_by_project_agents(tmp_path))
    async with AcePage(query='"visual"', patches=patches()) as page:
        detail = await _goto_agents(page, 10)
        await _enter_rail(page, detail)
        await page.press("apostrophe")
        await wait_for_visual_idle(page)
        assert page.app._entry_jump_mode_active is True
        ace_png_visual.assert_page_png(
            page,
            "agents_node_rail_jump_hints_120x40",
            title="ACE agents node rail jump hints",
        )


async def test_agents_node_rail_collapsed_tribes_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 9, 27, 10, 45, 0))
    patch_startup_loaders(monkeypatch, agents=_by_project_agents(tmp_path))
    async with AcePage(query='"visual"', patches=patches()) as page:
        detail = await _goto_agents(page, 10)
        await _enter_rail(page, detail)
        # Collapse the focused tribe, then hold whole-panel focus on it.
        await page.press("h")
        await page.press("h")
        await wait_for_visual_idle(page)
        assert len(page.app._collapsed_panel_keys) == 1
        widgets = list(
            page.app.query_one("#agent-list-container")
            .query(AgentList)
            .results(AgentList)
        )
        titles = [str(widget.border_title) for widget in widgets]
        assert any("?" in title for title in titles)
        ace_png_visual.assert_page_png(
            page,
            "agents_node_rail_collapsed_tribes_120x40",
            title="ACE agents node rail collapsed tribes",
        )


async def test_agents_node_rail_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 9, 27, 10, 45, 0))
    patch_startup_loaders(monkeypatch, agents=_by_project_agents(tmp_path))
    async with AcePage(query='"visual"', patches=patches(), size=(80, 24)) as page:
        detail = await _goto_agents(page, 10)
        await _enter_rail(page, detail)
        ace_png_visual.assert_page_png(
            page,
            "agents_node_rail_80x24",
            title="ACE agents node rail narrow",
        )
