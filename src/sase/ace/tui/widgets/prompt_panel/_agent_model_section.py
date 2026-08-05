"""Responsive per-member model lanes for family container detail panels."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderResult
from rich.table import Table
from rich.text import Text

from sase.llm_provider.model_label import model_value_text

from ...models.agent import Agent
from ...models.agent_family_members import concrete_family_member_rows
from .._agent_list_styling import _AGENT_NAME_ANNOTATION_STYLE
from ._agent_display_family import family_member_label

MODEL_SECTION_ID = "model"
MODEL_FIELD_LABEL = "Model: "
MODEL_FIELD_LABEL_STYLE = "bold #87D7FF"
MODEL_LANE_LIMIT = 12
_MODEL_LANE_LABEL_STYLE = _AGENT_NAME_ANNOTATION_STYLE
_MODEL_LANE_SEPARATOR_STYLE = "dim"
_MODEL_LANE_DEFAULT_STYLE = "dim #AF87D7"
_MODEL_LANE_TAIL_STYLE = "dim italic"

type ModelLane = tuple[str, Text]


def build_family_model_lanes(agent: Agent) -> tuple[ModelLane, ...]:
    """Build one labelled model lane per concrete family member.

    Returns an empty tuple when the family projects to fewer than two
    members, signalling the caller to fall back to the single-line field.
    """
    family_name = agent.presented_agent_name or ""
    members = concrete_family_member_rows(agent)
    if len(members) < 2:
        return ()

    lanes: list[ModelLane] = []
    for member in members:
        label = family_member_label(member, family_name)
        value = model_value_text(
            member.model, member.llm_provider, member.reasoning_effort
        )
        if value is None:
            value = Text("default", style=_MODEL_LANE_DEFAULT_STYLE)
        lanes.append((label, value))
    return tuple(lanes)


def _model_gutter_width(lanes: Sequence[ModelLane]) -> int:
    """Return the padded width of the widest present member label."""
    if not lanes:
        return 0
    return max(cell_len(label) for label, _value in lanes)


@dataclass(slots=True)
class ResponsiveModelSection:
    """Per-member model lanes that wrap beneath one aligned value column."""

    lanes: tuple[ModelLane, ...]
    hidden_count: int = 0

    @property
    def logical_text(self) -> Text:
        """Return the styled, unwrapped model block used for inspection."""
        gutter_width = _model_gutter_width(self.lanes)
        text = Text(end="")
        for index, (label, value) in enumerate(self.lanes):
            if index == 0:
                text.append(MODEL_FIELD_LABEL, style=MODEL_FIELD_LABEL_STYLE)
            else:
                text.append(" " * cell_len(MODEL_FIELD_LABEL))
            text.append(label, style=_MODEL_LANE_LABEL_STYLE)
            text.append(" " * (gutter_width - cell_len(label)))
            text.append(" · ", style=_MODEL_LANE_SEPARATOR_STYLE)
            text.append_text(value)
            text.append("\n")
        if self.hidden_count > 0:
            text.append(" " * cell_len(MODEL_FIELD_LABEL))
            text.append(
                f"… +{self.hidden_count} more members (see FAMILY MEMBERS)",
                style=_MODEL_LANE_TAIL_STYLE,
            )
            text.append("\n")
        return text

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        gutter_width = _model_gutter_width(self.lanes)
        for index, (label, value) in enumerate(self.lanes):
            value.overflow = "fold"
            value.no_wrap = False
            table = Table.grid(padding=0)
            table.add_column(width=cell_len(MODEL_FIELD_LABEL), no_wrap=True)
            table.add_column(width=gutter_width + 3, no_wrap=True)
            table.add_column(overflow="fold")
            label_text = (
                Text(MODEL_FIELD_LABEL, style=MODEL_FIELD_LABEL_STYLE)
                if index == 0
                else Text()
            )
            gutter_text = Text()
            gutter_text.append(label, style=_MODEL_LANE_LABEL_STYLE)
            gutter_text.append(" " * (gutter_width - cell_len(label)))
            gutter_text.append(" · ", style=_MODEL_LANE_SEPARATOR_STYLE)
            table.add_row(label_text, gutter_text, value)
            yield from console.render(table, options)
        if self.hidden_count > 0:
            table = Table.grid(padding=0)
            table.add_column(width=cell_len(MODEL_FIELD_LABEL), no_wrap=True)
            table.add_column(width=gutter_width + 3, no_wrap=True)
            table.add_column(overflow="fold")
            tail = Text(
                f"… +{self.hidden_count} more members (see FAMILY MEMBERS)",
                style=_MODEL_LANE_TAIL_STYLE,
            )
            table.add_row(Text(), Text(), tail)
            yield from console.render(table, options)


__all__ = [
    "MODEL_FIELD_LABEL",
    "MODEL_LANE_LIMIT",
    "MODEL_SECTION_ID",
    "ModelLane",
    "ResponsiveModelSection",
    "build_family_model_lanes",
]
