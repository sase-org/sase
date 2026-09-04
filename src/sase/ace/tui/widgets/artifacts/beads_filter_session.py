"""Live inline-filter session behavior for the Artifacts Beads pane."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.widgets.filter_bar import FilterBar
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
    from sase.ace.query_profile import CompiledQueryProfile
    from textual.containers import Vertical as _MixinBase

    from .entry_navigation import ArtifactEntryTarget
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
    _query_profile: CompiledQueryProfile

    if TYPE_CHECKING:

        def _refresh_options(
            self,
            *,
            preferred_id: str | None = None,
            update_detail: bool = True,
        ) -> None: ...

        def _selected_option_id(self) -> str | None: ...

        def selected_entry_target(self) -> ArtifactEntryTarget | None: ...

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

    def query_history_record(self) -> object:
        """Return the committed Beads query-history record."""
        from sase.ace.query_record import QueryRecord

        source = to_query_string(self.filters)
        return QueryRecord(
            source=source,
            canonical=source,
            profile_digest=getattr(self._query_profile, "digest", None),
        )

    def apply_query_history_record(self, record: object) -> bool:
        """Apply a validated query-history record to the Beads pane."""
        source = getattr(record, "source", "")
        try:
            values = parse_bead_filter_query(source)
        except BeadFilterQueryError:
            return False
        canonical = to_query_string(values)
        if canonical != getattr(record, "canonical", None):
            return False
        self._commit_beads_filter_values(values, record_history=False)
        return True

    def _record_query_history_transition(
        self,
        old_values: BeadFilterValues,
        new_values: BeadFilterValues,
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
            "beads",
            old_source=old_source,
            old_canonical=old_source,
            old_profile_digest=getattr(self._query_profile, "digest", None),
            new_canonical=new_source,
            selected_target=self.selected_entry_target(),
        )

    def _commit_beads_filter_values(
        self,
        values: BeadFilterValues,
        *,
        preferred_id: str | None = None,
        record_history: bool = True,
    ) -> None:
        if record_history:
            self._record_query_history_transition(self.filters, values)
        self.filters = values
        self._live_filter_values = values
        self._filter_query_error = None
        if self._filter_session_open:
            self.query_one(BeadFilterBar).set_query(to_query_string(values))
        self._cancel_jump_mode_for_filter_change()
        self._refresh_options(preferred_id=preferred_id)

    def on_filter_bar_clicked(self, event: FilterBar.Clicked) -> None:
        event.stop()
        self.show_filters()

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

        preferred_id = self._selected_option_id()
        self._commit_beads_filter_values(values, preferred_id=preferred_id)
        self._close_filter_session()
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
            return None
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
        query_index = getattr(self, "_query_index", None)
        if query_index is not None:
            self.query_one(BeadFilterBar).set_observed_facets(
                {
                    key: values
                    for key, values in query_index.facets.items()
                    if key not in {"since", "until"}
                }
            )

    def _cancel_jump_mode_for_filter_change(self) -> None:
        cancel = getattr(
            self.app,
            "_cancel_artifacts_jump_mode_for_model_change",
            None,
        )
        if callable(cancel):
            cancel("beads")

    def host_limit_query(self) -> str:
        """Return the live or committed Beads query used for ``limit:`` paging."""

        return to_query_string(self._display_filter_values())

    def apply_host_limit_query(self, query: str, *, grow: bool = False) -> None:
        """Commit a rewritten host-limit query without closing the editor.

        Beads always loads its full project store, so there is no bounded
        snapshot to grow; ``grow`` exists only to keep this signature
        uniform with the other panes' host-query adapter.
        """
        del grow
        from sase.ace.tui.actions.artifacts_limit import restore_selection_after_limit

        try:
            values = parse_bead_filter_query(query)
        except BeadFilterQueryError:
            return
        preferred_id = self._selected_option_id()
        preferred = self.selected_entry_target()
        self._commit_beads_filter_values(values, preferred_id=preferred_id)
        restore_selection_after_limit(self, preferred)  # type: ignore[arg-type]


__all__ = ["BeadsFilterSessionMixin"]
