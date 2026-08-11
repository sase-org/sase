"""Live inline-filter session behavior for the Artifacts Beads pane."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.bead.filter_query import (
    BeadFilterQueryError,
    BeadFilterValues,
    default_bead_filter_values,
    parse_bead_filter_query,
    to_query_string,
)

from .bead_filter_bar import BeadFilterBar
from .beads_data import BeadsSnapshot
from .beads_filtering import BeadFilterIndex, build_bead_filter_index

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class BeadsFilterSessionMixin(_MixinBase):
    """Own committed and live filters for the Beads pane."""

    project_scope: str | None
    filters: BeadFilterValues
    _snapshot: BeadsSnapshot | None
    _filter_index: BeadFilterIndex | None
    _filter_index_source_key: tuple[object, ...] | None
    _filter_session_open: bool
    _filter_restore_values: BeadFilterValues | None
    _filter_restore_selection: str | None
    _live_filter_values: BeadFilterValues | None
    _filter_query_error: BeadFilterQueryError | None

    if TYPE_CHECKING:

        def _refresh_options(
            self,
            *,
            preferred_id: str | None = None,
            update_detail: bool = True,
        ) -> None: ...

        def _selected_option_id(self) -> str | None: ...

        def focus_list(self) -> None: ...

    def _init_beads_filter_session(self) -> None:
        self.filters = default_bead_filter_values()
        self._filter_index = None
        self._filter_index_source_key = None
        self._filter_session_open = False
        self._filter_restore_values = None
        self._filter_restore_selection = None
        self._live_filter_values = None
        self._filter_query_error = None

    def show_filters(self) -> None:
        """Open and focus the inline Beads filter bar."""

        bar = self.query_one(BeadFilterBar)
        if self._filter_session_open:
            bar.query_one("#bead-filter-input").focus()
            return
        self._filter_session_open = True
        self._filter_restore_values = self.filters
        self._filter_restore_selection = self._selected_option_id()
        self._live_filter_values = self.filters
        self._filter_query_error = None
        self._ensure_filter_index(needed=True)
        self._set_filter_completion_sources()
        bar.open(to_query_string(self.filters))
        self._refresh_options(preferred_id=self._filter_restore_selection)

    def on_bead_filter_bar_query_changed(
        self,
        event: BeadFilterBar.QueryChanged,
    ) -> None:
        event.stop()
        try:
            values = parse_bead_filter_query(event.text)
        except BeadFilterQueryError as exc:
            self._filter_query_error = exc
            self.query_one(BeadFilterBar).set_status(None, exact=False, error=exc)
            return

        self._filter_query_error = None
        self._live_filter_values = values
        self._cancel_jump_mode_for_filter_change()
        self._refresh_options()

    def on_bead_filter_bar_submitted(
        self,
        event: BeadFilterBar.Submitted,
    ) -> None:
        event.stop()
        try:
            values = parse_bead_filter_query(event.text)
        except BeadFilterQueryError as exc:
            self._filter_query_error = exc
            self.query_one(BeadFilterBar).set_status(None, exact=False, error=exc)
            self.notify(exc.message, severity="error")
            return

        self.filters = values
        self._live_filter_values = values
        preferred_id = self._selected_option_id()
        self._close_filter_session()
        self._cancel_jump_mode_for_filter_change()
        self._refresh_options(preferred_id=preferred_id)
        self.focus_list()

    def on_bead_filter_bar_dismissed(
        self,
        event: BeadFilterBar.Dismissed,
    ) -> None:
        event.stop()
        restore_values = self._filter_restore_values
        restore_selection = self._filter_restore_selection
        if restore_values is not None:
            self.filters = restore_values
        self._close_filter_session()
        self._cancel_jump_mode_for_filter_change()
        self._refresh_options(preferred_id=restore_selection)
        self.focus_list()

    def _close_filter_session(self) -> None:
        self.query_one(BeadFilterBar).close()
        self._filter_session_open = False
        self._filter_restore_values = None
        self._filter_restore_selection = None
        self._live_filter_values = None
        self._filter_query_error = None

    def _display_filter_values(self) -> BeadFilterValues:
        if self._filter_session_open and self._live_filter_values is not None:
            return self._live_filter_values
        return self.filters

    def _ensure_filter_index(self, *, needed: bool) -> BeadFilterIndex | None:
        snapshot = self._snapshot
        if not needed or snapshot is None or snapshot.project != self.project_scope:
            return None
        if self._filter_index_source_key != snapshot.source_key:
            self._filter_index = build_bead_filter_index(snapshot)
            self._filter_index_source_key = snapshot.source_key
        return self._filter_index

    def _set_filter_completion_sources(self) -> None:
        index = self._ensure_filter_index(needed=True)
        if index is None:
            self.query_one(BeadFilterBar).set_completion_sources(
                projects=(),
                assignees=(),
                owners=(),
                models=(),
                bugs=(),
                labels=(),
            )
        return
        self.query_one(BeadFilterBar).set_completion_sources(
            projects=(
                value
                for record in index
                for value in (record.project, record.project_display_name)
            ),
            assignees=(record.assignee for record in index if record.assignee.strip()),
            owners=(record.owner for record in index if record.owner.strip()),
            models=(record.model for record in index if record.model.strip()),
            bugs=(value for record in index for value in record.bug_labels),
            labels=(value for record in index for value in record.issue_labels),
        )

    def _cancel_jump_mode_for_filter_change(self) -> None:
        cancel = getattr(
            self.app,
            "_cancel_artifacts_jump_mode_for_model_change",
            None,
        )
        if callable(cancel):
            cancel("beads")


__all__ = ["BeadsFilterSessionMixin"]
