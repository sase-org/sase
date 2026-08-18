"""Workflow-step render paths for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text

from ...models.agent import Agent
from ...models.fold_state import FoldLevel
from ...util.lazy_syntax import lazy_renderable
from ._agent_display_header import AgentHeader
from ._agent_monitor_section import (
    MONITOR_SECTION_ID,
    build_monitor_output,
    build_monitor_section,
)
from ._helpers import append_section_heading, format_output


class AgentStepDisplayMixin:
    """Render bash, Python, and parallel workflow steps."""

    def _update_bash_python_display(
        self,
        agent: Agent,
        header_text: AgentHeader,
        error_tb_syntax: Syntax | None = None,
    ) -> None:
        """Display bash command or Python code with output."""
        if agent.step_type == "bash":
            source_label = "BASH COMMAND"
            syntax_lang = "bash"
        else:
            source_label = "PYTHON CODE"
            syntax_lang = "python"

        append_section_heading(header_text, source_label)

        source_content: object
        if agent.step_source:
            source_content = lazy_renderable(agent.step_source, syntax_lang)
        else:
            source_content = Text("No source available.\n", style="dim italic")

        output_header = Text()
        output_header.append("\n")
        output_header.append("\u2500" * 50 + "\n", style="dim")
        output_header.append("\n")
        append_section_heading(output_header, "STEP OUTPUT")

        renderables: list[Any] = [header_text]
        if error_tb_syntax:
            renderables.append(error_tb_syntax)
        renderables.append(source_content)

        if agent.step_output:
            output_str = format_output(agent.step_output)
            output_syntax = lazy_renderable(output_str, "json")
            renderables.extend([output_header, output_syntax])
        else:
            output_header.append("No output available.\n", style="dim italic")
            renderables.append(output_header)

        self.update(Group(*renderables))  # type: ignore[attr-defined]

    def _update_parallel_display(
        self,
        agent: Agent,
        header_text: AgentHeader,
        error_tb_syntax: Syntax | None = None,
    ) -> None:
        """Display output for a parallel workflow step without a prompt."""
        append_section_heading(header_text, "STEP OUTPUT")

        renderables: list[Any] = [header_text]
        if error_tb_syntax:
            renderables.append(error_tb_syntax)

        if agent.step_output:
            output_str = format_output(agent.step_output)
            output_syntax = lazy_renderable(output_str, "json")
            renderables.append(output_syntax)
        else:
            renderables.append(Text("No output available.\n", style="dim italic"))

        self.update(Group(*renderables))  # type: ignore[attr-defined]

    def _update_monitor_display(
        self,
        agent: Agent,
        header_text: AgentHeader,
        error_tb_syntax: Syntax | None = None,
        *,
        panel_level: FoldLevel = FoldLevel.COLLAPSED,
        section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    ) -> None:
        """Display a monitor member's command detail and captured output.

        ``live_reply.md`` holds a monitored command's raw merged stdout/stderr,
        not prose, so it is rendered as an ANSI-aware log block instead of the
        markdown path every other agent reply uses.
        """
        overrides = section_fold_overrides or {}
        section_level = overrides.get(MONITOR_SECTION_ID, panel_level)

        renderables: list[Any] = [header_text]
        if error_tb_syntax:
            renderables.append(error_tb_syntax)
        renderables.extend(build_monitor_section(agent, panel_level=section_level))
        renderables.extend(build_monitor_output(agent))

        self.update(Group(*renderables))  # type: ignore[attr-defined]
