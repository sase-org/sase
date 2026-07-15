"""Responsive SASE PLAN section for the Agents metadata header."""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderResult
from rich.table import Table
from rich.text import Text

from ...models.agent_associated_plan import AssociatedPlanSummary
from ._agent_artifacts import append_artifact_path
from ._helpers import append_major_section_divider

PLAN_SECTION_LABEL = "SASE PLAN"
PLAN_SECTION_MAX_WIDTH = 80
PLAN_FIELD_LABEL_WIDTH = cell_len("Goal: ")
PLAN_FIELD_LABEL_STYLE = "bold #87D7FF"
PLAN_GOAL_VALUE_STYLE = "italic #FFD787"
PLAN_SECTION_HEADING_STYLE = "bold #D7AF5F underline"
PLAN_UNAVAILABLE_STYLE = "dim italic #878787"
PLAN_MISSING_SUFFIX_STYLE = "dim italic #FF8787"
PLAN_TIER_STYLES = {
    "plan": "bold #5FD7FF",
    "epic": "bold #AF87FF",
    "none": "italic #8787AF",
}


@dataclass(frozen=True, slots=True)
class ResponsivePlanSection:
    """One logical section that reflows its fields at render time."""

    summary: AssociatedPlanSummary
    hint_number: int | None = None

    @property
    def logical_text(self) -> Text:
        """Return the unwrapped styled section used by header inspection."""
        text = self._heading()
        for label, value in self._rows():
            text.append(label, style=PLAN_FIELD_LABEL_STYLE)
            text.append_text(value)
            text.append("\n")
        return text

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        yield self._heading(width=options.max_width)
        width = min(options.max_width, PLAN_SECTION_MAX_WIDTH)
        table = Table.grid(padding=0)
        table.add_column(width=PLAN_FIELD_LABEL_WIDTH, no_wrap=True)
        table.add_column(overflow="fold")
        for label, value in self._rows():
            value.overflow = "fold"
            value.no_wrap = False
            table.add_row(Text(label, style=PLAN_FIELD_LABEL_STYLE), value)
        yield from console.render(table, options.update_width(width))

    @staticmethod
    def _heading(*, width: int | None = None) -> Text:
        text = Text()
        if width is None:
            append_major_section_divider(text)
        else:
            text.append("\n")
            text.append("─" * min(50, max(1, width)) + "\n", style="dim")
            text.append("\n")
        text.append(f"{PLAN_SECTION_LABEL}\n", style=PLAN_SECTION_HEADING_STYLE)
        text.append("\n")
        return text

    def _rows(self) -> tuple[tuple[str, Text], ...]:
        return (
            ("Goal: ", self._goal_value()),
            ("Tier: ", self._tier_value()),
            ("Path: ", self._path_value()),
        )

    def _goal_value(self) -> Text:
        if self.summary.goal:
            return Text(self.summary.goal, style=PLAN_GOAL_VALUE_STYLE)
        return Text("unavailable", style=PLAN_UNAVAILABLE_STYLE)

    def _tier_value(self) -> Text:
        tier = self.summary.effective_tier
        if tier is None:
            return Text("unavailable", style=PLAN_UNAVAILABLE_STYLE)
        return Text(tier, style=PLAN_TIER_STYLES[tier])

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
