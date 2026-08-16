"""Grouped OptionList construction for the Artifacts Files pane."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from textual.widgets.option_list import Option

from sase.project_display_names import ProjectRefDisplaySnapshot

from ..._artifact_tab_model import PaneGroupingModeDecl
from ...models.artifact_groups import ArtifactGroupBuildResult, build_grouped_rows
from ...models.group_fold import GroupFoldRegistry
from .entry_navigation import (
    ArtifactEntryTarget,
    prepend_jump_hint,
    prepend_mark_glyph,
)
from .files_data import FilesSnapshot, LogicalFile
from .files_rendering import file_row_text
from .group_banner import format_group_banner_option

FILES_PANE_ID = "files"

_ORIGIN_LABELS: dict[str, str] = {
    "ref": "Ref",
    "created": "Created",
    "capture": "Captured",
}


@dataclass(frozen=True, slots=True)
class FileRow:
    """Identity-preserving row backing one selectable file option."""

    option_id: str
    entry: LogicalFile


def file_row_target(row: FileRow) -> ArtifactEntryTarget:
    """Use the portable logical file identity as the navigation identity."""

    return ArtifactEntryTarget(pane_id=FILES_PANE_ID, parts=(row.entry.logical_id,))


def _file_key_value(entry: LogicalFile, mode_id: str) -> str:
    if mode_id == "by_source":
        return entry.latest.origin
    if mode_id == "by_kind":
        return entry.kind
    if mode_id == "by_project":
        return entry.projects[0] if entry.projects else ""
    return ""


def _file_group_label(
    mode_id: str,
    value: str,
    *,
    project_ref_display: ProjectRefDisplaySnapshot,
) -> str:
    if mode_id == "by_source":
        return _ORIGIN_LABELS.get(value, value.title() if value else "Unknown")
    if mode_id == "by_kind":
        return value.title() if value else "Unknown"
    if mode_id == "by_project":
        if not value:
            return "(no project)"
        return project_ref_display.display_snapshot.label_for(value)
    return value or "Unknown"


def build_grouped_file_rows(
    snapshot: FilesSnapshot,
    *,
    mode: PaneGroupingModeDecl,
    project_ref_display: ProjectRefDisplaySnapshot,
    fold_registry: GroupFoldRegistry | None = None,
) -> ArtifactGroupBuildResult[LogicalFile]:
    """Bucket already-loaded, newest-first file rows by the active mode."""

    return build_grouped_rows(
        snapshot.rows,
        pane_id=FILES_PANE_ID,
        mode_id=mode.id,
        keys=(mode.id,),
        key_values=lambda entry: (_file_key_value(entry, mode.id),),
        label_for=lambda _level, value: _file_group_label(
            mode.id, value, project_ref_display=project_ref_display
        ),
        target_for=lambda entry: ArtifactEntryTarget(
            pane_id=FILES_PANE_ID, parts=(entry.logical_id,)
        ),
        fold_registry=fold_registry,
    )


def build_file_options(
    snapshot: FilesSnapshot | None,
    *,
    project_scope: str | None,
    project_ref_display: ProjectRefDisplaySnapshot,
    loading: bool,
    mode: PaneGroupingModeDecl | None,
    fold_registry: GroupFoldRegistry | None,
    accent: str,
    jump_hints: Mapping[ArtifactEntryTarget, str] | None = None,
    marks: set[ArtifactEntryTarget] | None = None,
) -> tuple[list[Option], dict[str, FileRow], tuple[tuple[str, ...], ...]]:
    """Build grouped rows for the active mode and their selectable row map.

    Returns ``(options, rows, known_group_keys)``.
    """

    active_marks = marks or set()
    if snapshot is None or snapshot.project != project_scope:
        label = "Loading artifact files…" if loading else "Files have not loaded yet."
        return [Option(label, disabled=True)], {}, ()
    if not snapshot.rows:
        return [], {}, ()
    if mode is None:
        options: list[Option] = []
        rows: dict[str, FileRow] = {}
        for entry in snapshot.rows:
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
        return options, rows, ()

    result = build_grouped_file_rows(
        snapshot,
        mode=mode,
        project_ref_display=project_ref_display,
        fold_registry=fold_registry,
    )
    options = []
    rows = {}
    hints = jump_hints or {}
    for grouped_row in result.rows:
        if grouped_row.kind == "banner" and grouped_row.banner is not None:
            banner = grouped_row.banner
            options.append(
                format_group_banner_option(
                    banner,
                    accent=accent,
                    hint_char=hints.get(banner.target),
                )
            )
            continue
        grouped_entry = grouped_row.item
        assert grouped_entry is not None
        option_id = f"file:{grouped_entry.logical_id}"
        row = FileRow(option_id, grouped_entry)
        rows[option_id] = row
        target = file_row_target(row)
        options.append(
            Option(
                prepend_jump_hint(
                    prepend_mark_glyph(
                        file_row_text(
                            grouped_entry,
                            view_mode=snapshot.view_mode_for(grouped_entry.latest),
                            projects=project_ref_display,
                        ),
                        target in active_marks,
                    ),
                    hints.get(target),
                ),
                id=option_id,
            )
        )
    return options, rows, result.known_group_keys


__all__ = [
    "FILES_PANE_ID",
    "FileRow",
    "build_file_options",
    "build_grouped_file_rows",
    "file_row_target",
]
