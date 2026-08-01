"""Option reconciliation and summary rendering for the Beads pane."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Static

from sase.ace.tui.keymaps import KeymapRegistry
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.bead.filter_query import BeadFilterQueryError, BeadFilterValues
from sase.bead.filter_query import to_query_tokens

from .bead_filter_bar import BeadFilterBar
from .beads_data import BeadsSnapshot
from .beads_filtering import BeadFilterIndex, compile_bead_matcher
from .beads_list import BeadRow, build_bead_options
from .beads_rendering import (
    build_beads_hints,
    build_beads_scope,
    build_beads_status,
    build_empty_bead_detail,
)
from .entry_navigation import ArtifactEntryTarget

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
    from .beads_navigation import BeadsOptionList
else:
    _MixinBase = object


class BeadsOptionsMixin(_MixinBase):
    project_scope: str | None
    _project_display_name: str | None
    _registry: KeymapRegistry
    _snapshot: BeadsSnapshot | None
    _expanded_epics: set[tuple[str, str]]
    _loading: bool
    _load_error: str | None
    _rows: dict[str, BeadRow]
    filters: BeadFilterValues
    _filter_session_open: bool
    _filter_query_error: BeadFilterQueryError | None
    _entry_jump_hints: dict[ArtifactEntryTarget, str]
    _entry_marks: set[ArtifactEntryTarget]
    _detail_debouncer: DetailPanelDebouncer | None
    _syncing_options: bool
    _display_matched_counts: dict[str, int] | None
    _display_matched_triage_count: int | None

    if TYPE_CHECKING:

        def _display_filter_values(self) -> BeadFilterValues: ...

        def _ensure_filter_index(
            self,
            *,
            needed: bool,
        ) -> BeadFilterIndex | None: ...

        def _option_list(self) -> BeadsOptionList | None: ...

        def _selected_option_id(self) -> str | None: ...

        def _update_detail(self) -> None: ...

    def _init_beads_options(self) -> None:
        self._display_matched_counts = None
        self._display_matched_triage_count = None

    def _refresh_options(
        self,
        *,
        preferred_id: str | None = None,
        update_detail: bool = True,
    ) -> None:
        option_list = self._option_list()
        if option_list is None:
            return
        if preferred_id is None:
            preferred_id = self._selected_option_id()
        values = self._display_filter_values()
        matched_option_ids: frozenset[str] | None = None
        match_count: int | None = None
        self._display_matched_counts = None
        self._display_matched_triage_count = None
        filter_index = self._ensure_filter_index(
            needed=self._filter_session_open or not values.is_empty
        )
        if filter_index is not None:
            matcher = compile_bead_matcher(values)
            matching_records = tuple(
                record for record in filter_index if matcher(record)
            )
            match_count = len(matching_records)
            if not values.is_empty:
                matched_option_ids = frozenset(
                    record.option_id for record in matching_records
                )
                matched_counts = dict.fromkeys(("task", "epic", "phase"), 0)
                triage_count = 0
                for record in matching_records:
                    matched_counts[record.row_kind] += 1
                    if record.row_kind == "task" and "triage" in record.has_labels:
                        triage_count += 1
                self._display_matched_counts = matched_counts
                self._display_matched_triage_count = triage_count
        options, rows = build_bead_options(
            self._snapshot,
            project_scope=self.project_scope,
            loading=self._loading,
            expanded_epics=self._expanded_epics,
            jump_hints=self._entry_jump_hints,
            marks=self._entry_marks,
            matched_option_ids=matched_option_ids,
        )
        self._rows = rows
        target_index = next(
            (
                index
                for index, option in enumerate(options)
                if option.id == preferred_id
            ),
            None,
        )
        if target_index is None:
            target_index = next(
                (index for index, option in enumerate(options) if not option.disabled),
                None,
            )
        self._syncing_options = True
        try:
            option_list.replace_options(options, highlighted=target_index)
        finally:
            self._syncing_options = False
        self._update_static("#beads-status", self._status_text())
        self._update_static("#beads-info", self._scope_text())
        if self._filter_session_open and self._filter_query_error is None:
            self.query_one(BeadFilterBar).set_status(
                match_count,
                exact=True,
                error=None,
            )
        if update_detail:
            if self._detail_debouncer is None:
                self._update_detail()
            else:
                self._detail_debouncer.schedule(self._update_detail)

    def _scope_text(self) -> Any:
        return build_beads_scope(
            self._registry,
            project_scope=self.project_scope,
            project_display_name=self._project_display_name,
            filter_tokens=to_query_tokens(self.filters),
        )

    def _status_text(self) -> Any:
        return build_beads_status(
            self._snapshot,
            loading=self._loading,
            load_error=self._load_error,
            matched_counts=self._display_matched_counts,
            matched_triage_count=self._display_matched_triage_count,
        )

    def _hints_text(self) -> Any:
        return build_beads_hints(self._registry)

    def _empty_detail(self) -> str:
        return build_empty_bead_detail(
            self._snapshot,
            project_scope=self.project_scope,
            loading=self._loading,
            load_error=self._load_error,
        )

    def _update_static(self, selector: str, content: Any) -> None:
        if not self.is_mounted:
            return
        try:
            self.query_one(selector, Static).update(content)
        except Exception:
            pass


__all__ = ["BeadsOptionsMixin"]
