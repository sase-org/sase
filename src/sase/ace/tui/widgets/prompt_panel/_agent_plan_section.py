"""Responsive PLAN lane for the Agents metadata header."""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderResult
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from sase.phase_size_presentation import (
    PHASE_SIZE_CHIP_WIDTH,
    phase_size_chip,
)
from sase.sdd.plan_display import (
    PLAN_FIELD_LABEL_WIDTH,
    PLAN_MISSING_SUFFIX_STYLE,
    PLAN_PHASE_ID_STYLE,
    PLAN_PHASE_MODEL_STYLE,
    PLAN_SECTION_LABEL,
    PLAN_SECTION_MAX_WIDTH,
    plan_field_rows,
    plan_lane_details,
    plan_lane_header,
    plan_logical_text,
    plan_phase_logical_text,
    plan_phase_metadata,
    plan_provenance_rows,
)

from ...models.agent_associated_plan import (
    AssociatedPlanPhaseSummary,
    AssociatedPlanSummary,
)
from ._agent_context_common import (
    COLOR_PLAN_PRIMARY,
    COLOR_PLAN_SUBHEADER,
    COLOR_REASON,
    COLOR_SUMMARY,
)


@dataclass(slots=True)
class ResponsivePlanSection:
    """One logical descriptive lane that reflows its fields at render time."""

    summary: AssociatedPlanSummary
    hint_number: int | None = None

    @property
    def logical_text(self) -> Text:
        """Return the unwrapped styled lane used by header inspection."""
        return plan_logical_text(self.summary, hint_number=self.hint_number)

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
        return plan_lane_header(self.summary)

    def _lane_details(self) -> Text:
        return plan_lane_details(self.summary)

    def _rows(self) -> tuple[tuple[str, Text], ...]:
        return (
            *plan_field_rows(self.summary, hint_number=self.hint_number),
            *plan_provenance_rows(self.summary),
        )

    @staticmethod
    def _logical_phase(
        ordinal: int,
        phase: AssociatedPlanPhaseSummary,
    ) -> Text:
        return plan_phase_logical_text(ordinal, phase)

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
        table = Table.grid(padding=0, expand=True)
        table.add_column(width=cell_len(ordinal_text), no_wrap=True)
        table.add_column(width=cell_len("◆ "), no_wrap=True)
        table.add_column(ratio=1, overflow="fold")
        table.add_column(width=PHASE_SIZE_CHIP_WIDTH, no_wrap=True)
        table.add_row(
            Text(ordinal_text, style=COLOR_SUMMARY),
            Text("◆ ", style=COLOR_PLAN_SUBHEADER),
            title,
            phase_size_chip(phase.size, width=PHASE_SIZE_CHIP_WIDTH),
        )
        return table

    @staticmethod
    def _phase_metadata(phase: AssociatedPlanPhaseSummary) -> Text:
        return plan_phase_metadata(phase)

    @staticmethod
    def _indented_phase_line(text: Text) -> Padding:
        return Padding(text, (0, 0, 0, 4), expand=False)
