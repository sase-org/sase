"""Grouped OptionList construction for the Artifacts Files pane."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from textual.widgets.option_list import Option

from sase.project_display_names import ProjectRefDisplaySnapshot

from .entry_navigation import (
    ArtifactEntryTarget,
    prepend_jump_hint,
    prepend_mark_glyph,
)
from .files_data import FilesSnapshot, LogicalFile
from .files_rendering import (
    file_group_header,
    file_group_label,
    file_row_text,
)


@dataclass(frozen=True, slots=True)
class FileRow:
    """Identity-preserving row backing one selectable file option."""

    option_id: str
    entry: LogicalFile


def file_row_target(row: FileRow) -> ArtifactEntryTarget:
    """Use the portable logical file identity as the navigation identity."""

    return ("file", row.entry.logical_id)


def build_file_options(
    snapshot: FilesSnapshot | None,
    *,
    project_scope: str | None,
    project_ref_display: ProjectRefDisplaySnapshot,
    loading: bool,
    now: datetime,
    jump_hints: Mapping[ArtifactEntryTarget, str] | None = None,
    marks: set[ArtifactEntryTarget] | None = None,
) -> tuple[list[Option], dict[str, FileRow]]:
    """Build newest-first date groups and their selectable row map."""

    active_marks = marks or set()
    if snapshot is None or snapshot.project != project_scope:
        label = "Loading artifact files…" if loading else "Files have not loaded yet."
        return [Option(label, disabled=True)], {}
    if not snapshot.rows:
        return [], {}

    options: list[Option] = []
    rows: dict[str, FileRow] = {}
    current_group: str | None = None
    for entry in snapshot.rows:
        group = file_group_label(entry, today=now)
        if group != current_group:
            options.append(
                Option(
                    file_group_header(group),
                    id=f"header:{group.casefold()}",
                    disabled=True,
                )
            )
            current_group = group
        option_id = f"file:{entry.logical_id}"
        row = FileRow(option_id, entry)
        rows[option_id] = row
        target = file_row_target(row)
        options.append(
            Option(
                prepend_jump_hint(
                    prepend_mark_glyph(
                        file_row_text(
                            entry,
                            view_mode=snapshot.view_mode_for(entry.latest),
                            projects=project_ref_display,
                        ),
                        target in active_marks,
                    ),
                    (jump_hints or {}).get(target),
                ),
                id=option_id,
            )
        )
    return options, rows


__all__ = ["FileRow", "build_file_options", "file_row_target"]
