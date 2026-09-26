"""Workflow-step render paths for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rich.syntax import Syntax
from rich.text import Text

from ...models.agent import Agent
from ...models._projected_record import resolve_step_output
from ...models.fold_state import FoldLevel
from ...util.lazy_syntax import lazy_renderable
from ._agent_display_header import AgentHeader
from ._agent_gate_section import (
    GATE_SECTION_ID,
    build_gate_output,
    build_gate_section,
)
from ._agent_monitor_section import (
    MONITOR_SECTION_ID,
    build_monitor_output,
    build_monitor_section,
)
from ._agent_proc_shell_section import (
    PROC_SHELL_SECTION_ID,
    build_proc_shell_output,
    build_proc_shell_preview,
    build_proc_shell_section,
)
from ..decks.card_part import card_document, context_card, output_card
from ._helpers import append_section_heading, format_output
from ._traceback_section import build_traceback_block


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
        append_section_heading(output_header, "STEP OUTPUT")

        output_parts: list[Any] = [*build_traceback_block(error_tb_syntax)]

        step_output = resolve_step_output(agent)
        if step_output:
            output_str = format_output(step_output)
            output_syntax = lazy_renderable(output_str, "json")
            output_parts.extend([output_header, output_syntax])
        else:
            output_header.append("No output available.\n", style="dim italic")
            output_parts.append(output_header)

        self.update(  # type: ignore[attr-defined]
            card_document(
                context_card(header_text, source_content),
                output_card(*output_parts),  # type: ignore[arg-type]
            )
        )

    def _update_parallel_display(
        self,
        agent: Agent,
        header_text: AgentHeader,
        error_tb_syntax: Syntax | None = None,
    ) -> None:
        """Display output for a parallel workflow step without a prompt."""
        try:
            header_text.end = ""
        except Exception:
            pass
        output_header = Text()
        append_section_heading(output_header, "STEP OUTPUT")

        output_parts: list[Any] = [
            *build_traceback_block(error_tb_syntax),
            output_header,
        ]

        step_output = resolve_step_output(agent)
        if step_output:
            output_str = format_output(step_output)
            output_syntax = lazy_renderable(output_str, "json")
            output_parts.append(output_syntax)
        else:
            output_parts.append(Text("No output available.\n", style="dim italic"))

        self.update(  # type: ignore[attr-defined]
            card_document(
                context_card(header_text),
                output_card(*output_parts),  # type: ignore[arg-type]
            )
        )

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

        context_parts: list[Any] = [
            header_text,
            *build_monitor_section(agent, panel_level=section_level),
        ]
        output_parts: list[Any] = [
            *build_traceback_block(error_tb_syntax),
            *build_monitor_output(agent),
        ]

        self.update(  # type: ignore[attr-defined]
            card_document(
                context_card(*context_parts),  # type: ignore[arg-type]
                output_card(*output_parts),  # type: ignore[arg-type]
            )
        )

    def _update_gate_display(
        self,
        agent: Agent,
        header_text: AgentHeader,
        error_tb_syntax: Syntax | None = None,
        *,
        panel_level: FoldLevel = FoldLevel.COLLAPSED,
        section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    ) -> None:
        """Display a gate member's decision detail and captured output."""
        overrides = section_fold_overrides or {}
        section_level = overrides.get(GATE_SECTION_ID, panel_level)

        context_parts = [
            header_text,
            *build_gate_section(agent, panel_level=section_level),
        ]
        output_parts: list[Any] = [
            *build_traceback_block(error_tb_syntax),
            *build_gate_output(agent),
        ]

        self.update(  # type: ignore[attr-defined]
            card_document(
                context_card(*context_parts),  # type: ignore[arg-type]
                output_card(*output_parts),  # type: ignore[arg-type]
            )
        )

    def _update_proc_shell_display(
        self,
        agent: Agent,
        header_text: AgentHeader,
        error_tb_syntax: Syntax | None = None,
        *,
        panel_level: FoldLevel = FoldLevel.COLLAPSED,
        section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    ) -> None:
        """Display one stand-alone proc shell without probing agent artifacts."""
        overrides = section_fold_overrides or {}
        section_level = overrides.get(PROC_SHELL_SECTION_ID, panel_level)

        context_parts = [
            header_text,
            *build_proc_shell_preview(agent),
            *build_proc_shell_section(agent, panel_level=section_level),
        ]
        output_parts: list[Any] = [
            *build_traceback_block(error_tb_syntax),
            *build_proc_shell_output(agent),
        ]

        self.update(  # type: ignore[attr-defined]
            card_document(
                context_card(*context_parts),  # type: ignore[arg-type]
                output_card(*output_parts),  # type: ignore[arg-type]
            )
        )
