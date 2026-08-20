"""Live filter-session and deep-archive behavior for the plans pane."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.widgets.filter_bar import FilterBar
from sase.plan_search.filter_query import (
    PlanFilterQueryError,
    PlanFilterValues,
    parse_plan_filter_query,
    to_query_string,
)

from .plan_filter_bar import PlanFilterBar
from .plans_data import PlansSnapshot
from .plans_deep_archive import (
    DeepArchiveRequest,
    DeepArchiveResult,
    deep_archive_coverage,
    load_deep_archive_result,
    make_deep_archive_request,
    remember_deep_archive_result,
)
from .plans_filtering import PlanFilterIndex

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class PlansFilterSessionMixin(_MixinBase):
    """Own inline filtering and full archive search orchestration."""

    project_scope: str | None
    filters: PlanFilterValues
    _snapshot: PlansSnapshot | None
    _filter_index: PlanFilterIndex | None
    _filter_index_snapshot: PlansSnapshot | None
    _filter_session_open: bool
    _filter_restore_values: PlanFilterValues | None
    _filter_restore_selection: str | None
    _live_filter_values: PlanFilterValues | None
    _filter_query_error: PlanFilterQueryError | None
    _deep_archive_debouncer: DetailPanelDebouncer | None
    _deep_archive_worker: Worker[DeepArchiveResult] | None
    _deep_archive_request: DeepArchiveRequest | None
    _deep_archive_in_flight: DeepArchiveRequest | None
    _deep_archive_pending: DeepArchiveRequest | None
    _deep_archive_cache: dict[DeepArchiveRequest, DeepArchiveResult]
    _display_archive_total: int | None
    _display_archive_coverage_label: str | None
    _query_profile: Any
    _query_index: Any
    _query_session: Any
    contract: Any
    _load_generation: int

    if TYPE_CHECKING:

        def _refresh_options(
            self,
            *,
            preferred_id: str | None = None,
            update_detail: bool = True,
        ) -> None: ...

        def _selected_option_id(self) -> str | None: ...

        def focus_list(self) -> None: ...

    def _init_plans_filter_session(self) -> None:
        from sase.ace.config import get_ace_page_size
        from sase.ace.query.limit_token import ensure_limit

        self.filters = parse_plan_filter_query(ensure_limit("", get_ace_page_size()))
        self._filter_index = None
        self._filter_index_snapshot = None
        self._filter_session_open = False
        self._filter_restore_values = None
        self._filter_restore_selection = None
        self._live_filter_values = None
        self._filter_query_error = None
        self._deep_archive_debouncer = None
        self._deep_archive_worker = None
        self._deep_archive_request = None
        self._deep_archive_in_flight = None
        self._deep_archive_pending = None
        self._deep_archive_cache = {}

    def on_filter_bar_clicked(self, event: FilterBar.Clicked) -> None:
        event.stop()
        self.show_filters()

    def show_filters(self) -> None:
        """Open and focus the inline plans filter bar."""
        bar = self.query_one(PlanFilterBar)
        if self._filter_session_open:
            bar.query_one("#plan-filter-input").focus()
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
        self._schedule_deep_archive(self.filters)

    def on_plan_filter_bar_query_changed(
        self,
        event: PlanFilterBar.QueryChanged,
    ) -> None:
        event.stop()
        try:
            values = parse_plan_filter_query(event.text)
        except PlanFilterQueryError as exc:
            self._filter_query_error = exc
            self._invalidate_deep_archive_request()
            self.query_one(PlanFilterBar).set_status(
                None,
                exact=False,
                error=exc,
            )
            return

        self._filter_query_error = None
        self._live_filter_values = values
        self._cancel_jump_mode_for_filter_change()
        self._refresh_options()
        self._schedule_deep_archive(values)

    def on_plan_filter_bar_submitted(
        self,
        event: PlanFilterBar.Submitted,
    ) -> None:
        event.stop()
        try:
            values = parse_plan_filter_query(event.text)
        except PlanFilterQueryError as exc:
            self._filter_query_error = exc
            self._invalidate_deep_archive_request()
            self.query_one(PlanFilterBar).set_status(
                None,
                exact=False,
                error=exc,
            )
            self.notify(exc.message, severity="error")
            return

        self.filters = values
        self._live_filter_values = values
        preferred_id = self._selected_option_id()
        self._close_filter_session()
        self._cancel_jump_mode_for_filter_change()
        self._refresh_options(preferred_id=preferred_id)
        self._schedule_deep_archive(values)
        self.focus_list()

    def on_plan_filter_bar_dismissed(
        self,
        event: PlanFilterBar.Dismissed,
    ) -> None:
        event.stop()
        restore_values = self._filter_restore_values
        restore_selection = self._filter_restore_selection
        if restore_values is not None:
            self.filters = restore_values
        self._invalidate_deep_archive_request()
        self._close_filter_session()
        self._cancel_jump_mode_for_filter_change()
        self._refresh_options(preferred_id=restore_selection)
        self._schedule_deep_archive(self.filters)
        self.focus_list()

    def _close_filter_session(self) -> None:
        self.query_one(PlanFilterBar).close()
        self._filter_session_open = False
        self._filter_restore_values = None
        self._filter_restore_selection = None
        self._live_filter_values = None
        self._filter_query_error = None

    def _display_filter_values(self) -> PlanFilterValues:
        if self._filter_session_open and self._live_filter_values is not None:
            return self._live_filter_values
        return self.filters

    def _ensure_filter_index(self, *, needed: bool) -> PlanFilterIndex | None:
        snapshot = self._snapshot
        if not needed or snapshot is None or snapshot.project != self.project_scope:
            return None
        if self._filter_index_snapshot is not snapshot:
            return None
        return self._filter_index

    def _set_filter_completion_sources(self) -> None:
        if self._query_profile.pane_id != "ref:plan" and self._query_index is not None:
            declared_facets = (
                self.contract.presentation.facets
                if getattr(self, "contract", None) is not None
                else ()
            )
            facets = {
                key: values
                for key, values in self._query_index.facets.items()
                if key not in {"since", "until"}
            }
            if declared_facets:
                allowed = set(declared_facets)
                facets = {
                    key: values for key, values in facets.items() if key in allowed
                }
            self.query_one(PlanFilterBar).set_observed_facets(facets)
            return
        snapshot = self._snapshot
        index = self._ensure_filter_index(needed=True)
        if snapshot is None or index is None:
            self.query_one(PlanFilterBar).set_completion_sources((), (), ())
            return
        query_index = getattr(self, "_query_index", None)
        if query_index is not None:
            self.query_one(PlanFilterBar).set_observed_facets(
                {
                    key: values
                    for key, values in query_index.facets.items()
                    if key not in {"since", "until"}
                }
            )

    def _filter_coverage(
        self,
        values: PlanFilterValues,
    ) -> tuple[bool, str | None]:
        return deep_archive_coverage(
            self._snapshot,
            values,
            self._deep_archive_result_for(values),
        )

    def _deep_archive_request_for(
        self,
        values: PlanFilterValues,
    ) -> DeepArchiveRequest | None:
        return make_deep_archive_request(
            self._snapshot,
            project_scope=self.project_scope,
            filter_session_open=self._filter_session_open,
            values=values,
            generation=-(self._load_generation + 1),
        )

    def _deep_archive_result_for(
        self,
        values: PlanFilterValues,
    ) -> DeepArchiveResult | None:
        request = self._deep_archive_request_for(values)
        return None if request is None else self._deep_archive_cache.get(request)

    def _schedule_deep_archive(self, values: PlanFilterValues) -> None:
        request = self._deep_archive_request_for(values)
        if request is None:
            self._invalidate_deep_archive_request()
            return
        self._deep_archive_request = request
        cached = self._deep_archive_cache.get(request)
        if cached is not None:
            if self._deep_archive_debouncer is not None:
                self._deep_archive_debouncer.cancel()
            self._install_deep_archive_result(cached)
            if self.is_mounted:
                self._refresh_options()
            return
        if self._deep_archive_in_flight == request:
            return

        def launch() -> None:
            self._launch_deep_archive(request)

        if self._deep_archive_debouncer is None:
            launch()
        else:
            self._deep_archive_debouncer.schedule(launch)

    def _launch_deep_archive(self, request: DeepArchiveRequest) -> None:
        if request != self._deep_archive_request:
            return
        if request in self._deep_archive_cache:
            self._refresh_options()
            return
        worker = self._deep_archive_worker
        if worker is not None and not worker.is_finished:
            self._deep_archive_pending = request
            return
        snapshot = self._snapshot
        if snapshot is None or id(snapshot) != request.snapshot_identity:
            return

        def task() -> DeepArchiveResult:
            return load_deep_archive_result(
                snapshot,
                request,
                profile=self._query_profile,
            )

        self._deep_archive_in_flight = request
        self._deep_archive_pending = None
        self._deep_archive_worker = self.run_worker(
            task,
            thread=True,
            group="artifacts-plans-deep-archive",
            exclusive=False,
            exit_on_error=False,
        )

    def _on_deep_archive_worker_changed(
        self,
        event: Worker.StateChanged,
    ) -> None:
        if event.state not in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }:
            return
        request = self._deep_archive_in_flight
        self._deep_archive_worker = None
        self._deep_archive_in_flight = None
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if (
                isinstance(result, DeepArchiveResult)
                and request == self._deep_archive_request
                and result.request == request
                and result.query_index.generation == request.generation
            ):
                remember_deep_archive_result(self._deep_archive_cache, result)
                self._install_deep_archive_result(result)
                if self._filter_session_open:
                    self._set_filter_completion_sources()
                self._refresh_options()

        pending = self._deep_archive_pending
        self._deep_archive_pending = None
        if pending is not None and pending == self._deep_archive_request:
            self._launch_deep_archive(pending)

    def _install_deep_archive_result(self, result: DeepArchiveResult) -> None:
        """Publish a generation-checked extended corpus to the query session."""
        if (
            self._snapshot is None
            or id(self._snapshot) != result.request.snapshot_identity
            or result.query_index.profile.digest != self._query_profile.digest
        ):
            return
        self._query_session.clear()
        self._filter_index = result.filter_index
        self._filter_index_snapshot = self._snapshot
        self._query_index = result.query_index
        if result.query_result is not None:
            self._query_session.remember(result.query_result)

    def _invalidate_deep_archive_request(self) -> None:
        if self._deep_archive_debouncer is not None:
            self._deep_archive_debouncer.cancel()
        self._deep_archive_request = None
        self._deep_archive_pending = None

    def _reset_deep_archive_state(self) -> None:
        self._invalidate_deep_archive_request()
        self._deep_archive_cache.clear()
        self._display_archive_total = None
        self._display_archive_coverage_label = None

    def _cancel_jump_mode_for_filter_change(self) -> None:
        cancel_jump = getattr(
            self.app,
            "_cancel_artifacts_jump_mode_for_model_change",
            None,
        )
        if callable(cancel_jump):
            cancel_jump(getattr(self, "pane_key", "ref:plan"))


__all__ = ["PlansFilterSessionMixin"]
