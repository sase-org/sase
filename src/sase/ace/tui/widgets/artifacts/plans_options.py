"""Option-list reconciliation and summary rendering for the plans pane."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.keymaps import KeymapRegistry
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.plan_search.filter_query import PlanFilterQueryError, PlanFilterValues
from sase.plan_search.filter_query import to_query_string, to_query_tokens
from sase.core.query_profile_corpus_facade import ArtifactQueryIndex

from .entry_navigation import ArtifactEntryTarget
from .plan_filter_bar import PlanFilterBar
from .plans_data import PlansSnapshot, ProjectArchive
from .plans_deep_archive import (
    DeepArchiveResult,
    deep_archive_coverage,
    merge_archive_matches,
)
from .plans_filtering import PlanFilterIndex
from .plans_list import PlanRow, build_plan_options, plan_row_target, row_option_id
from .plans_rendering import (
    build_empty_plan_detail,
    build_plans_hints,
    build_plans_scope,
    build_plans_status,
)
from .query_session import ArtifactQuerySession
from .types import ARTIFACTS_ACCENTS, ArtifactsPaneContract

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase

    from .plans_navigation import PlansOptionList
else:
    _MixinBase = object


class PlansOptionsMixin(_MixinBase):
    """Own list rebuilding, match counts, and pane summary text."""

    contract: ArtifactsPaneContract | None
    project_scope: str | None
    provider_label: str
    filters: PlanFilterValues
    _project_display_name: str | None
    _registry: KeymapRegistry
    _snapshot: PlansSnapshot | None
    _filter_session_open: bool
    _filter_query_error: PlanFilterQueryError | None
    _live_filter_values: PlanFilterValues | None
    _loading: bool
    _load_error: str | None
    _rows: dict[str, PlanRow]
    _entry_jump_hints: dict[ArtifactEntryTarget, str]
    _entry_marks: set[ArtifactEntryTarget]
    _pending_entry_target: ArtifactEntryTarget | None
    _detail_debouncer: DetailPanelDebouncer | None
    _syncing_options: bool
    _display_matched_counts: dict[str, int] | None
    _display_archive_total: int | None
    _display_archive_coverage_label: str | None
    _query_index: ArtifactQueryIndex | None
    _query_session: ArtifactQuerySession

    if TYPE_CHECKING:

        def _deep_archive_result_for(
            self,
            values: PlanFilterValues,
        ) -> DeepArchiveResult | None: ...

        def _display_filter_values(self) -> PlanFilterValues: ...

        def _ensure_filter_index(
            self,
            *,
            needed: bool,
        ) -> PlanFilterIndex | None: ...

        def _filter_coverage(
            self,
            values: PlanFilterValues,
        ) -> tuple[bool, str | None]: ...

        def _invalidate_deep_archive_request(self) -> None: ...

        def _close_filter_session(self) -> None: ...

        def _sync_artifacts_footer(self) -> None: ...

        def _first_selectable_index(self) -> int | None: ...

        def _option_index(self, option_id: str | None) -> int | None: ...

        def _option_list(self) -> PlansOptionList | None: ...

        def _selected_option_id(self) -> str | None: ...

        def _update_detail(self) -> None: ...

    def _init_plans_options(self) -> None:
        self._display_matched_counts = None
        self._display_archive_total = None
        self._display_archive_coverage_label = None

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
        archive_entries: tuple[ProjectArchive, ...] | None = None
        self._display_matched_counts = None
        self._display_archive_total = None
        self._display_archive_coverage_label = None
        match_count: int | None = None
        matched_ids: frozenset[str] = frozenset()
        pending_query = False
        filter_index = self._ensure_filter_index(
            needed=self._filter_session_open or not values.is_empty
        )
        if filter_index is not None:
            query_index = self._query_index
            query = to_query_string(values)
            result = (
                None
                if query_index is None or not query
                else self._query_session.result(query, query_index)
            )
            if result is not None:
                matched_ids = frozenset(result.matched_row_ids)
                matching_records = tuple(
                    record for record in filter_index if record.option_id in matched_ids
                )
                match_count = len(matching_records)
            elif values.is_empty:
                matching_records = tuple(filter_index)
                matched_ids = frozenset(record.option_id for record in matching_records)
                match_count = len(matching_records)
            else:
                matching_records = ()
                match_count = None
                pending_query = True
            deep_result = self._deep_archive_result_for(values)
            if deep_result is not None and self._snapshot is not None:
                non_archive_records = tuple(
                    record for record in matching_records if record.kind != "archive"
                )
                preview_archive_ids = frozenset(
                    record.option_id
                    for record in matching_records
                    if record.kind == "archive"
                )
                preview_archive = tuple(
                    item
                    for item in self._snapshot.archive
                    if row_option_id(
                        self._snapshot,
                        "archive",
                        item.project,
                        item.match.plan.path,
                    )
                    in preview_archive_ids
                )
                deep_archive = tuple(
                    item
                    for item in deep_result.archive
                    if row_option_id(
                        self._snapshot,
                        "archive",
                        item.project,
                        item.match.plan.path,
                    )
                    in matched_ids
                )
                archive_entries = merge_archive_matches(
                    preview_archive,
                    deep_archive,
                )
                match_count = len(non_archive_records) + len(archive_entries)
                self._display_archive_total = max(
                    deep_result.scanned_count,
                    len(archive_entries),
                )
                _, coverage_label = deep_archive_coverage(
                    self._snapshot,
                    values,
                    deep_result,
                )
                self._display_archive_coverage_label = (
                    "" if deep_result.exact else coverage_label or "preview"
                )
                if not values.is_empty:
                    matched_option_ids = frozenset(
                        record.option_id for record in non_archive_records
                    ).union(
                        row_option_id(
                            self._snapshot,
                            "archive",
                            item.project,
                            item.match.plan.path,
                        )
                        for item in archive_entries
                    )
                    matched_counts = dict.fromkeys(("proposal", "active", "archive"), 0)
                    for record in non_archive_records:
                        matched_counts[record.kind] += 1
                    matched_counts["archive"] = len(archive_entries)
                    self._display_matched_counts = matched_counts
            if (
                not values.is_empty
                and matched_option_ids is None
                and match_count is not None
            ):
                matched_option_ids = frozenset(
                    record.option_id for record in matching_records
                )
                matched_counts = dict.fromkeys(("proposal", "active", "archive"), 0)
                for record in matching_records:
                    matched_counts[record.kind] += 1
                self._display_matched_counts = matched_counts
        if pending_query:
            if self._filter_session_open and self._filter_query_error is None:
                exact, coverage_label = self._filter_coverage(values)
                self.query_one(PlanFilterBar).set_status(
                    None,
                    exact=False,
                    error=None,
                    coverage_label=coverage_label if not exact else None,
                )
            return
        options, rows = build_plan_options(
            self._snapshot,
            project_scope=self.project_scope,
            loading=self._loading,
            jump_hints=self._entry_jump_hints,
            marks=self._entry_marks,
            matched_option_ids=matched_option_ids,
            archive_entries=archive_entries,
            archive_total=self._display_archive_total,
            accent=self._accent(),
        )
        self._rows = rows
        pending_id = self._pending_option_id()
        if pending_id is None and self._pending_entry_target is not None:
            if not values.is_empty and self._clear_filter_for_entry_jump():
                self._notify_filter_cleared_for_entry_jump()
                self._refresh_options(
                    preferred_id=preferred_id,
                    update_detail=update_detail,
                )
                return
            if self._loaded_current_snapshot():
                self._notify_pending_entry_missing()
        if pending_id is not None:
            preferred_id = pending_id
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
        if pending_id is not None:
            self._pending_entry_target = None
        self._update_status()
        self._update_static("#plans-info", self._scope_text())
        if self._filter_session_open and self._filter_query_error is None:
            exact, coverage_label = self._filter_coverage(values)
            self.query_one(PlanFilterBar).set_status(
                match_count,
                exact=exact and match_count is not None,
                error=None,
                coverage_label=coverage_label,
            )
        if update_detail:
            if self._detail_debouncer is None or (
                not self._filter_session_open and values.is_empty
            ):
                self._update_detail()
            else:
                self._detail_debouncer.schedule(self._update_detail)
        self._sync_artifacts_footer()

    def _accent(self) -> str:
        contract = self.contract
        return ARTIFACTS_ACCENTS["plans"] if contract is None else contract.accent

    def _scope_text(self) -> Text:
        return build_plans_scope(
            self._registry,
            project_scope=self.project_scope,
            project_display_name=self._project_display_name,
            filter_tokens=to_query_tokens(self.filters),
            provider_label=self.provider_label,
            accent=self._accent(),
        )

    def _status_text(self) -> Text:
        return build_plans_status(
            self._snapshot,
            loading=self._loading,
            load_error=self._load_error,
            matched_counts=self._display_matched_counts,
            archive_total=self._display_archive_total,
            archive_coverage_label=self._display_archive_coverage_label,
            accent=self._accent(),
        )

    def _hints_text(self) -> Text:
        return build_plans_hints(self._registry, accent=self._accent())

    def _empty_detail(self) -> str:
        matched_total = (
            None
            if self._display_matched_counts is None
            else sum(self._display_matched_counts.values())
        )
        return build_empty_plan_detail(
            self._snapshot,
            project_scope=self.project_scope,
            loading=self._loading,
            load_error=self._load_error,
            has_active_filter=not self.filters.is_empty,
            matched_total=matched_total,
        )

    def _update_status(self) -> None:
        self._update_static("#plans-status", self._status_text())

    def _update_static(self, selector: str, content: Any) -> None:
        if not self.is_mounted:
            return
        try:
            self.query_one(selector, Static).update(content)
        except Exception:
            pass

    def _pending_option_id(self) -> str | None:
        target = self._pending_entry_target
        if target is None:
            return None
        return next(
            (
                option_id
                for option_id, row in self._rows.items()
                if plan_row_target(row) == target
            ),
            None,
        )

    def _clear_filter_for_entry_jump(self) -> bool:
        if self.filters.is_empty and not self._filter_session_open:
            return False
        self.filters = PlanFilterValues()
        self._filter_query_error = None
        self._invalidate_deep_archive_request()
        if self._filter_session_open:
            self._close_filter_session()
        else:
            self._live_filter_values = None
        return True

    def _notify_filter_cleared_for_entry_jump(self) -> None:
        notify = getattr(self, "notify", None)
        if callable(notify):
            notify("Cleared Plans filter to show linked plan")

    def _notify_pending_entry_missing(self) -> None:
        self._pending_entry_target = None
        notify = getattr(self, "notify", None)
        if callable(notify):
            notify("Linked plan is no longer visible in Plans", severity="warning")

    def _loaded_current_snapshot(self) -> bool:
        return (
            self._snapshot is not None
            and self._snapshot.project == self.project_scope
            and not self._loading
        )


__all__ = ["PlansOptionsMixin"]
