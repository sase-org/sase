"""AgentDetail lifecycle coverage for collapsed-panel summaries."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from textual.app import App, ComposeResult

from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panel_summary import (
    build_agent_panel_summary_snapshot,
)
from sase.ace.tui.widgets._agent_detail_panels import DetailPanelMode
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.agent_panel_summary import AgentPanelSummary


def _agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="summary_agent",
        project_file="/tmp/sase/sase.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 17, 12, 0, 0),
        raw_suffix="summary",
    )


class _DetailApp(App[None]):
    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


async def test_summary_invalidates_agent_render_and_preserves_detail_mode() -> None:
    agent = _agent()
    snapshot = build_agent_panel_summary_snapshot("focus", [agent])
    app = _DetailApp()

    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail._panel_mode = DetailPanelMode.INFO
        detail._current_agent = agent
        prior_generation = detail._agent_detail_generation

        detail.show_panel_summary(snapshot)
        await pilot.pause()

        assert detail.is_panel_summary_visible()
        assert detail._current_agent is None
        assert detail._agent_detail_generation == prior_generation + 1
        assert detail._panel_mode is DetailPanelMode.INFO
        assert not detail._is_agent_detail_render_current(
            agent.identity,
            prior_generation,
            "merged",
            None,
        )
        summary = detail.query_one("#agent-panel-summary", AgentPanelSummary)
        assert summary.snapshot == snapshot
        assert "COLLAPSED AGENT PANEL" in summary.render().plain
        assert "summary_agent" in summary.render().plain
        route_owner = SimpleNamespace(query_one=lambda *_args: detail)
        assert (
            BasicNavigationMixin._get_agent_detail_scroll_id(route_owner)
            == "#agent-panel-summary-scroll"
        )

        detail.update_display_immediate(agent)
        await pilot.pause()

        assert not detail.is_panel_summary_visible()
        assert detail._current_agent is agent
        assert detail._panel_mode is DetailPanelMode.INFO


async def test_large_summary_mounts_narrow_without_truncating_members() -> None:
    agents = [_agent() for _index in range(75)]
    for index, agent in enumerate(agents):
        agent.cl_name = f"narrow_summary_agent_{index}"
        agent.raw_suffix = f"narrow-{index}"
    snapshot = build_agent_panel_summary_snapshot("large", agents)
    app = _DetailApp()

    async with app.run_test(size=(40, 12)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.show_panel_summary(snapshot)
        await pilot.pause()

        summary = detail.query_one("#agent-panel-summary", AgentPanelSummary)
        rendered = summary.render().plain
        assert detail.is_panel_summary_visible()
        assert "75 agents" in rendered
        assert "narrow_summary_agent_0" in rendered
        assert "narrow_summary_agent_74" in rendered
