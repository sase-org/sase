"""Logical-file, version, and entry selection for the Artifacts Files pane."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from sase.ace.tui.graphics._viewer_types import ArtifactViewMode
from sase.core.artifact_file_types import ArtifactFile

from .entry_navigation import ArtifactEntryTarget
from .files_data import (
    FileVersion,
    FilesSnapshot,
    LogicalFile,
    selected_file_version_to_artifact_file,
)
from .files_list import FileRow, file_row_target

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class FilesSelectionMixin(_MixinBase):
    """Own the highlighted logical file and which of its versions is active."""

    _rows: dict[str, FileRow]
    _selected_version_indices: dict[str, int]
    _detail_generation: int

    if TYPE_CHECKING:

        def selected_row(self) -> FileRow | None: ...

        def selected_entry_target(self) -> ArtifactEntryTarget | None: ...

        def _current_snapshot(self) -> FilesSnapshot | None: ...

        def _refresh_options(
            self,
            *,
            preferred_target: ArtifactEntryTarget | None = None,
        ) -> None: ...

        def _schedule_detail(self) -> None: ...

    def _init_files_selection(self) -> None:
        self._selected_version_indices = {}

    @property
    def selected_logical_file(self) -> LogicalFile | None:
        row = self.selected_row()
        return None if row is None else row.entry

    @property
    def selected_version(self) -> FileVersion | None:
        logical = self.selected_logical_file
        if logical is None:
            return None
        return logical.versions[self.selected_version_index(logical)]

    @property
    def selected_entry(self) -> ArtifactFile | None:
        version = self.selected_version
        return (
            None if version is None else selected_file_version_to_artifact_file(version)
        )

    @property
    def selected_view_mode(self) -> ArtifactViewMode | None:
        """Return the selected row's cached terminal-viewer classification."""

        entry = self.selected_version
        snapshot = self._current_snapshot()
        if entry is None or snapshot is None:
            return None
        return snapshot.view_mode_for(entry)

    def entries_for_targets(
        self,
        targets: Iterable[ArtifactEntryTarget],
    ) -> tuple[ArtifactFile, ...]:
        """Resolve visible stable targets to rows while preserving caller order."""

        entries = {file_row_target(row): row.entry for row in self._rows.values()}
        result = []
        for target in targets:
            logical = entries.get(target)
            if logical is None:
                continue
            result.append(
                selected_file_version_to_artifact_file(
                    logical.versions[self.selected_version_index(logical)]
                )
            )
        return tuple(result)

    def selected_version_index(self, logical: LogicalFile | None = None) -> int:
        logical = logical or self.selected_logical_file
        if logical is None:
            return 0
        index = self._selected_version_indices.get(
            logical.logical_id,
            len(logical.versions) - 1,
        )
        return max(0, min(index, len(logical.versions) - 1))

    def select_version(self, step: int) -> bool:
        logical = self.selected_logical_file
        if logical is None or len(logical.versions) <= 1:
            return False
        before = self.selected_version_index(logical)
        after = (before + step) % len(logical.versions)
        self._selected_version_indices[logical.logical_id] = after
        self._detail_generation += 1
        self._schedule_detail()
        self._refresh_options(preferred_target=self.selected_entry_target())
        return after != before

    def _reset_version_indices(self, rows: Iterable[LogicalFile]) -> None:
        """Clamp remembered version choices onto freshly loaded rows."""

        self._selected_version_indices = {
            row.logical_id: min(
                self._selected_version_indices.get(
                    row.logical_id,
                    len(row.versions) - 1,
                ),
                len(row.versions) - 1,
            )
            for row in rows
        }


__all__ = ["FilesSelectionMixin"]
