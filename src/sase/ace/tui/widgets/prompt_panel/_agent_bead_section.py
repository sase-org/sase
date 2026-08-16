"""Responsive type-aware BEAD lane for the Agents metadata header."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderResult
from rich.table import Table
from rich.text import Text

from sase.bead_time_presentation import BEAD_TIME_RICH_STYLE, bead_created_label
from sase.bead_type_presentation import bead_type_presentation
from sase.bead_flag_presentation import flag_key_chip
from sase.bead.plus_one_presentation import (
    PLUS_ONE_RICH_STYLE,
    plus_one_badge,
    plus_one_evidence_label,
    plus_one_reports_label,
)
from sase.phase_size_presentation import phase_size_chip

from ...models.agent_associated_plan import BeadSummary
from ...models.fold_scale import FoldScale, fold_scale_position
from ...models.fold_state import FoldLevel
from ._artifact_files import append_artifact_file_path
from ._agent_context_common import (
    COLOR_BEAD_PRIMARY,
    COLOR_BEAD_SUBHEADER,
    COLOR_EMPTY,
    COLOR_REASON,
    COLOR_SUMMARY,
    COLOR_TRUNCATION,
    append_context_lane_header,
    count_phrase,
)
from ._fold_language import append_fold_glyph

BEAD_SECTION_ID = "bead"
BEAD_SECTION_LABEL = "BEAD"
BEAD_SECTION_MAX_WIDTH = 80
BEAD_FOLD_HINT = "zz to show"
_BEAD_FIELD_LABELS = (
    "Phase Title",
    "Flag Title",
    "Description",
    "Notes",
    "Epic Plan",
    "Epic Title",
    "Flag Key",
    "Remove By",
    "Size",
    "+1 Reports",
    "+1 Evidence",
    "Created",
)
BEAD_FIELD_LABEL_WIDTH = cell_len(f"  {max(_BEAD_FIELD_LABELS, key=len)}: ")
BEAD_PLAN_STATE_STYLE = "dim italic #FF8787"


class _BeadDetail(IntEnum):
    """Positional detail tiers owned by the BEAD lane."""

    DIGEST = 1
    FULL = 2


def bead_detail_level(level: FoldLevel, scale: FoldScale) -> _BeadDetail:
    """Resolve a sase-agent fold level to the positional BEAD detail tier."""
    position, _size = fold_scale_position(level, scale)
    return _BeadDetail.DIGEST if position == 1 else _BeadDetail.FULL


def bead_summary_has_foldable_rows(summary: BeadSummary) -> bool:
    """Return whether ``summary`` has BEAD log rows that can fold."""
    section = ResponsiveBeadSection(summary)
    return any(_value_is_foldable(value) for _label, value in section._foldable_rows())


def _value_is_foldable(value: Text) -> bool:
    return len(value.plain.splitlines()) > 1


@dataclass(slots=True)
class ResponsiveBeadSection:
    """One selected-bead lane that reflows complete values at render time."""

    summary: BeadSummary
    hint_number: int | None = None
    detail: _BeadDetail = _BeadDetail.FULL

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

    def _lane_header(self) -> Text:
        text = Text(end="")
        presentation = bead_type_presentation(self.summary.bead_type)
        details = Text()
        details.append(f"{presentation.glyph} ", style=presentation.rich_style)
        details.append(self.summary.bead_type, style=COLOR_SUMMARY)
        details.append(" ", style=COLOR_SUMMARY)
        details.append(self.summary.id, style=COLOR_BEAD_PRIMARY)
        if badge := plus_one_badge(self.summary.plus_one_count):
            details.append(f"  [{badge}]", style=PLUS_ONE_RICH_STYLE)
        append_context_lane_header(
            text,
            BEAD_SECTION_LABEL,
            label_style=COLOR_BEAD_SUBHEADER,
            details=details,
        )
        return text

    def _rows(self) -> tuple[tuple[str, Text], ...]:
        if self.summary.bead_type == "task":
            rows = [
                (self._label("Task Title"), self._bead_title_value()),
                (self._label("Description"), self._description_value()),
            ]
            if self.summary.notes and self.summary.notes.strip():
                rows.append(
                    (self._label("Notes"), self._foldable_value(self._notes_value()))
                )
            if self.summary.size is not None:
                rows.append((self._label("Size"), self._size_value()))
            if self.summary.plus_one_count:
                rows.append((self._label("+1 Reports"), self._plus_one_count_value()))
                rows.append(
                    (
                        self._label("+1 Evidence"),
                        self._foldable_value(self._plus_one_evidence_value()),
                    )
                )
            rows.append((self._label("Created"), self._created_value()))
            return tuple(rows)
        if self.summary.bead_type == "flag":
            rows = [
                (self._label("Flag Title"), self._bead_title_value()),
                (self._label("Description"), self._description_value()),
                (self._label("Flag Key"), self._flag_key_value()),
                (self._label("Remove By"), self._flag_removal_value()),
            ]
            if self.summary.notes and self.summary.notes.strip():
                rows.append(
                    (self._label("Notes"), self._foldable_value(self._notes_value()))
                )
            rows.append((self._label("Created"), self._created_value()))
            return tuple(rows)
        rows = [
            (self._label("Phase Title"), self._bead_title_value()),
            (self._label("Description"), self._description_value()),
        ]
        if self.summary.notes and self.summary.notes.strip():
            rows.append(
                (self._label("Notes"), self._foldable_value(self._notes_value()))
            )
        rows.extend(
            [
                (self._label("Size"), self._size_value()),
                (self._label("Epic Plan"), self._plan_value()),
                (self._label("Epic Title"), self._title_value()),
            ]
        )
        rows.append((self._label("Created"), self._created_value()))
        return tuple(rows)

    @staticmethod
    def _label(label: str) -> str:
        field_width = BEAD_FIELD_LABEL_WIDTH - cell_len("  : ")
        return f"  {label:>{field_width}}: "

    def _foldable_rows(self) -> tuple[tuple[str, Text], ...]:
        rows: list[tuple[str, Text]] = []
        if self.summary.notes and self.summary.notes.strip():
            rows.append((self._label("Notes"), self._notes_value()))
        if self.summary.bead_type == "task" and self.summary.plus_one_count:
            rows.append((self._label("+1 Evidence"), self._plus_one_evidence_value()))
        return tuple(rows)

    def _foldable_value(self, value: Text) -> Text:
        """Return ``value`` or its one-line folded digest for this detail tier."""
        if self.detail is not _BeadDetail.DIGEST:
            return value

        lines = value.plain.splitlines()
        # Fold the unbounded append-only logs, never identity fields. Single authored
        # lines stay inline even when they wrap visually, preserving lossless content.
        if len(lines) <= 1:
            return value

        text = Text()
        append_fold_glyph(text, FoldLevel.COLLAPSED)
        text.append(
            f"{count_phrase(len(lines), 'line')} ({BEAD_FOLD_HINT})",
            style=COLOR_TRUNCATION,
        )
        return text

    def _description_value(self) -> Text:
        if self.summary.description:
            return Text(self.summary.description, style=COLOR_REASON)
        return Text("unavailable", style=COLOR_EMPTY)

    def _notes_value(self) -> Text:
        return Text(self.summary.notes or "", style=COLOR_REASON)

    def _bead_title_value(self) -> Text:
        if self.summary.title:
            return Text(self.summary.title, style=COLOR_BEAD_PRIMARY)
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

    def _size_value(self) -> Text:
        return phase_size_chip(
            self.summary.size,
            unavailable_style=COLOR_EMPTY,
        )

    def _created_value(self) -> Text:
        return Text(
            bead_created_label(self.summary.created_at),
            style=BEAD_TIME_RICH_STYLE,
        )

    def _plus_one_count_value(self) -> Text:
        return Text(
            plus_one_reports_label(self.summary.plus_one_count),
            style=PLUS_ONE_RICH_STYLE,
        )

    def _plus_one_evidence_value(self) -> Text:
        text = Text()
        for index, evidence in enumerate(self.summary.plus_one_evidence):
            if index:
                text.append("\n\n")
            text.append(plus_one_evidence_label(evidence), style=PLUS_ONE_RICH_STYLE)
            text.append(f"\n{evidence.note}", style=COLOR_REASON)
            if evidence.refs:
                text.append(f"\nRefs: {', '.join(evidence.refs)}", style="dim #87AFFF")
        return text

    def _flag_key_value(self) -> Text:
        if self.summary.flag_key:
            return flag_key_chip(self.summary.flag_key)
        return Text("unavailable", style=COLOR_EMPTY)

    def _flag_removal_value(self) -> Text:
        parts = []
        if self.summary.flag_remove_by_date:
            parts.append(self.summary.flag_remove_by_date)
        if self.summary.flag_remove_by_release:
            parts.append(f"v{self.summary.flag_remove_by_release}")
        if parts:
            return Text(" · ".join(parts), style=COLOR_REASON)
        return Text("unavailable", style=COLOR_EMPTY)
