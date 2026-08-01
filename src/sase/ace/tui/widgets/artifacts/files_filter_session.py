"""Live inline-filter session behavior for the Artifacts Files pane."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast

from sase.core.artifact_file_types import ARTIFACT_FILE_KINDS

from .entry_navigation import ArtifactEntryTarget
from .file_filter_bar import FileFilterBar
from .files_filtering import (
    FilesFilterQueryError,
    FilesFilterValues,
    parse_files_filter_query,
    to_query_string,
)

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class FilesFilterSessionMixin(_MixinBase):
    """Own committed/live filters and stored-kind cycling."""

    filters: FilesFilterValues
    _filter_session_open: bool
    _filter_restore_values: FilesFilterValues | None
    _filter_restore_selection: ArtifactEntryTarget | None
    _live_filter_values: FilesFilterValues | None
    _filter_query_error: FilesFilterQueryError | None

    if TYPE_CHECKING:

        def _refresh_options(
            self,
            *,
            preferred_target: ArtifactEntryTarget | None = None,
        ) -> None: ...

        def selected_entry_target(self) -> ArtifactEntryTarget | None: ...

        def focus_list(self) -> None: ...

        def _set_filter_completion_sources(self) -> None: ...

    def _init_files_filter_session(self) -> None:
        self.filters = FilesFilterValues()
        self._filter_session_open = False
        self._filter_restore_values = None
        self._filter_restore_selection = None
        self._live_filter_values = None
        self._filter_query_error = None

    def show_filters(self) -> None:
        """Open and focus the inline Files filter bar."""

        bar = self.query_one(FileFilterBar)
        if self._filter_session_open:
            bar.query_one("#file-filter-input").focus()
            return
        self._filter_session_open = True
        self._filter_restore_values = self.filters
        self._filter_restore_selection = self.selected_entry_target()
        self._live_filter_values = self.filters
        self._filter_query_error = None
        self._set_filter_completion_sources()
        bar.open(to_query_string(self.filters))
        self._refresh_options(preferred_target=self._filter_restore_selection)

    def on_file_filter_bar_query_changed(
        self,
        event: FileFilterBar.QueryChanged,
    ) -> None:
        event.stop()
        try:
            values = parse_files_filter_query(event.text)
        except FilesFilterQueryError as exc:
            self._filter_query_error = exc
            self.query_one(FileFilterBar).set_status(
                None,
                exact=False,
                error=exc,
            )
            return
        self._filter_query_error = None
        self._live_filter_values = values
        self._cancel_jump_mode_for_filter_change()
        self._refresh_options()

    def on_file_filter_bar_submitted(
        self,
        event: FileFilterBar.Submitted,
    ) -> None:
        event.stop()
        try:
            values = parse_files_filter_query(event.text)
        except FilesFilterQueryError as exc:
            self._filter_query_error = exc
            self.query_one(FileFilterBar).set_status(
                None,
                exact=False,
                error=exc,
            )
            self.notify(exc.message, severity="error")
            return
        self.filters = values
        self._live_filter_values = values
        preferred = self.selected_entry_target()
        self._close_filter_session()
        self._cancel_jump_mode_for_filter_change()
        self._refresh_options(preferred_target=preferred)
        self.focus_list()

    def on_file_filter_bar_dismissed(
        self,
        event: FileFilterBar.Dismissed,
    ) -> None:
        event.stop()
        restore = self._filter_restore_values
        preferred = self._filter_restore_selection
        if restore is not None:
            self.filters = restore
        self._close_filter_session()
        self._cancel_jump_mode_for_filter_change()
        self._refresh_options(preferred_target=preferred)
        self.focus_list()

    def cycle_kind(self) -> None:
        """Cycle All through only the stored kinds present in the snapshot."""

        snapshot = getattr(self, "_snapshot", None)
        present = {row.kind for row in (() if snapshot is None else snapshot.rows)}
        available = tuple(kind for kind in ARTIFACT_FILE_KINDS if kind in present)
        current = self.filters.kinds[0] if len(self.filters.kinds) == 1 else None
        if not available:
            next_value: str | None = None
        elif current not in available:
            next_value = available[0]
        else:
            index = available.index(cast(str, current))
            next_value = available[index + 1] if index + 1 < len(available) else None
        if self._filter_session_open:
            self._close_filter_session()
        self.filters = replace(
            self.filters,
            kinds=(() if next_value is None else (next_value,)),
        )
        self._cancel_jump_mode_for_filter_change()
        self._refresh_options()
        self.focus_list()

    def _display_filter_values(self) -> FilesFilterValues:
        if self._filter_session_open and self._live_filter_values is not None:
            return self._live_filter_values
        return self.filters

    def _close_filter_session(self) -> None:
        self.query_one(FileFilterBar).close()
        self._filter_session_open = False
        self._filter_restore_values = None
        self._filter_restore_selection = None
        self._live_filter_values = None
        self._filter_query_error = None

    def _cancel_jump_mode_for_filter_change(self) -> None:
        cancel = getattr(
            self.app,
            "_cancel_artifacts_jump_mode_for_model_change",
            None,
        )
        if callable(cancel):
            cancel("other")


__all__ = ["FilesFilterSessionMixin"]
