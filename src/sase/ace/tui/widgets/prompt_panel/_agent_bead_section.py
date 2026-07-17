"""Responsive phase BEAD lane for the Agents metadata header."""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderResult
from rich.table import Table
from rich.text import Text

from ...models.agent_associated_plan import PhaseBeadSummary
from ._artifact_files import append_artifact_file_path
from ._agent_context_common import (
    COLOR_BEAD_PRIMARY,
    COLOR_BEAD_SUBHEADER,
    COLOR_EMPTY,
    COLOR_REASON,
    COLOR_SUMMARY,
    append_context_lane_header,
)

BEAD_SECTION_LABEL = "BEAD"
BEAD_SECTION_MAX_WIDTH = 80
BEAD_FIELD_LABEL_WIDTH = cell_len("  Description: ")
BEAD_PLAN_STATE_STYLE = "dim italic #FF8787"


@dataclass(slots=True)
class ResponsiveBeadSection:
    """One selected-phase lane that reflows complete values at render time."""

    summary: PhaseBeadSummary
    hint_number: int | None = None

    @property
    def logical_text(self) -> Text:
        """Return the unwrapped styled lane used by header inspection."""
        text = self._lane_header()
        for label, value in self._rows():
            text.append(label, style=COLOR_SUMMARY)
            text.append_text(value)
            text.append("\n")
        return text

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        yield self._lane_header()
        width = min(options.max_width, BEAD_SECTION_MAX_WIDTH)
        table = Table.grid(padding=0)
        table.add_column(width=BEAD_FIELD_LABEL_WIDTH, no_wrap=True)
        table.add_column(overflow="fold")
        for label, value in self._rows():
            value.overflow = "fold"
            value.no_wrap = False
            table.add_row(Text(label, style=COLOR_SUMMARY), value)
        yield from console.render(table, options.update_width(width))

    @staticmethod
    def _lane_header() -> Text:
        text = Text(end="")
        append_context_lane_header(
            text,
            BEAD_SECTION_LABEL,
            label_style=COLOR_BEAD_SUBHEADER,
            details="phase",
        )
        return text

    def _rows(self) -> tuple[tuple[str, Text], ...]:
        return (
            (self._label("ID"), Text(self.summary.id, style=COLOR_BEAD_PRIMARY)),
            (self._label("Description"), self._description_value()),
            (self._label("Epic Plan"), self._plan_value()),
            (self._label("Epic Title"), self._title_value()),
        )

    @staticmethod
    def _label(label: str) -> str:
        return f"  {label:>11}: "

    def _description_value(self) -> Text:
        if self.summary.description:
            return Text(self.summary.description, style=COLOR_REASON)
        return Text("unavailable", style=COLOR_EMPTY)

    def _plan_value(self) -> Text:
        if not self.summary.display_plan_path:
            return Text("unavailable", style=COLOR_EMPTY)

        text = Text()
        if self.hint_number is not None:
            text.append(f"[{self.hint_number}] ", style="bold #FFFF00")
        append_artifact_file_path(
            text,
            self.summary.display_plan_path,
            exists=self.summary.plan_exists,
        )
        if not self.summary.plan_exists:
            text.append(" (missing)", style=BEAD_PLAN_STATE_STYLE)
        elif not self.summary.plan_readable:
            text.append(" (unreadable)", style=BEAD_PLAN_STATE_STYLE)
        return text

    def _title_value(self) -> Text:
        if self.summary.epic_title:
            return Text(self.summary.epic_title, style=COLOR_BEAD_PRIMARY)
        return Text("unavailable", style=COLOR_EMPTY)
