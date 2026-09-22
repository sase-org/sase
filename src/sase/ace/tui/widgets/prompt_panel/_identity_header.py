"""Detachable identity header model for prompt-panel documents."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.text import Span, Text

from ...models.agent import Agent, AgentType
from .._agent_list_styling import (
    _AGENT_NAME_ANNOTATION_STYLE,
    _GATE_ROW_STYLE,
    _MONITOR_ROW_STYLE,
    _PROC_SHELL_ROW_STYLE,
    _STEP_TYPE_COLORS,
)
from ._agent_display_family import FAMILY_IDENTITY_COLOR
from ._agent_display_header_renderable import AgentHeader, AgentHeaderRenderable

# Must match the light rule in ``append_major_section_divider`` (``_helpers``).
_MAJOR_DIVIDER_RULE = "─" * 50

WORKFLOW_IDENTITY_COLOR = "#AF87D7"
AGENT_FALLBACK_IDENTITY_COLOR = "#87AFFF"
STEP_FALLBACK_IDENTITY_COLOR = "#D7AFFF"

IdentityHeaderSink = Callable[["IdentityHeader | None"], None]


@dataclass(frozen=True, slots=True)
class IdentityHeader:
    """Identity block split out of a prompt-panel metadata document."""

    kind_label: str
    accent: str
    expanded: AgentHeader
    compact: Text
    has_hints: bool = False

    def inline_renderable(self) -> RenderableType:
        """Return the kind line plus expanded block for inline documents."""
        kind_line = Text()
        kind_line.append(f"{self.kind_label}\n", style=f"bold {self.accent} underline")
        return Group(kind_line, self.expanded)


def identity_kind_for_agent(agent: Agent) -> tuple[str, str]:
    """Return the panel kind label and accent color for ``agent``."""
    if agent.is_family_container_row:
        return ("FAMILY", FAMILY_IDENTITY_COLOR)
    if agent.is_proc_shell:
        return ("PROC SHELL", _PROC_SHELL_ROW_STYLE)
    if agent.is_agent_entry:
        return ("AGENT SHELL", _AGENT_NAME_ANNOTATION_STYLE)
    if agent.is_gate:
        return ("GATE", _GATE_ROW_STYLE)
    if agent.is_monitor:
        return ("MONITOR", _MONITOR_ROW_STYLE)
    if agent.is_workflow_step_child and agent.step_type:
        return (
            "STEP",
            _STEP_TYPE_COLORS.get(agent.step_type, STEP_FALLBACK_IDENTITY_COLOR),
        )
    if (
        agent.agent_type == AgentType.WORKFLOW
        and not agent.is_workflow_child
        and not agent.appears_as_agent
    ):
        return ("WORKFLOW", WORKFLOW_IDENTITY_COLOR)
    return ("AGENT", AGENT_FALLBACK_IDENTITY_COLOR)


def find_identity_header(content: object) -> IdentityHeader | None:
    """Return the identity attached to a prompt-panel document, if any."""
    if isinstance(content, AgentHeaderRenderable):
        return content.identity_header
    if isinstance(content, Group):
        for child in content.renderables:
            found = find_identity_header(child)
            if found is not None:
                return found
        return None
    renderable = getattr(content, "renderable", None)
    if renderable is not None and not isinstance(content, (Text, str, bytes)):
        return find_identity_header(renderable)
    return None


def strip_leading_document_chrome(text: Text) -> tuple[Text, int]:
    """Strip blank lines plus one light divider from the body start."""
    plain = text.plain
    pos = 0
    total = len(plain)
    while pos < total and plain[pos] == "\n":
        pos += 1
    if plain.startswith(_MAJOR_DIVIDER_RULE, pos):
        pos += len(_MAJOR_DIVIDER_RULE)
        while pos < total and plain[pos] == "\n":
            pos += 1
    if not pos:
        return text, 0
    stripped = Text(plain[pos:], end=text.end)
    for span in text.spans:
        if span.end <= pos:
            continue
        stripped.spans.append(
            Span(max(span.start, pos) - pos, span.end - pos, span.style)
        )
    return stripped, pos


__all__ = [
    "AGENT_FALLBACK_IDENTITY_COLOR",
    "STEP_FALLBACK_IDENTITY_COLOR",
    "WORKFLOW_IDENTITY_COLOR",
    "IdentityHeader",
    "IdentityHeaderSink",
    "find_identity_header",
    "identity_kind_for_agent",
    "strip_leading_document_chrome",
]
