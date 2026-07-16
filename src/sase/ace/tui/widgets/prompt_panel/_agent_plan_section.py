"""Responsive PLAN lane for the Agents metadata header."""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderResult
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from ...models.agent_associated_plan import (
    AssociatedPlanPhaseSummary,
    AssociatedPlanSummary,
)
from ._agent_artifacts import append_artifact_path
from ._agent_context_common import (
    COLOR_EMPTY,
    COLOR_PLAN_PRIMARY,
    COLOR_PLAN_SUBHEADER,
    COLOR_REASON,
    COLOR_SUMMARY,
    append_context_lane_header,
    count_phrase,
)

PLAN_SECTION_LABEL = "PLAN"
PLAN_SECTION_MAX_WIDTH = 80
PLAN_FIELD_LABEL_WIDTH = cell_len("  Title: ")
PLAN_MISSING_SUFFIX_STYLE = "dim italic #FF8787"
PLAN_PHASE_ID_STYLE = "#AF87FF"
PLAN_PHASE_MODEL_STYLE = "italic #AF87FF"


@dataclass(slots=True)
class ResponsivePlanSection:
    """One logical descriptive lane that reflows its fields at render time."""

    summary: AssociatedPlanSummary
    hint_number: int | None = None

    @property
    def logical_text(self) -> Text:
        """Return the unwrapped styled lane used by header inspection."""
        text = self._lane_header()
        for label, value in self._rows():
            text.append(label, style=COLOR_SUMMARY)
            text.append_text(value)
            text.append("\n")
        if self.summary.phase_availability == "available":
            for ordinal, phase in enumerate(self.summary.phases, start=1):
                text.append_text(self._logical_phase(ordinal, phase))
        return text

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        yield self._lane_header()
        width = min(options.max_width, PLAN_SECTION_MAX_WIDTH)
        table = Table.grid(padding=0)
        table.add_column(width=PLAN_FIELD_LABEL_WIDTH, no_wrap=True)
        table.add_column(overflow="fold")
        for label, value in self._rows():
            value.overflow = "fold"
            value.no_wrap = False
            table.add_row(Text(label, style=COLOR_SUMMARY), value)
        yield from console.render(table, options.update_width(width))
        render_options = options.update_width(width)
        if self.summary.phase_availability != "available":
            return

        for ordinal, phase in enumerate(self.summary.phases, start=1):
            title_table = self._phase_title_table(ordinal, phase)
            yield from console.render(title_table, render_options)
            yield from console.render(
                self._indented_phase_line(self._phase_metadata(phase)),
                render_options,
            )
            if phase.description:
                yield from console.render(
                    self._indented_phase_line(
                        Text(
                            phase.description,
                            style=COLOR_REASON,
                            overflow="fold",
                            no_wrap=False,
                        )
                    ),
                    render_options,
                )

    def _lane_header(self) -> Text:
        text = Text(end="")
        append_context_lane_header(
            text,
            PLAN_SECTION_LABEL,
            label_style=COLOR_PLAN_SUBHEADER,
            details=self._lane_details(),
        )
        return text

    def _lane_details(self) -> Text:
        text = Text()
        tier = self.summary.effective_tier
        if tier is None:
            text.append("tier unavailable", style=COLOR_EMPTY)
            return text

        text.append(tier, style=COLOR_SUMMARY)
        if self.summary.phase_availability == "available":
            text.append(" · ", style=COLOR_SUMMARY)
            text.append(
                count_phrase(len(self.summary.phases), "phase"),
                style=COLOR_SUMMARY,
            )
        elif self.summary.phase_availability != "not-applicable":
            text.append(" · ", style=COLOR_SUMMARY)
            text.append("phases unavailable", style=COLOR_EMPTY)
        return text

    def _rows(self) -> tuple[tuple[str, Text], ...]:
        return (
            ("  Title: ", self._title_value()),
            ("   Goal: ", self._goal_value()),
            ("   Path: ", self._path_value()),
        )

    def _title_value(self) -> Text:
        if self.summary.title:
            text = Text()
            text.append(self.summary.title, style=COLOR_PLAN_PRIMARY)
            return text
        return Text("unavailable", style=COLOR_EMPTY)

    def _goal_value(self) -> Text:
        if self.summary.goal:
            return Text(self.summary.goal, style=COLOR_REASON)
        return Text("unavailable", style=COLOR_EMPTY)

    def _path_value(self) -> Text:
        text = Text()
        if self.hint_number is not None:
            text.append(f"[{self.hint_number}] ", style="bold #FFFF00")
        append_artifact_path(
            text,
            self.summary.display_path,
            exists=self.summary.exists,
        )
        if not self.summary.exists:
            text.append(" (missing)", style=PLAN_MISSING_SUFFIX_STYLE)
        return text

    @staticmethod
    def _logical_phase(
        ordinal: int,
        phase: AssociatedPlanPhaseSummary,
    ) -> Text:
        text = Text()
        text.append(f"  {ordinal} ", style=COLOR_SUMMARY)
        text.append("◆ ", style=COLOR_PLAN_SUBHEADER)
        text.append(phase.title, style=COLOR_PLAN_PRIMARY)
        text.append("\n")
        text.append("    ")
        text.append_text(ResponsivePlanSection._phase_metadata(phase))
        text.append("\n")
        if phase.description:
            text.append("    ")
            text.append(phase.description, style=COLOR_REASON)
            text.append("\n")
        return text

    @staticmethod
    def _phase_title_table(
        ordinal: int,
        phase: AssociatedPlanPhaseSummary,
    ) -> Table:
        ordinal_text = f"  {ordinal} "
        title = Text(
            phase.title,
            style=COLOR_PLAN_PRIMARY,
            overflow="fold",
            no_wrap=False,
        )
        table = Table.grid(padding=0)
        table.add_column(width=cell_len(ordinal_text), no_wrap=True)
        table.add_column(width=cell_len("◆ "), no_wrap=True)
        table.add_column(overflow="fold")
        table.add_row(
            Text(ordinal_text, style=COLOR_SUMMARY),
            Text("◆ ", style=COLOR_PLAN_SUBHEADER),
            title,
        )
        return table

    @staticmethod
    def _phase_metadata(phase: AssociatedPlanPhaseSummary) -> Text:
        text = Text(phase.id, style=PLAN_PHASE_ID_STYLE)
        text.append(" · ", style=COLOR_SUMMARY)
        if phase.depends_on:
            text.append(
                f"after {', '.join(phase.depends_on)}",
                style=COLOR_SUMMARY,
            )
        else:
            text.append("no dependencies", style=COLOR_SUMMARY)
        if phase.model:
            text.append(" · model ", style=COLOR_SUMMARY)
            text.append(phase.model, style=PLAN_PHASE_MODEL_STYLE)
        text.overflow = "fold"
        text.no_wrap = False
        return text

    @staticmethod
    def _indented_phase_line(text: Text) -> Padding:
        return Padding(text, (0, 0, 0, 4), expand=False)
