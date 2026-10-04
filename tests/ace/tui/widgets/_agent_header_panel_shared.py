"""Shared helpers for the split agent header-panel tests.

The tests formerly lived in a single ``test_agent_header_panel`` module.
Helpers needed by more than one split module live here under public names;
the ``test_agent_header_panel_*`` modules import only these public names
(never ``_``-prefixed names from each other).
"""

from __future__ import annotations

import dataclasses
from typing import Any

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.agent_header_panel import AgentHeaderPanel
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from tests.ace.tui.widgets._agent_display_helpers import (
    make_agent,
    make_artifact_agent,
)

__all__ = [
    "LONG_RAW_PROMPT",
    "DetailApp",
    "artifact_agent",
    "header_panel",
    "header_text",
    "show_agent",
    "show_agent_full",
    "solo_agent",
]

LONG_RAW_PROMPT = (
    "Can you help me start rendering the AGENT RAW PROMPT section in the sticky "
    "header above the agent data deck panel? Make sure that we provide a good "
    "preview of the contents in this section.\n"
    "\n"
    "- first list item explains the quote bar\n"
    "- second list item explains the row budget\n"
    "```\n"
    "some fenced code block line\n"
    "```\n"
    "A final hard-wrapped prose paragraph keeps going so the preview budget "
    "overflows and the border subtitle names the hidden line count."
)


def solo_agent() -> Any:
    return make_agent(agent_name="solo")


class DetailApp(App[None]):
    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


async def show_agent(detail: AgentDetail, agent: Any, pilot: Any) -> None:
    detail.update_display_immediate(agent)
    await pilot.pause()


async def show_agent_full(detail: AgentDetail, agent: Any, pilot: Any) -> None:
    detail.update_display(agent)
    await pilot.pause()


def artifact_agent(tmp_path: Any, name: str, raw_prompt: str) -> Any:
    subdir = tmp_path / name
    subdir.mkdir(exist_ok=True)
    agent = make_artifact_agent(subdir, status="DONE", raw_prompt=raw_prompt)
    return dataclasses.replace(agent, cl_name=f"cl-{name}", raw_suffix=name)


def header_panel(detail: AgentDetail) -> AgentHeaderPanel:
    return detail.query_one("#agent-header-panel", AgentHeaderPanel)


def header_text(panel: AgentHeaderPanel) -> str:
    content = panel.query_one("#agent-header-content")
    return renderable_to_text(getattr(content, "content", None)) or ""
