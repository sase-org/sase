"""Regression tests for AgentList one-line option rendering."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.containers import Container

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.agent_list import AgentList


_ROOT = Path(__file__).resolve().parents[4]


def _agent(
    *,
    cl_name: str,
    raw_suffix: str,
    agent_name: str,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/long-project-name/project.gp",
        status="DONE",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        stop_time=datetime(2026, 4, 25, 14, 3, 4),
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        tag="long-tag-name",
    )


class _NarrowAgentListApp(App[None]):
    """Mount AgentList with the production stylesheet in a narrow viewport."""

    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"
    CSS = """
    #harness {
        width: 28;
        height: 12;
    }

    #agent-list {
        width: 100%;
        height: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="harness"):
            yield AgentList(id="agent-list")


@pytest.mark.asyncio
async def test_agent_list_options_stay_single_line_when_narrow() -> None:
    """Textual's OptionList line cache should assign one visual row per option."""
    app = _NarrowAgentListApp()
    async with app.run_test(size=(36, 16)) as pilot:
        widget = app.query_one(AgentList)
        widget.update_list(
            [
                _agent(
                    cl_name="very-long-change-spec-name-alpha",
                    raw_suffix="20260425140304",
                    agent_name="coder.codex.with.long.annotation",
                ),
                _agent(
                    cl_name="very-long-change-spec-name-beta",
                    raw_suffix="20260425140305",
                    agent_name="reviewer.claude.with.long.annotation",
                ),
            ],
            current_idx=0,
            now=datetime(2026, 4, 25, 16, 0, 0),
        )
        await pilot.pause()

        widget._line_cache.clear()
        widget._update_lines()

        assert widget.styles.text_wrap == "nowrap"
        assert widget.styles.text_overflow == "clip"
        assert widget.option_count > 0
        assert set(widget._line_cache.heights.values()) == {1}
        assert len(widget._line_cache.lines) == widget.option_count
