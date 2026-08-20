"""Shared helpers for agent render cache tests."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.app import App

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_rendering import agent_render_key
from sase.ace.tui.widgets.agent_list import AgentList


def agent(
    *,
    cl_name: str = "demo",
    status: str = "DONE",
    approve: bool = False,
    agent_name: str | None = None,
    raw_suffix: str = "20260425143000",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/p.sase",
        status=status,
        start_time=datetime(2026, 4, 25, 14, 30, 0),
        approve=approve,
        agent_name=agent_name,
        raw_suffix=raw_suffix,
    )


def bead_key(a: Agent) -> tuple[object, ...]:
    return agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )


def style_at(text: Text, position: int) -> str | None:
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    return str(text.style) if text.style else None


class AgentListHarness(App):
    """Mount a single AgentList for the patch tests."""

    def compose(self):
        yield AgentList(id="agent-list")


def agent_row_index(widget: AgentList, agent_idx: int) -> int:
    """Resolve the OptionList row index for ``agent_idx`` in *widget*."""
    return widget._row_index_for_agent(agent_idx)  # type: ignore[return-value]
