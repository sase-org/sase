"""MONITOR detail section rendering for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Callable

from rich.text import Text

from sase.ace.hooks.timestamps import format_duration
from sase.monitor.naming import short_monitor_id
from sase.monitor_state import (
    MONITOR_GLYPH,
    MONITOR_GLYPH_COLOR,
    MONITOR_TIMEOUT_GLYPH,
)

from ...models.agent import Agent
from ...models.agent_time import compute_row_runtime
from ...models.fold_scale import AGENT_FOLD_SCALE, FoldScale, effective_fold_level
from ...models.fold_state import FoldLevel
from ...util.axe_log_renderer import render_axe_output
from ...util.lazy_syntax import lazy_renderable
from ._agent_context_common import COLOR_EMPTY, COLOR_REASON, COLOR_SUMMARY
from ._agent_display_content import get_phase_label, render_phase_divider
from ._fold_language import append_fold_section_heading
from ._helpers import append_section_heading

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

MonitorTextAnnotator = Callable[[str | Text], Text]


def _field_label(label: str) -> str:
    return f"  {label:<{_FIELD_LABEL_WIDTH}}"


def _state_text(monitor_state: str | None) -> Text:
    glyph, style = _STATE_DISPLAY.get(monitor_state or "", ("?", "dim"))
    return Text(f"{glyph} {monitor_state or 'unknown'}", style=style)


def _monitor_output_source_id(agent: Agent) -> str:
    """Return the shared ``render_axe_output`` cache slot for ``agent``."""
    return f"monitor:{agent.monitor_id or agent.identity}"


def _monitor_field_parts(
    agent: Agent,
    *,
    annotate: MonitorTextAnnotator | None = None,
    prefix: Text | None = None,
) -> list[object]:
    """Return the MONITOR field block currently after the fold heading."""
    parts: list[object] = []
    text = prefix if prefix is not None else Text(end="")

    if agent.monitor_command:
        text.append(_field_label("Command:") + "\n", style=COLOR_SUMMARY)
        parts.append(text)
        if annotate is None:
            parts.append(lazy_renderable(agent.monitor_command, "bash"))
        else:
            parts.append(annotate(agent.monitor_command + "\n"))
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


def build_monitor_section(
    agent: Agent,
    *,
    panel_level: FoldLevel = FoldLevel.COLLAPSED,
    scale: FoldScale = AGENT_FOLD_SCALE,
    annotate: MonitorTextAnnotator | None = None,
) -> list[object]:
    """Return the MONITOR section renderables: heading, fields, and command.

    The monitored command is syntax-highlighted as shell, which ``lazy_renderable``
    may return as a ``Syntax`` object rather than plain ``Text`` — it is kept as its
    own list element (mirroring bash/python step rendering) instead of being merged
    into the surrounding ``Text`` buffer.
    """
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
    return _monitor_field_parts(agent, annotate=annotate, prefix=text)


def build_monitor_output(
    agent: Agent,
    *,
    heading: bool = True,
    annotate: MonitorTextAnnotator | None = None,
) -> list[object]:
    """Return the captured-output block for a monitor row or family phase."""
    output = agent.get_live_reply_content()
    if heading:
        header = Text()
        header.append("\n")
        header.append("─" * 50 + "\n", style="dim")
        header.append("\n")
        append_section_heading(header, "OUTPUT")
        if not output:
            header.append("No output yet.\n", style="dim italic")
            return [header]
        parts: list[object] = [header]
    else:
        header = Text(end="")
        header.append(_field_label("Output:") + "\n", style=COLOR_SUMMARY)
        if not output:
            header.append("No output yet.\n", style="dim italic")
            return [header]
        parts = [header]

    if agent.monitor_output_truncated:
        parts.append(
            Text(
                "… output truncated (head + tail retained) …\n",
                style="yellow",
            )
        )
    body: object = render_axe_output(
        _monitor_output_source_id(agent),
        output,
        "ansi",
    )
    if annotate is not None:
        body = annotate(body if isinstance(body, Text) else str(body))
    parts.append(body)
    return parts


def build_monitor_phase(
    agent: Agent,
    *,
    annotate: MonitorTextAnnotator | None = None,
) -> list[object]:
    """Return the family-facing MONITOR phase: divider, fields, and log."""
    parts: list[object] = [
        render_phase_divider(
            get_phase_label(agent),
            agent.run_start_time or agent.start_time,
            accent=MONITOR_GLYPH_COLOR,
            glyph=MONITOR_GLYPH,
        )
    ]
    parts.extend(_monitor_field_parts(agent, annotate=annotate))
    parts.extend(build_monitor_output(agent, heading=False, annotate=annotate))
    return parts


def monitor_phase_text(
    agent: Agent,
    *,
    annotate: MonitorTextAnnotator,
) -> Text:
    """Flatten ``build_monitor_phase`` into one ``Text`` for hint-mode append."""
    result = Text(end="")
    for part in build_monitor_phase(agent, annotate=annotate):
        if not isinstance(part, Text):
            raise TypeError(
                "monitor_phase_text requires annotate so every part is Text, "
                f"got {type(part).__name__}"
            )
        result.append_text(part)
    return result


__all__ = [
    "MONITOR_SECTION_ID",
    "MonitorTextAnnotator",
    "build_monitor_output",
    "build_monitor_phase",
    "build_monitor_section",
    "monitor_phase_text",
]
