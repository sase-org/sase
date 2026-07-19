"""AgentDetail lifecycle coverage for tribe documents."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from textual.app import App, ComposeResult

from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_tribe_summary import (
    build_agent_tribe_summary_snapshot,
)
from sase.ace.tui.widgets._agent_detail_panels import DetailPanelMode
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel


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
    panel_fold_level = None

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


async def test_tribe_document_invalidates_agent_render_and_uses_prompt_scroll() -> None:
    agent = _agent()
    snapshot = build_agent_tribe_summary_snapshot(
        "focus",
        [agent],
        panel_collapsed=True,
    )
    app = _DetailApp()

    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail._panel_mode = DetailPanelMode.INFO
        detail._current_agent = agent
        prior_generation = detail._agent_detail_generation

        detail.show_tribe_summary(snapshot)
        await pilot.pause()

        assert detail._current_agent is None
        assert detail._current_tribe_identity == ("panel", "focus")
        assert detail._agent_detail_generation == prior_generation + 1
        assert detail._panel_mode is DetailPanelMode.INFO
        assert not detail._is_agent_detail_render_current(
            agent.identity,
            prior_generation,
            "merged",
            None,
        )
        prompt = detail.query_one("#agent-prompt-panel", AgentPromptPanel)
        assert "TRIBE\nName: @focus" in prompt.content.plain
        assert "summary_agent" not in prompt.content.plain  # Pulse is count-only.
        route_owner = SimpleNamespace(query_one=lambda *_args: detail)
        assert (
            BasicNavigationMixin._get_agent_detail_scroll_id(route_owner)
            == "#agent-prompt-scroll"
        )

        detail.update_display_immediate(agent)
        await pilot.pause()

        assert detail._current_tribe_identity is None
        assert detail._current_agent is agent


async def test_cheap_then_full_tribe_paint_preserves_one_prompt_surface() -> None:
    agents = [_agent() for _index in range(12)]
    for index, agent in enumerate(agents):
        agent.cl_name = f"tribe-agent-{index}"
        agent.raw_suffix = f"tribe-{index}"
    snapshot = build_agent_tribe_summary_snapshot(
        None,
        agents,
        panel_collapsed=True,
    )
    app = _DetailApp()

    async with app.run_test(size=(45, 14)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        prompt = detail.query_one("#agent-prompt-panel", AgentPromptPanel)

        detail.show_tribe_summary(snapshot, cheap=True)
        await pilot.pause()
        assert "TRIBE MEMBERS" not in prompt.content.plain

        detail.show_tribe_summary(snapshot)
        await pilot.pause()
        rendered = prompt.content.plain
        assert "TRIBE MEMBERS · 12" in rendered
        assert "tribe-agent-0" not in rendered  # Pulse roster remains count-only.
        assert len(list(detail.query("#agent-prompt-panel"))) == 1
