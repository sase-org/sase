"""Rendering helpers for the dismissed-agent revive modal."""

from __future__ import annotations

from rich.text import Text
from textual.widgets.option_list import Option

from sase.project_display_names import humanize_vcs_refs_in_text

from ..models.agent import Agent, AgentType
from ..models.agent_status import STOPPED_COLOR, STOPPED_GLYPH, STOPPED_STATUS

_TYPE_COLORS: dict[AgentType, str] = {
    AgentType.RUNNING: "#87AFFF",
    AgentType.WORKFLOW: "#FF87D7",
}

_STEP_TYPE_COLORS: dict[str, str] = {
    "agent": "#5FD7FF",
    "bash": "#FFAF5F",
    "python": "#87D787",
    "parallel": "#D7AFFF",
}

_STATUS_COLORS: dict[str, str] = {
    "DONE": "#5FD75F",
    "FAILED": "#FF5F5F",
    STOPPED_STATUS: STOPPED_COLOR,
    "WAITING INPUT": "#FF87D7",
}


def get_type_color(agent: Agent) -> str:
    """Get the color for an agent's type label."""
    if agent.appears_as_agent:
        return _TYPE_COLORS[AgentType.RUNNING]
    if agent.is_workflow_child and agent.step_type in _STEP_TYPE_COLORS:
        return _STEP_TYPE_COLORS[agent.step_type]
    return _TYPE_COLORS.get(agent.agent_type, "#FFFFFF")


def get_status_style(status: str) -> str:
    """Get Rich style string for a status value."""
    color = _STATUS_COLORS.get(status)
    if color:
        return f"bold {color}"
    return "dim"


def format_agent_label(
    agent: Agent,
    orig_idx: int = -1,
    *,
    marked: set[int] | None = None,
    step_counts: dict[str, int] | None = None,
) -> Text:
    """Create styled text for an agent option."""
    marked = marked or set()
    step_counts = step_counts or {}

    text = Text()

    if orig_idx in marked:
        text.append(" \u25cf ", style="bold #00D7D7")
    else:
        text.append("   ")

    if agent.status == "DONE":
        text.append("\u2714 ", style="bold #5FD75F")
    elif agent.status == "FAILED":
        text.append("\u2718 ", style="bold #FF5F5F")
    elif agent.status == STOPPED_STATUS:
        text.append(f"{STOPPED_GLYPH} ", style=f"bold {STOPPED_COLOR}")
    else:
        text.append("\u25cb ", style="dim")

    type_color = get_type_color(agent)
    text.append(f"[{agent.display_type}]", style=f"bold {type_color}")
    text.append(" ")

    text.append(agent.display_name, style="bold")

    if agent.presented_agent_name:
        text.append("  ")
        text.append(f"@{agent.presented_agent_name}", style="#87D7FF")

    text.append("  ")
    text.append(agent.start_time_compact, style="dim")

    if agent.model:
        text.append("  ")
        text.append(agent.model, style="dim italic")

    if agent.raw_suffix and agent.raw_suffix in step_counts:
        count = step_counts[agent.raw_suffix]
        text.append("  ")
        text.append(f"({count} steps)", style="dim #00D7D7")

    return text


def create_options(
    agents: list[Agent],
    *,
    marked: set[int] | None = None,
    step_counts: dict[str, int] | None = None,
) -> list[Option]:
    """Create options from agents."""
    return [
        Option(
            format_agent_label(agent, i, marked=marked, step_counts=step_counts),
            id=str(i),
        )
        for i, agent in enumerate(agents)
    ]


def placeholder_option(*, loading_archive: bool) -> Option:
    """Create the disabled loading or empty placeholder option."""
    if loading_archive:
        return Option(Text("Loading dismissed archive...", style="dim"), disabled=True)
    return Option(Text("No dismissed agents in this scope", style="dim"), disabled=True)


def build_metadata_preview(agent: Agent, children: list[Agent]) -> Text:
    """Build structured agent metadata for the preview pane."""
    meta = Text()

    type_color = get_type_color(agent)
    header = f"[{agent.display_type}] {agent.display_name}"
    meta.append("\u2501\u2501\u2501 ", style="dim")
    meta.append(header, style=f"bold {type_color}")
    meta.append(
        " " + "\u2501" * max(1, 36 - len(header)),
        style="dim",
    )
    meta.append("\n\n")

    label_width = 12

    meta.append(f"  {'Status':<{label_width}}", style="bold")
    meta.append(agent.status, style=get_status_style(agent.status))
    meta.append("\n")

    meta.append(f"  {'Started':<{label_width}}", style="bold")
    meta.append(f"{agent.start_time_display}\n", style="dim")

    meta.append(f"  {'Duration':<{label_width}}", style="bold")
    meta.append(f"{agent.duration_display}\n", style="dim")

    if agent.model:
        meta.append(f"  {'Model':<{label_width}}", style="bold")
        meta.append(f"{agent.model}\n", style="dim italic")

    if agent.llm_provider:
        meta.append(f"  {'Provider':<{label_width}}", style="bold")
        meta.append(f"{agent.llm_provider}\n", style="dim")

    if agent.presented_agent_name:
        meta.append(f"  {'Agent':<{label_width}}", style="bold")
        meta.append(f"@{agent.presented_agent_name}\n", style="#87D7FF")

    if agent.workflow and not agent.appears_as_agent:
        meta.append(f"  {'Workflow':<{label_width}}", style="bold")
        meta.append(f"{agent.workflow}\n", style="dim")

    if children:
        meta.append(f"\n  \u2500\u2500 Steps ({len(children)}) ")
        meta.append(
            "\u2500" * 24 + "\n",
            style="dim",
        )
        for i, child in enumerate(children, 1):
            step_type = child.step_type or "step"
            step_name = child.step_name or child.cl_name
            status_style = get_status_style(child.status)
            meta.append(f"  {i}. ", style="dim #AAAAAA")
            step_color = _STEP_TYPE_COLORS.get(step_type, type_color)
            meta.append(f"[{step_type}] ", style=f"dim {step_color}")
            meta.append(f"{step_name:<20}", style="dim")
            meta.append(f"{child.status}\n", style=status_style)

    if agent.error_message:
        meta.append("\n  \u2500\u2500 Error ")
        meta.append("\u2500" * 28 + "\n", style="dim")
        meta.append(f"  {agent.error_message}\n", style="bold #FF5F5F")
        if agent.error_traceback:
            meta.append(f"  {agent.error_traceback}\n", style="dim #FF5F5F")

    return meta


def build_response_preview(agent: Agent) -> Text:
    """Build the response preview body for an agent."""
    raw = agent.get_response_content()
    content = raw.strip() if raw else None

    if not content:
        return Text("(no response content)", style="dim italic")

    preview = Text()
    preview.append(
        "\n  \u2500\u2500 Response " + "\u2500" * 26 + "\n",
        style="dim",
    )
    preview_content = humanize_vcs_refs_in_text(content[:5000])
    preview.append(preview_content)
    if len(content) > 5000:
        preview.append("\n... (truncated)", style="dim")
    return preview
