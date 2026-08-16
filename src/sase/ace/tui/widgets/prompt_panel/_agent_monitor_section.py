"""MONITOR detail section rendering for the agent prompt panel."""

from __future__ import annotations

from rich.text import Text

from sase.ace.hooks.timestamps import format_duration
from sase.monitor.naming import short_monitor_id
from sase.monitor_state import MONITOR_TIMEOUT_GLYPH

from ...models.agent import Agent
from ...models.agent_time import compute_row_runtime
from ...models.fold_scale import AGENT_FOLD_SCALE, FoldScale, effective_fold_level
from ...models.fold_state import FoldLevel
from ...util.lazy_syntax import lazy_renderable
from ._agent_context_common import COLOR_EMPTY, COLOR_REASON, COLOR_SUMMARY
from ._fold_language import append_fold_section_heading

MONITOR_SECTION_ID = "monitor"
_COLOR_HEADER = "bold #D7AF5F underline"
_FIELD_LABEL_WIDTH = 13

_STATE_DISPLAY: dict[str, tuple[str, str]] = {
    "running": ("●", "bold green"),
    "completed": ("✓", "bold cyan"),
    "failed": ("✗", "bold red"),
    "timeout": (MONITOR_TIMEOUT_GLYPH, "bold red"),
    "stopped": ("⊘", "bold magenta"),
    "lost": ("?", "bold red"),
}


def _field_label(label: str) -> str:
    return f"  {label:<{_FIELD_LABEL_WIDTH}}"


def _state_text(monitor_state: str | None) -> Text:
    glyph, style = _STATE_DISPLAY.get(monitor_state or "", ("?", "dim"))
    return Text(f"{glyph} {monitor_state or 'unknown'}", style=style)


def build_monitor_section(
    agent: Agent,
    *,
    panel_level: FoldLevel = FoldLevel.COLLAPSED,
    scale: FoldScale = AGENT_FOLD_SCALE,
) -> list[object]:
    """Return the MONITOR section renderables: heading, fields, and command.

    The monitored command is syntax-highlighted as shell, which ``lazy_renderable``
    may return as a ``Syntax`` object rather than plain ``Text`` — it is kept as its
    own list element (mirroring bash/python step rendering) instead of being merged
    into the surrounding ``Text`` buffer.
    """
    parts: list[object] = []
    text = Text(end="")
    level = effective_fold_level(panel_level, scale)
    heading = Text(end="")
    append_fold_section_heading(
        heading,
        "MONITOR",
        section_id=MONITOR_SECTION_ID,
        level=level,
        scale=scale,
        style=_COLOR_HEADER,
    )
    text.append_text(heading)

    if agent.monitor_command:
        text.append(_field_label("Command:") + "\n", style=COLOR_SUMMARY)
        parts.append(text)
        parts.append(lazy_renderable(agent.monitor_command, "bash"))
        text = Text(end="")

    if agent.monitor_cwd:
        text.append(_field_label("Cwd:"), style=COLOR_SUMMARY)
        text.append(f"{agent.monitor_cwd}\n", style=COLOR_REASON)
    if agent.monitor_reason:
        text.append(_field_label("Reason:"), style=COLOR_SUMMARY)
        text.append(f"{agent.monitor_reason}\n", style=COLOR_REASON)
    if agent.monitor_next_action:
        text.append(_field_label("Next action:"), style=COLOR_SUMMARY)
        text.append(f"{agent.monitor_next_action}\n", style=COLOR_REASON)

    text.append(_field_label("State:"), style=COLOR_SUMMARY)
    text.append_text(_state_text(agent.monitor_state))
    if agent.monitor_exit_code is not None:
        exit_style = "dim" if agent.monitor_exit_code == 0 else "bold red"
        text.append(f"  (exit {agent.monitor_exit_code})", style=exit_style)
    text.append("\n")

    _, elapsed = compute_row_runtime(agent)
    if agent.monitor_timeout_seconds is not None:
        timeout_label = format_duration(agent.monitor_timeout_seconds)
        text.append(_field_label("Timeout:"), style=COLOR_SUMMARY)
        text.append(f"{elapsed or '—'} of {timeout_label} budget\n", style=COLOR_REASON)
    elif elapsed:
        text.append(_field_label("Elapsed:"), style=COLOR_SUMMARY)
        text.append(f"{elapsed}\n", style=COLOR_REASON)
    if agent.monitor_idle_timeout_seconds is not None:
        idle_label = format_duration(agent.monitor_idle_timeout_seconds)
        text.append(_field_label("Idle timeout:"), style=COLOR_SUMMARY)
        text.append(f"{idle_label} without output\n", style=COLOR_REASON)

    if agent.monitor_id:
        text.append(_field_label("Monitor id:"), style=COLOR_SUMMARY)
        text.append(agent.monitor_id, style=COLOR_REASON)
        text.append(f"  ({short_monitor_id(agent.monitor_id)})\n", style="dim")
        text.append(_field_label(""), style=COLOR_SUMMARY)
        text.append(
            f"sase monitor show {short_monitor_id(agent.monitor_id)} --follow\n",
            style=COLOR_EMPTY,
        )

    parts.append(text)
    return parts


__all__ = ["MONITOR_SECTION_ID", "build_monitor_section"]
