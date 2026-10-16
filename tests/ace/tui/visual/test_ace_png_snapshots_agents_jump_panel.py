"""sase's TUI PNG visual snapshots for the Agents-tab jump footer panel."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.llm_calls import cache as tools_cache_module
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import AgentDetail, AgentJumpPanel
from sase.ace.tui.widgets._agent_jump_legend import JumpLegendRenderable
from sase.ace.tui.widgets.prompt_panel._member_roster import MemberJumpMap
from sase.ace.tui.widgets import llm_calls_panel as llm_calls_panel_module
from sase.ace.tui.widgets.decks.model import DeckId
from sase.ace.tui.widgets.llm_calls_panel import AgentLLMCallsPanel
from tests.ace.tui.visual._ace_agents_png_snapshot_agent_session_fixtures import (
    agent_session_and_lone_planner_agents,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    pin_agents_visual_now,
)
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


def _big_agent_session_agents() -> list[Agent]:
    """Proven agent session plus twelve dotted descendants for neighbor sections."""
    agents = agent_session_and_lone_planner_agents()
    peers = [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"visual-real-family-peer-{index:02d}",
            project_file="/workspace/sase/visual_project.sase",
            status="RUNNING",
            start_time=datetime(2026, 7, 18, 12, 20, 0),
            raw_suffix=f"202607181220{index:02d}",
            agent_name=f"visual-real-family.peer{index:02d}",
        )
        for index in range(12)
    ]
    return [*agents, *peers]


def _big_clan_agents() -> list[Agent]:
    """Fourteen clan members, enough for two-digit clan numbering."""
    started = datetime(2026, 7, 23, 9, 0, 0)
    project_file = "/workspace/sase/visual_project.sase"
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"visual-bigclan-member-{index:02d}",
            project_file=project_file,
            status="DONE" if index % 2 == 0 else "RUNNING",
            start_time=started,
            stop_time=started if index % 2 == 0 else None,
            raw_suffix=f"202607230900{index:02d}",
            agent_name=f"member{index:02d}",
            agent_clan="visual-bigclan",
        )
        for index in range(14)
    ]


_IN_FLIGHT_MIX_STATUSES = {
    1: "STARTING",
    3: "FAILED",
    4: "RUNNING",
    6: "QUESTION",
    7: "RUNNING",
    9: "FAILED",
    10: "RUNNING",
    12: "WAITING",
    13: "RUNNING",
}


def _in_flight_mix_clan_agents() -> list[Agent]:
    """Fourteen clan members with five in-flight targets past the first slots."""
    started = datetime(2026, 7, 23, 9, 0, 0)
    project_file = "/workspace/sase/visual_project.sase"
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"visual-mixclan-member-{index:02d}",
            project_file=project_file,
            status=_IN_FLIGHT_MIX_STATUSES.get(index, "DONE"),
            start_time=started,
            stop_time=started if index not in _IN_FLIGHT_MIX_STATUSES else None,
            raw_suffix=f"202607231100{index:02d}",
            agent_name=f"member{index:02d}",
            agent_clan="visual-mixclan",
        )
        for index in range(14)
    ]


def _layered_jump_clan_agents() -> list[Agent]:
    """Layered clan with a seal for divider and title suffix snapshots."""
    generation = "20260723090000"
    start = datetime(2026, 7, 23, 9, 0, 0)
    members = (
        ("root", "DONE", ()),
        ("peer", "RUNNING", ()),
        ("build", "RUNNING", ("visual-wave-clan.root",)),
        ("test", "WAITING", ("visual-wave-clan.build",)),
        ("docs", "DONE", ("visual-wave-clan.test",)),
    )
    agents = [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"visual-wave-clan-{suffix}",
            project_file="/workspace/sase/visual_project.sase",
            status=status,
            start_time=start.replace(minute=index),
            stop_time=start.replace(minute=index + 1) if status == "DONE" else None,
            raw_suffix=f"2026072309{index:02d}00-{suffix}",
            agent_name=f"visual-wave-clan.{suffix}",
            agent_clan="visual-wave-clan",
            agent_clan_generation=generation,
            phase_bead_id=f"sase-visual.{index}",
            waiting_for=list(waits),
        )
        for index, (suffix, status, waits) in enumerate(members)
    ]
    land = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-wave-clan-land",
        project_file="/workspace/sase/visual_project.sase",
        status="WAITING",
        start_time=start.replace(minute=5),
        raw_suffix="20260723090500-land",
        agent_name="visual-wave-clan.land",
        agent_clan="visual-wave-clan",
        agent_clan_generation=generation,
        epic_bead_id="sase-visual-epic",
        waiting_for=["visual-wave-clan.docs"],
    )
    return [*agents, land]


def _collapsed_shown_numbers(
    jump_map: MemberJumpMap, width: int
) -> tuple[list[str], str]:
    """Return the shown numbers and last line of a collapsed legend render."""
    lines = JumpLegendRenderable(jump_map, mode="collapsed")._lines_for_width(  # noqa: SLF001
        width
    )
    texts = [line.plain for line in lines]
    numbers = [target.number for target in jump_map.targets]
    shown: list[str] = []
    for line in texts:
        line = line.replace("┊", " ")
        for cell in line.split("  "):
            first = cell.strip().split(" ", 1)[0].removeprefix("⊘").strip()
            if first in numbers and first not in shown:
                shown.append(first)
    return shown, texts[-1]


async def _open_agents_on_jump_roster(
    page: AcePage, *, zoom_deck: bool = False
) -> AgentDetail:
    await wait_for_startup(page)
    await page.press("shift+tab")
    await page.expect_state("tab", "agents")
    await wait_for_visual_idle(page)
    detail = page.app.query_one("#agent-detail-panel", AgentDetail)
    await wait_for_state(
        page,
        lambda: detail.jump_panel_toggle_available(),
        description="jump panel available",
    )
    if zoom_deck:
        await page.press("Z")
        await wait_for_visual_idle(page)
    await wait_for_svg_contains(page, "JUMP")
    await wait_for_visual_idle(page)
    return detail


async def test_jump_panel_collapsed_single_section_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 19, 9, 5, 5))
    patch_startup_loaders(monkeypatch, agents=agent_session_and_lone_planner_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        detail = await _open_agents_on_jump_roster(page)
        panel = detail.query_one("#agent-jump-panel", AgentJumpPanel)
        assert not panel.is_expanded
        assert_page_svg_contains(page, "SESSION TURNS")
        assert_page_svg_contains(page, "more")

        ace_png_visual.assert_page_png(
            page,
            "agents_jump_panel_collapsed_single_section_120x40",
            title="ACE agents jump panel collapsed single section",
        )


async def test_jump_panel_collapsed_two_digit_overflow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 23, 9, 30, 0))
    patch_startup_loaders(monkeypatch, agents=_big_clan_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        detail = await _open_agents_on_jump_roster(page)
        panel = detail.query_one("#agent-jump-panel", AgentJumpPanel)
        assert not panel.is_expanded
        assert_page_svg_contains(page, "CLAN MEMBERS")
        assert_page_svg_contains(page, "+")
        jump_map = panel._jump_map  # noqa: SLF001
        assert jump_map is not None
        running_numbers = [
            target.number
            for target in jump_map.targets
            if target.status_bucket == "Running"
        ]
        assert running_numbers == ["01", "03", "05", "07", "09", "11", "13"]
        shown, last_line = _collapsed_shown_numbers(jump_map, 60)
        assert shown == ["01", "03", "05", "07", "09"]
        assert last_line.strip().endswith("+9 ▶2")

        ace_png_visual.assert_page_png(
            page,
            "agents_jump_panel_collapsed_two_digit_overflow_120x40",
            title="ACE agents jump panel collapsed two-digit overflow",
        )


@pytest.mark.parametrize("width", (60, 80, 120))
async def test_jump_panel_layered_wave_dividers_png_snapshot(
    width: int,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 23, 9, 30, 0))
    patch_startup_loaders(monkeypatch, agents=_layered_jump_clan_agents())

    async with AcePage(
        query='"visual"',
        size=(width, 40),
        patches=patches(),
    ) as page:
        detail = await _open_agents_on_jump_roster(page, zoom_deck=width < 120)
        panel = detail.query_one("#agent-jump-panel", AgentJumpPanel)
        jump_map = panel._jump_map  # noqa: SLF001
        assert jump_map is not None
        assert jump_map.sections[0].title_suffix == "4 WAVES + LAND"
        legend = JumpLegendRenderable(jump_map, mode="collapsed")
        lines = legend._lines_for_width(max(1, panel.size.width - 2))  # noqa: SLF001
        assert 1 <= len(lines) <= 2
        assert any("┊" in line.plain for line in lines)
        assert_page_svg_contains(page, "┊")

        ace_png_visual.assert_page_png(
            page,
            f"agents_jump_panel_layered_wave_dividers_{width}x40",
            title=f"ACE agents layered-clan JUMP panel at {width} columns",
        )


async def test_jump_panel_collapsed_in_flight_mix_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 23, 11, 30, 0))
    patch_startup_loaders(monkeypatch, agents=_in_flight_mix_clan_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        detail = await _open_agents_on_jump_roster(page)
        panel = detail.query_one("#agent-jump-panel", AgentJumpPanel)
        assert not panel.is_expanded
        assert_page_svg_contains(page, "CLAN MEMBERS")
        jump_map = panel._jump_map  # noqa: SLF001
        assert jump_map is not None
        in_flight_numbers = [
            target.number
            for target in jump_map.targets
            if target.status_bucket in ("Running", "Starting")
        ]
        assert in_flight_numbers == ["01", "04", "07", "10", "13"]
        shown, last_line = _collapsed_shown_numbers(jump_map, 60)
        assert shown == in_flight_numbers
        assert last_line.strip().endswith("+9")

        ace_png_visual.assert_page_png(
            page,
            "agents_jump_panel_collapsed_in_flight_mix_120x40",
            title="ACE agents jump panel collapsed in-flight mix",
        )


async def test_jump_panel_expanded_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 23, 9, 30, 0))
    patch_startup_loaders(monkeypatch, agents=_big_clan_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        detail = await _open_agents_on_jump_roster(page)
        await page.press(".")
        await wait_for_svg_contains(page, "less")
        await wait_for_visual_idle(page)
        panel = detail.query_one("#agent-jump-panel", AgentJumpPanel)
        assert panel.is_expanded
        assert_page_svg_contains(page, "CLAN MEMBERS")
        assert_page_svg_contains(page, "member00")

        ace_png_visual.assert_page_png(
            page,
            "agents_jump_panel_expanded_120x40",
            title="ACE agents jump panel expanded",
        )


async def test_jump_panel_expanded_two_sections_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 23, 9, 30, 0))
    patch_startup_loaders(monkeypatch, agents=_big_agent_session_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        detail = await _open_agents_on_jump_roster(page)
        await page.press(".")
        await wait_for_svg_contains(page, "less")
        await wait_for_visual_idle(page)
        panel = detail.query_one("#agent-jump-panel", AgentJumpPanel)
        assert panel.is_expanded
        from sase.ace.tui.widgets.renderable_text import renderable_to_text

        expanded_text = renderable_to_text(panel._member_roster)  # noqa: SLF001
        assert expanded_text is not None
        assert "❖ SESSION TURNS" in expanded_text
        assert "❖ NEIGHBORS" in expanded_text

        ace_png_visual.assert_page_png(
            page,
            "agents_jump_panel_expanded_two_sections_120x40",
            title="ACE agents jump panel expanded two sections",
        )


async def test_jump_panel_narrowed_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 23, 9, 30, 0))
    patch_startup_loaders(monkeypatch, agents=_big_clan_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_agents_on_jump_roster(page)
        await page.press("1")
        await wait_for_svg_contains(page, "esc cancel")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_jump_panel_narrowed_120x40",
            title="ACE agents jump panel narrowed after first digit",
        )


def _populate_agent_session_tool_calls(artifacts_dir: Path) -> None:
    records: list[dict[str, Any]] = [
        {
            "schema_version": 2,
            "recorded_at": "2026-07-23T09:01:00+00:00",
            "runtime": "codex",
            "source": "stream",
            "event": "ToolUse",
            "status": "pending",
            "tool_name": "Edit",
            "tool_use_id": "call_jump_family_1",
            "tool_input_summary": {
                "file_path": "src/sase/ace/tui/widgets/agent_jump_panel.py"
            },
            "tool_response_summary": {},
        },
        {
            "schema_version": 2,
            "recorded_at": "2026-07-23T09:01:05+00:00",
            "runtime": "codex",
            "source": "stream",
            "event": "ToolResult",
            "status": "completed",
            "tool_name": "Edit",
            "tool_use_id": "call_jump_family_1",
            "duration_ms": 918,
            "completed_at": "2026-07-23T09:01:05+00:00",
            "tool_input_summary": {
                "file_path": "src/sase/ace/tui/widgets/agent_jump_panel.py"
            },
            "tool_response_summary": {},
        },
    ]
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    path = artifacts_dir / "tool_calls.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            json.dump(record, handle, sort_keys=True)
            handle.write("\n")


def _llm_calls_agent_session_agents(artifacts_dir: Path) -> list[Agent]:
    agents = agent_session_and_lone_planner_agents()
    root = agents[0]
    root.llm_provider = "codex"
    root.model = "gpt-5.5"
    root.artifacts_dir = str(artifacts_dir)
    return agents


async def test_jump_panel_llm_calls_layout_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 19, 9, 5, 5))
    monkeypatch.setattr(
        llm_calls_panel_module, "local_now", lambda: datetime(2026, 7, 19, 9, 5, 5)
    )
    monkeypatch.setattr(
        tools_cache_module, "local_now", lambda: datetime(2026, 7, 19, 9, 5, 5)
    )
    llm_calls_panel_module._llm_calls_cache.clear()
    artifacts_dir = tmp_path / "ace-run" / "20260718120000"
    _populate_agent_session_tool_calls(artifacts_dir)
    patch_startup_loaders(
        monkeypatch, agents=_llm_calls_agent_session_agents(artifacts_dir)
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        detail = await _open_agents_on_jump_roster(page)
        detail.show_deck(0, DeckId.TOOLS)
        await wait_for_state(
            page,
            lambda: detail.deck_area.panel(0).deck is DeckId.TOOLS,
            description="Tools deck selected",
        )
        await wait_for_state(
            page,
            lambda: bool(detail.deck_area.panel(0).tools_view._last_entries),
            description="Tools deck content available",
        )
        page.app._refresh_agent_footer_bindings_only()
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "JUMP")
        assert_page_svg_contains(page, "SESSION TURNS")
        panel = detail.deck_area.panel(0).tools_view
        assert panel._last_entries

        ace_png_visual.assert_page_png(
            page,
            "agents_jump_panel_llm_calls_layout_120x40",
            title="ACE agents jump panel below LLM Calls panel",
        )
