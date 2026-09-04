"""Live inline-filter session behavior for the Artifacts Files pane."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast

from sase.ace.tui.widgets.filter_bar import FilterBar
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
    from sase.ace.query_profile import CompiledQueryProfile
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
    _query_profile: CompiledQueryProfile

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
        from sase.ace.config import get_ace_page_size
        from sase.ace.query.limit_token import ensure_limit

        self.filters = parse_files_filter_query(ensure_limit("", get_ace_page_size()))
        self._filter_session_open = False
        self._filter_restore_values = None
        self._filter_restore_selection = None
        self._live_filter_values = None
        self._filter_query_error = None

    def query_history_record(self) -> object:
        """Return the committed Files query-history record."""
        from sase.ace.query_record import QueryRecord

        source = to_query_string(self.filters)
        return QueryRecord(
            source=source,
            canonical=source,
            profile_digest=getattr(self._query_profile, "digest", None),
        )

    def apply_query_history_record(self, record: object) -> bool:
        """Apply a validated query-history record to the Files pane."""
        source = getattr(record, "source", "")
        try:
            values = parse_files_filter_query(source)
        except FilesFilterQueryError:
            return False
        canonical = to_query_string(values)
        if canonical != getattr(record, "canonical", None):
            return False
        self._commit_files_filter_values(values, record_history=False)
        return True

    def _record_query_history_transition(
        self,
        old_values: FilesFilterValues,
        new_values: FilesFilterValues,
    ) -> None:
        recorder = getattr(
            getattr(self, "app", None),
            "_record_artifacts_query_transition",
            None,
        )
        if not callable(recorder):
            return
        old_source = to_query_string(old_values)
        new_source = to_query_string(new_values)
        recorder(
            "files",
            old_source=old_source,
            old_canonical=old_source,
            old_profile_digest=getattr(self._query_profile, "digest", None),
            new_canonical=new_source,
            selected_target=self.selected_entry_target(),
        )

    def _commit_files_filter_values(
        self,
        values: FilesFilterValues,
        *,
        preferred_target: ArtifactEntryTarget | None = None,
        grow: bool = False,
        record_history: bool = True,
    ) -> None:
        if record_history:
            self._record_query_history_transition(self.filters, values)
        self.filters = values
        self._live_filter_values = values
        self._filter_query_error = None
        if self._filter_session_open:
            self.query_one(FileFilterBar).set_query(to_query_string(values))
        self._cancel_jump_mode_for_filter_change()
        if grow:
            self._maybe_grow_files_snapshot(values.limit)
        self._refresh_options(preferred_target=preferred_target)

    def on_filter_bar_clicked(self, event: FilterBar.Clicked) -> None:
        event.stop()
        self.show_filters()

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
        preferred = self.selected_entry_target()
        self._commit_files_filter_values(values, preferred_target=preferred)
        self._close_filter_session()
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
        values = replace(
            self.filters,
            kinds=(() if next_value is None else (next_value,)),
        )
        self._commit_files_filter_values(values)
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

    def close_host_filter_session(self) -> None:
        """Close the inline Files filter editor before a host query rewrite."""
        if self._filter_session_open:
            self._close_filter_session()

    def _cancel_jump_mode_for_filter_change(self) -> None:
        cancel = getattr(
            self.app,
            "_cancel_artifacts_jump_mode_for_model_change",
            None,
        )
        if callable(cancel):
            cancel("files")

    def host_limit_query(self) -> str:
        """Return the live or committed Files query used for ``limit:`` paging."""

        return to_query_string(self._display_filter_values())

    def apply_host_limit_query(self, query: str, *, grow: bool = False) -> None:
        """Commit a rewritten host-limit query and grow the snapshot if needed."""

        from sase.ace.tui.actions.artifacts_limit import restore_selection_after_limit

        try:
            values = parse_files_filter_query(query)
        except FilesFilterQueryError:
            return
        preferred = self.selected_entry_target()
        self._commit_files_filter_values(
            values,
            preferred_target=preferred,
            grow=grow,
        )
        restore_selection_after_limit(self, preferred)  # type: ignore[arg-type]

    def _maybe_grow_files_snapshot(self, cap: int | None) -> None:
        """Request the full index when the cap outruns the loaded first page."""

        snapshot = getattr(self, "_snapshot", None)
        request_load = getattr(self, "_request_load", None)
        if snapshot is None or not callable(request_load):
            return
        if snapshot.complete or snapshot.load_error:
            return
        if cap is None or cap > len(snapshot.rows):
            request_load(force=False, full=True)


__all__ = ["FilesFilterSessionMixin"]
