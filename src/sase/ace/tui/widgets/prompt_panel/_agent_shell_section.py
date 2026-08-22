"""Responsive per-shell lanes for family container detail panels."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderResult
from rich.table import Table
from rich.text import Text

from sase.llm_provider.model_label import model_value_text
from sase.monitor_state import MONITOR_GLYPH, MONITOR_GLYPH_COLOR

from ...models.agent import Agent
from ...models.agent_family_members import concrete_family_member_rows
from .._agent_list_styling import _AGENT_NAME_ANNOTATION_STYLE, _STEP_TYPE_COLORS
from ._agent_context_common import (
    COLOR_EMPTY,
    COLOR_REASON,
    REASON_GLYPH,
    normalize_context_display,
)
from ._agent_display_family import family_member_label
from ._helpers import PROMPT_PANEL_LINE_CELL_LIMIT, wrap_text_by_cells

SHELL_SECTION_ID = "shells"
SHELL_FIELD_LABEL = "Shells: "
SHELL_FIELD_LABEL_STYLE = "bold #87D7FF"
SHELL_LANE_LIMIT = 12
_SHELL_LANE_LABEL_STYLE = _AGENT_NAME_ANNOTATION_STYLE
_SHELL_LANE_SEPARATOR = " · "
_SHELL_LANE_SEPARATOR_STYLE = "dim"
_SHELL_LANE_DEFAULT_STYLE = "dim #AF87D7"
_SHELL_LANE_TAIL_STYLE = "dim italic"
_SHELL_MONITOR_GLYPH_STYLE = f"bold {MONITOR_GLYPH_COLOR}"
_SHELL_MONITOR_COMMAND_STYLE = _STEP_TYPE_COLORS["bash"]
_SHELL_MONITOR_REASON_MARKER_STYLE = f"bold {COLOR_REASON}"
_SHELL_MONITOR_COMMAND_MARKER_STYLE = f"bold {_SHELL_MONITOR_COMMAND_STYLE}"
_SHELL_MONITOR_PLACEHOLDER = "unavailable"
_SHELL_CONTINUATION_INDENT = 2


@dataclass(frozen=True, slots=True)
class _AgentShellLane:
    """One concrete LLM agent shell in a family metadata lane."""

    label: str
    value: Text


@dataclass(frozen=True, slots=True)
class _MonitorShellLane:
    """One proc-shell monitor lane in a family metadata lane."""

    label: str
    command: str | None
    reason: str | None


type ShellLane = _AgentShellLane | _MonitorShellLane


@dataclass(frozen=True, slots=True)
class _MonitorSelection:
    marker: str
    marker_style: str
    continuation: str | None
    continuation_style: str


def build_family_shell_lanes(agent: Agent) -> tuple[ShellLane, ...]:
    """Build one labelled shell lane per concrete family shell."""
    family_name = agent.presented_agent_name or ""
    lanes: list[ShellLane] = []
    for member in concrete_family_member_rows(agent):
        label = family_member_label(member, family_name)
        if member.is_monitor:
            lanes.append(
                _MonitorShellLane(
                    label=label,
                    command=member.monitor_command,
                    reason=member.monitor_reason,
                )
            )
            continue

        value = model_value_text(
            member.model,
            member.llm_provider,
            member.reasoning_effort,
            member.model_alias,
        )
        if value is None:
            value = Text("default", style=_SHELL_LANE_DEFAULT_STYLE)
        lanes.append(_AgentShellLane(label=label, value=value))
    if not lanes and agent.is_family_container_row:
        value = model_value_text(
            agent.model,
            agent.llm_provider,
            agent.reasoning_effort,
            agent.model_alias,
        )
        if value is None:
            value = Text("default", style=_SHELL_LANE_DEFAULT_STYLE)
        lanes.append(
            _AgentShellLane(label=family_member_label(agent, family_name), value=value)
        )
    return tuple(lanes)


def _shell_gutter_width(lanes: Sequence[ShellLane]) -> int:
    """Return the padded width of the widest present shell label."""
    if not lanes:
        return 0
    return max(cell_len(lane.label) for lane in lanes)


def _lane_prefix(index: int, label: str, gutter_width: int) -> Text:
    prefix = Text(end="")
    if index == 0:
        prefix.append(SHELL_FIELD_LABEL, style=SHELL_FIELD_LABEL_STYLE)
    else:
        prefix.append(" " * cell_len(SHELL_FIELD_LABEL))
    prefix.append(label, style=_SHELL_LANE_LABEL_STYLE)
    prefix.append(" " * (gutter_width - cell_len(label)))
    prefix.append(_SHELL_LANE_SEPARATOR, style=_SHELL_LANE_SEPARATOR_STYLE)
    return prefix


def _lane_prefix_width(gutter_width: int) -> int:
    return cell_len(SHELL_FIELD_LABEL) + gutter_width + cell_len(_SHELL_LANE_SEPARATOR)


def _normalized_command(command: str | None) -> str:
    return "" if command is None else command.strip()


def _single_physical_line(value: str) -> bool:
    return "\n" not in value and "\r" not in value


def _monitor_command_width(total_width: int, gutter_width: int) -> int:
    prefix_width = _lane_prefix_width(gutter_width)
    glyph_width = cell_len(f"{MONITOR_GLYPH} ")
    return max(1, total_width - prefix_width - glyph_width)


def _monitor_reason_payload_width(total_width: int) -> int:
    payload_prefix_width = (
        cell_len(SHELL_FIELD_LABEL)
        + _SHELL_CONTINUATION_INDENT
        + cell_len(REASON_GLYPH)
        + 1
    )
    return max(1, total_width - payload_prefix_width)


def _monitor_selection(
    lane: _MonitorShellLane,
    *,
    total_width: int,
    gutter_width: int,
) -> _MonitorSelection:
    command = _normalized_command(lane.command)
    if (
        command
        and _single_physical_line(command)
        and cell_len(command) <= _monitor_command_width(total_width, gutter_width)
    ):
        return _MonitorSelection(
            marker=command,
            marker_style=_SHELL_MONITOR_COMMAND_STYLE,
            continuation=None,
            continuation_style=COLOR_REASON,
        )

    reason = normalize_context_display(lane.reason or "")
    if reason:
        return _MonitorSelection(
            marker="why",
            marker_style=_SHELL_MONITOR_REASON_MARKER_STYLE,
            continuation=reason,
            continuation_style=COLOR_REASON,
        )

    diagnostic = normalize_context_display(command)
    if diagnostic:
        return _MonitorSelection(
            marker="cmd",
            marker_style=_SHELL_MONITOR_COMMAND_MARKER_STYLE,
            continuation=diagnostic,
            continuation_style=_SHELL_MONITOR_COMMAND_STYLE,
        )

    return _MonitorSelection(
        marker=_SHELL_MONITOR_PLACEHOLDER,
        marker_style=COLOR_EMPTY,
        continuation=None,
        continuation_style=COLOR_EMPTY,
    )


def _append_monitor_lane(
    text: Text,
    *,
    index: int,
    lane: _MonitorShellLane,
    gutter_width: int,
    total_width: int,
) -> None:
    selection = _monitor_selection(
        lane,
        total_width=total_width,
        gutter_width=gutter_width,
    )
    text.append_text(_lane_prefix(index, lane.label, gutter_width))
    text.append(MONITOR_GLYPH, style=_SHELL_MONITOR_GLYPH_STYLE)
    text.append(" ")
    text.append(selection.marker, style=selection.marker_style)
    text.append("\n")
    if selection.continuation is None:
        return

    payload_width = _monitor_reason_payload_width(total_width)
    wrapped = wrap_text_by_cells(selection.continuation, payload_width)
    if not wrapped:
        return
    arrow_indent = cell_len(SHELL_FIELD_LABEL) + _SHELL_CONTINUATION_INDENT
    payload_indent = arrow_indent + cell_len(REASON_GLYPH) + 1
    text.append(" " * arrow_indent)
    text.append(REASON_GLYPH, style=selection.continuation_style)
    text.append(" ")
    text.append(wrapped[0], style=selection.continuation_style)
    text.append("\n")
    for line in wrapped[1:]:
        text.append(" " * payload_indent)
        text.append(line, style=selection.continuation_style)
        text.append("\n")


def _append_agent_lane(
    text: Text,
    *,
    index: int,
    lane: _AgentShellLane,
    gutter_width: int,
) -> None:
    text.append_text(_lane_prefix(index, lane.label, gutter_width))
    text.append_text(lane.value)
    text.append("\n")


def _logical_shell_text(
    lanes: Sequence[ShellLane],
    *,
    hidden_count: int,
    total_width: int,
) -> Text:
    gutter_width = _shell_gutter_width(lanes)
    text = Text(end="")
    for index, lane in enumerate(lanes):
        if isinstance(lane, _AgentShellLane):
            _append_agent_lane(
                text,
                index=index,
                lane=lane,
                gutter_width=gutter_width,
            )
        else:
            _append_monitor_lane(
                text,
                index=index,
                lane=lane,
                gutter_width=gutter_width,
                total_width=total_width,
            )
    if hidden_count > 0:
        text.append(" " * cell_len(SHELL_FIELD_LABEL))
        text.append(
            f"… +{hidden_count} more shells (see FAMILY MEMBERS)",
            style=_SHELL_LANE_TAIL_STYLE,
        )
        text.append("\n")
    return text


@dataclass(slots=True)
class ResponsiveShellSection:
    """Per-shell family lanes that wrap beneath aligned shell metadata."""

    lanes: tuple[ShellLane, ...]
    hidden_count: int = 0

    @property
    def logical_text(self) -> Text:
        """Return the styled shell block used for inspection."""
        return _logical_shell_text(
            self.lanes,
            hidden_count=self.hidden_count,
            total_width=PROMPT_PANEL_LINE_CELL_LIMIT,
        )

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        gutter_width = _shell_gutter_width(self.lanes)
        for index, lane in enumerate(self.lanes):
            if isinstance(lane, _MonitorShellLane):
                text = Text(end="")
                _append_monitor_lane(
                    text,
                    index=index,
                    lane=lane,
                    gutter_width=gutter_width,
                    total_width=options.max_width,
                )
                yield text
                continue

            value = lane.value.copy()
            value.overflow = "fold"
            value.no_wrap = False
            table = Table.grid(padding=0)
            table.add_column(width=cell_len(SHELL_FIELD_LABEL), no_wrap=True)
            table.add_column(
                width=gutter_width + cell_len(_SHELL_LANE_SEPARATOR),
                no_wrap=True,
            )
            table.add_column(overflow="fold")
            label_text = (
                Text(SHELL_FIELD_LABEL, style=SHELL_FIELD_LABEL_STYLE)
                if index == 0
                else Text()
            )
            gutter_text = Text()
            gutter_text.append(lane.label, style=_SHELL_LANE_LABEL_STYLE)
            gutter_text.append(" " * (gutter_width - cell_len(lane.label)))
            gutter_text.append(
                _SHELL_LANE_SEPARATOR,
                style=_SHELL_LANE_SEPARATOR_STYLE,
            )
            table.add_row(label_text, gutter_text, value)
            yield from console.render(table, options)
        if self.hidden_count > 0:
            table = Table.grid(padding=0)
            table.add_column(width=cell_len(SHELL_FIELD_LABEL), no_wrap=True)
            table.add_column(
                width=gutter_width + cell_len(_SHELL_LANE_SEPARATOR),
                no_wrap=True,
            )
            table.add_column(overflow="fold")
            tail = Text(
                f"… +{self.hidden_count} more shells (see FAMILY MEMBERS)",
                style=_SHELL_LANE_TAIL_STYLE,
            )
            table.add_row(Text(), Text(), tail)
            yield from console.render(table, options)


__all__ = [
    "SHELL_FIELD_LABEL",
    "SHELL_LANE_LIMIT",
    "SHELL_SECTION_ID",
    "ResponsiveShellSection",
    "ShellLane",
    "build_family_shell_lanes",
]
