"""Interactive plan pipeline and bead DAG pane for ACE Artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Markdown, OptionList, Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.plan_search.filter_query import (
    PlanFilterQueryError,
    PlanFilterValues,
    parse_plan_filter_query,
    to_query_string,
    to_query_tokens,
)
from ...keymaps import KeymapRegistry, load_keymap_registry
from .._prompt_preview_target import PreviewPayload
from .entry_navigation import ArtifactEntryTarget
from .panes import ArtifactsPaneLifecycle
from .plans_data import PlansSnapshot, ProjectArchive, load_plans_snapshot
from .plans_deep_archive import (
    DEEP_ARCHIVE_DEBOUNCE_S,
    DeepArchiveRequest,
    DeepArchiveResult,
    deep_archive_coverage,
    load_deep_archive_result,
    make_deep_archive_request,
    merge_archive_matches,
    remember_deep_archive_result,
)
from .plans_detail import (
    archive_preview_markdown,
    archive_properties_header,
    bead_body_markdown,
    bead_preview_markdown,
    bead_properties_header,
    linked_plan_for_issue,
    proposal_properties_header,
)
from .plans_list import (
    PlanRow,
    build_plan_options,
    plan_row_target,
    row_option_id,
)
from .plan_filter_bar import PlanFilterBar
from .plans_filtering import (
    PlanFilterIndex,
    build_plan_filter_index,
    compile_plan_matcher,
)
from .plans_rendering import (
    archive_text,
    build_empty_plan_detail,
    build_plans_hints,
    build_plans_scope,
    build_plans_status,
    epic_text,
    phase_text,
    project_badge,
    proposal_text,
)

if TYPE_CHECKING:
    from ...app import AceApp


_proposal_text = proposal_text
_epic_text = epic_text
_phase_text = phase_text
_archive_text = archive_text
_project_badge = project_badge


class ArtifactsPlansPane(ArtifactsPaneLifecycle, Vertical):
    """Browse proposals, epic phase trees, and committed plan markdown."""

    can_focus = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._init_artifacts_lifecycle()
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._registry = load_keymap_registry({})
        self._snapshot: PlansSnapshot | None = None
        self.filters = PlanFilterValues()
        self._filter_index: PlanFilterIndex | None = None
        self._filter_index_snapshot: PlansSnapshot | None = None
        self._filter_session_open = False
        self._filter_restore_values: PlanFilterValues | None = None
        self._filter_restore_expanded: set[tuple[str, str]] | None = None
        self._filter_restore_selection: str | None = None
        self._live_filter_values: PlanFilterValues | None = None
        self._filter_query_error: PlanFilterQueryError | None = None
        self._display_matched_counts: dict[str, int] | None = None
        self._display_archive_total: int | None = None
        self._display_archive_coverage_label: str | None = None
        self._deep_archive_debouncer: DetailPanelDebouncer | None = None
        self._deep_archive_worker: Worker[DeepArchiveResult] | None = None
        self._deep_archive_request: DeepArchiveRequest | None = None
        self._deep_archive_in_flight: DeepArchiveRequest | None = None
        self._deep_archive_pending: DeepArchiveRequest | None = None
        self._deep_archive_cache: dict[DeepArchiveRequest, DeepArchiveResult] = {}
        self._rows: dict[str, PlanRow] = {}
        self._expanded_epics: set[tuple[str, str]] = set()
        self._loading = False
        self._reload_pending = False
        self._force_pending = False
        self._load_error: str | None = None
        self._worker: Worker[Any] | None = None
        self._detail_debouncer: DetailPanelDebouncer | None = None
        self._syncing_options = False
        self._entry_jump_hints: dict[ArtifactEntryTarget, str] = {}

    def compose(self) -> ComposeResult:
        yield PlanFilterBar(id="plan-filter-bar")
        yield Static(self._scope_text(), classes="artifacts-pane-info", id="plans-info")
        with Horizontal(id="plans-panels"):
            list_panel = Vertical(id="plans-list-panel")
            list_panel.border_title = "Plan pipeline"
            with list_panel:
                yield Static(self._status_text(), id="plans-status")
                yield OptionList(id="plans-list")
            detail_panel = Vertical(id="plans-detail-panel")
            detail_panel.border_title = "Details"
            with detail_panel:
                with VerticalScroll(id="plans-detail-scroll"):
                    yield Static("", id="plans-detail-properties")
                    yield Markdown(self._empty_detail(), id="plans-detail")
        yield Static(self._hints_text(), id="plans-hints")

    def on_mount(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(self.app)
        self._deep_archive_debouncer = DetailPanelDebouncer(
            self.app,
            delay_s=DEEP_ARCHIVE_DEBOUNCE_S,
        )
        self._refresh_options()

    def on_unmount(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        if self._deep_archive_debouncer is not None:
            self._deep_archive_debouncer.cancel()
        if self._worker is not None and not self._worker.is_finished:
            self._worker.cancel()
        if (
            self._deep_archive_worker is not None
            and not self._deep_archive_worker.is_finished
        ):
            self._deep_archive_worker.cancel()

    def on_first_activate(self) -> None:
        self._request_load(force=False)

    def on_activate(self) -> None:
        self.focus_list()
        if self._snapshot is None or self._snapshot.project != self.project_scope:
            self._request_load(force=False)
        else:
            self._schedule_deep_archive(self._display_filter_values())

    def on_deactivate(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        self._invalidate_deep_archive_request()

    def on_refresh(self) -> None:
        self._request_load(force=True)

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        self._registry = registry
        self._update_static("#plans-info", self._scope_text())
        self._update_static("#plans-hints", self._hints_text())

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
    ) -> None:
        changed = project != self.project_scope
        self.project_scope = project
        self._project_display_name = display_name
        self._update_static("#plans-info", self._scope_text())
        if not changed:
            return
        self._load_error = None
        self._reset_deep_archive_state()
        if self.artifacts_active:
            self._request_load(force=False)
        else:
            self._refresh_options()

    @property
    def snapshot(self) -> PlansSnapshot | None:
        return self._snapshot

    def selected_row(self) -> PlanRow | None:
        option_list = self._option_list()
        if option_list is None or option_list.highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(option_list.highlighted)
        except Exception:
            return None
        return self._rows.get(option.id or "")

    def focus_list(self) -> None:
        option_list = self._option_list()
        if option_list is not None:
            option_list.focus()

    def show_filters(self) -> None:
        """Open and focus the inline plans filter bar."""
        bar = self.query_one(PlanFilterBar)
        if self._filter_session_open:
            bar.query_one("#plan-filter-input").focus()
            return
        self._filter_session_open = True
        self._filter_restore_values = self.filters
        self._filter_restore_expanded = set(self._expanded_epics)
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
        restore_expanded = self._filter_restore_expanded
        restore_selection = self._filter_restore_selection
        if restore_values is not None:
            self.filters = restore_values
        if restore_expanded is not None:
            self._expanded_epics = set(restore_expanded)
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
        self._filter_restore_expanded = None
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
            self._filter_index = build_plan_filter_index(snapshot)
            self._filter_index_snapshot = snapshot
        return self._filter_index

    def _set_filter_completion_sources(self) -> None:
        snapshot = self._snapshot
        index = self._ensure_filter_index(needed=True)
        if snapshot is None or index is None:
            self.query_one(PlanFilterBar).set_completion_sources((), ())
            return
        archive_statuses = tuple(
            status
            for record in index
            if record.kind == "archive"
            for status in record.status_labels
        )
        deep_result = self._deep_archive_result_for(self._display_filter_values())
        if deep_result is not None:
            archive_statuses = (
                *archive_statuses,
                *(
                    status
                    for item in deep_result.archive
                    for status in (
                        item.match.plan.status,
                        item.match.plan.frontmatter.get("status", ""),
                    )
                    if status
                ),
            )
        projects = tuple(
            value
            for project in snapshot.projects
            for value in (project, snapshot.display_names.get(project, project))
        )
        self.query_one(PlanFilterBar).set_completion_sources(
            archive_statuses,
            projects,
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
            return load_deep_archive_result(snapshot, request)

        self._deep_archive_in_flight = request
        self._deep_archive_pending = None
        self._deep_archive_worker = self.run_worker(
            task,
            thread=True,
            group="artifacts-plans-deep-archive",
            exclusive=False,
            exit_on_error=False,
        )

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
            cancel_jump("plans")

    def move_selection(self, step: int) -> None:
        option_list = self._option_list()
        if option_list is None:
            return
        option_list.focus()
        if step > 0:
            option_list.action_cursor_down()
        else:
            option_list.action_cursor_up()

    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        option_list = self._option_list()
        if option_list is None:
            return ()
        targets: list[ArtifactEntryTarget] = []
        for index in range(option_list.option_count):
            option_id = option_list.get_option_at_index(index).id or ""
            row = self._rows.get(option_id)
            if row is not None:
                targets.append(plan_row_target(row))
        return tuple(targets)

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        row = self.selected_row()
        return None if row is None else plan_row_target(row)

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        option_list = self._option_list()
        target_index = self._option_index_for_target(target)
        if option_list is None or target_index is None:
            return False
        changed = option_list.highlighted != target_index
        option_list.focus()
        self._syncing_options = True
        try:
            option_list.highlighted = target_index
        finally:
            self._syncing_options = False
        if changed:
            if self._detail_debouncer is None:
                self._update_detail()
            else:
                self._detail_debouncer.schedule(self._update_detail)
        return True

    def apply_entry_jump_hints(
        self,
        hints: Mapping[ArtifactEntryTarget, str],
    ) -> None:
        self._entry_jump_hints = dict(hints)
        self._refresh_options(update_detail=False)

    def clear_entry_jump_hints(self) -> None:
        if not self._entry_jump_hints:
            return
        self._entry_jump_hints = {}
        self._refresh_options(update_detail=False)

    def _option_index_for_target(self, target: ArtifactEntryTarget) -> int | None:
        option_list = self._option_list()
        if option_list is None:
            return None
        for index in range(option_list.option_count):
            option_id = option_list.get_option_at_index(index).id or ""
            row = self._rows.get(option_id)
            if row is not None and plan_row_target(row) == target:
                return index
        return None

    def set_selected_epic_expanded(self, expanded: bool) -> None:
        row = self.selected_row()
        if row is None or row.issue is None:
            return
        epic_id = row.issue.id if row.kind == "epic" else row.issue.parent_id
        if epic_id is None:
            return
        cancel_jump = getattr(
            self.app, "_cancel_artifacts_jump_mode_for_model_change", None
        )
        if callable(cancel_jump):
            cancel_jump("plans")
        epic_key = (row.project, epic_id)
        if expanded:
            if epic_key in self._expanded_epics:
                return
            self._expanded_epics.add(epic_key)
        else:
            if epic_key not in self._expanded_epics:
                return
            self._expanded_epics.discard(epic_key)
        snapshot = self._snapshot
        preferred_id = (
            None
            if snapshot is None
            else row_option_id(snapshot, "epic", row.project, epic_id)
        )
        self._refresh_options(preferred_id=preferred_id)

    def selected_preview(self) -> PreviewPayload | None:
        row = self.selected_row()
        if row is None:
            return None
        if row.proposal is not None:
            return PreviewPayload(
                content=row.proposal.content,
                lexer="markdown",
                title=row.proposal.title,
                kind_label="proposal",
                icon="◆",
                source_path=row.proposal.plan_path,
            )
        if row.archive is not None:
            plan = row.archive.plan
            return PreviewPayload(
                content=archive_preview_markdown(row.archive),
                lexer="markdown",
                title=plan.title or plan.name,
                kind_label=f"{plan.kind} plan",
                icon="▤",
                source_path=plan.path,
            )
        if row.issue is not None:
            return PreviewPayload(
                content=bead_preview_markdown(
                    row.issue,
                    self._snapshot,
                    project=row.project,
                ),
                lexer="markdown",
                title=f"{row.issue.id} · {row.issue.title}",
                kind_label="bead",
                icon="◈",
                source_path=row.issue.design or None,
            )
        return None

    def _request_load(self, *, force: bool) -> None:
        project = self.project_scope
        if self._loading:
            self._reload_pending = True
            self._force_pending = self._force_pending or force
            return
        self._loading = True
        self._load_error = None
        self._update_status()
        previous = (
            self._snapshot
            if self._snapshot is not None and self._snapshot.project == project
            else None
        )

        def task() -> PlansSnapshot:
            return load_plans_snapshot(project, previous=previous, force=force)

        self._worker = self.run_worker(
            task,
            thread=True,
            exclusive=False,
            exit_on_error=False,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._deep_archive_worker:
            self._on_deep_archive_worker_changed(event)
            return
        if event.worker is not self._worker:
            return
        terminal = event.state in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            self._loading = False
            if (
                isinstance(result, PlansSnapshot)
                and result.project == self.project_scope
            ):
                preferred = self._selected_option_id()
                cancel_jump = getattr(
                    self.app, "_cancel_artifacts_jump_mode_for_model_change", None
                )
                if callable(cancel_jump):
                    cancel_jump("plans")
                snapshot_changed = result is not self._snapshot
                self._snapshot = result
                self._filter_index = None
                self._filter_index_snapshot = None
                if snapshot_changed:
                    self._reset_deep_archive_state()
                self._load_error = None
                if self._filter_session_open:
                    self._set_filter_completion_sources()
                self._refresh_options(preferred_id=preferred)
                self._schedule_deep_archive(self._display_filter_values())
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._load_error = str(event.worker.error or "Plans load failed")
            self._update_status()
        elif event.state == WorkerState.CANCELLED:
            self._loading = False

        if terminal and self._reload_pending:
            force = self._force_pending
            self._reload_pending = False
            self._force_pending = False
            self.call_later(lambda: self._request_load(force=force))

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
            ):
                remember_deep_archive_result(self._deep_archive_cache, result)
                if self._filter_session_open:
                    self._set_filter_completion_sources()
                self._refresh_options()

        pending = self._deep_archive_pending
        self._deep_archive_pending = None
        if pending is not None and pending == self._deep_archive_request:
            self._launch_deep_archive(pending)

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
        filter_index = self._ensure_filter_index(
            needed=self._filter_session_open or not values.is_empty
        )
        if filter_index is not None:
            matcher = compile_plan_matcher(values)
            matching_records = tuple(
                record for record in filter_index if matcher(record)
            )
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
                archive_entries = merge_archive_matches(
                    preview_archive,
                    deep_result.archive,
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
                    matched_counts = dict.fromkeys(
                        ("proposal", "epic", "phase", "archive"), 0
                    )
                    for record in non_archive_records:
                        matched_counts[record.kind] += 1
                    matched_counts["archive"] = len(archive_entries)
                    self._display_matched_counts = matched_counts
            else:
                match_count = len(matching_records)
            if not values.is_empty and matched_option_ids is None:
                matched_option_ids = frozenset(
                    record.option_id for record in matching_records
                )
                matched_counts = dict.fromkeys(
                    ("proposal", "epic", "phase", "archive"), 0
                )
                for record in matching_records:
                    matched_counts[record.kind] += 1
                self._display_matched_counts = matched_counts
        options, rows = build_plan_options(
            self._snapshot,
            project_scope=self.project_scope,
            loading=self._loading,
            expanded_epics=self._expanded_epics,
            jump_hints=self._entry_jump_hints,
            matched_option_ids=matched_option_ids,
            archive_entries=archive_entries,
            archive_total=self._display_archive_total,
        )
        self._rows = rows
        self._syncing_options = True
        try:
            option_list.clear_options()
            option_list.add_options(options)
            target_index = self._option_index(preferred_id)
            if target_index is None:
                target_index = self._first_selectable_index()
            option_list.highlighted = target_index
        finally:
            self._syncing_options = False
        self._update_status()
        self._update_static("#plans-info", self._scope_text())
        if self._filter_session_open and self._filter_query_error is None:
            exact, coverage_label = self._filter_coverage(values)
            self.query_one(PlanFilterBar).set_status(
                match_count,
                exact=exact,
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

    @on(OptionList.OptionHighlighted, "#plans-list")
    def _on_option_highlighted(self, _event: OptionList.OptionHighlighted) -> None:
        if self._syncing_options:
            return
        if self._detail_debouncer is None:
            self._update_detail()
        else:
            self._detail_debouncer.schedule(self._update_detail)

    @on(OptionList.OptionSelected, "#plans-list")
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        cast("AceApp", self.app).action_plans_view_selected()

    def _update_detail(self) -> None:
        try:
            properties = self.query_one("#plans-detail-properties", Static)
            body = self.query_one("#plans-detail", Markdown)
        except Exception:
            return
        row = self.selected_row()
        if row is None:
            properties.display = False
            properties.update("")
            body.update(self._empty_detail())
        elif row.proposal is not None:
            properties.display = True
            properties.update(
                proposal_properties_header(
                    row.proposal,
                    project_name=self._project_name(row.project),
                )
            )
            body.update(row.proposal.body or "_No plan body._")
        elif row.issue is not None:
            properties.display = True
            properties.update(
                bead_properties_header(
                    row.issue,
                    self._snapshot,
                    project=row.project,
                    project_name=self._project_name(row.project),
                )
            )
            linked_plan = linked_plan_for_issue(
                row.issue, self._snapshot, project=row.project
            )
            body.update(bead_body_markdown(row.issue, linked_plan))
        elif row.archive is not None:
            properties.display = True
            properties.update(
                archive_properties_header(
                    row.archive,
                    project_name=self._project_name(row.project),
                )
            )
            body.update(row.archive.plan.body or "_No plan body._")

    def _project_name(self, project: str) -> str:
        snapshot = self._snapshot
        if snapshot is None:
            return project
        return snapshot.display_names.get(project, project)

    def _scope_text(self) -> Text:
        return build_plans_scope(
            self._registry,
            project_scope=self.project_scope,
            project_display_name=self._project_display_name,
            filter_tokens=to_query_tokens(self.filters),
        )

    def _status_text(self) -> Text:
        return build_plans_status(
            self._snapshot,
            loading=self._loading,
            load_error=self._load_error,
            matched_counts=self._display_matched_counts,
            archive_total=self._display_archive_total,
            archive_coverage_label=self._display_archive_coverage_label,
        )

    def _hints_text(self) -> Text:
        return build_plans_hints(self._registry)

    def _empty_detail(self) -> str:
        return build_empty_plan_detail(
            self._snapshot,
            project_scope=self.project_scope,
            loading=self._loading,
            load_error=self._load_error,
        )

    def _option_list(self) -> OptionList | None:
        try:
            return self.query_one("#plans-list", OptionList)
        except Exception:
            return None

    def _selected_option_id(self) -> str | None:
        option_list = self._option_list()
        if option_list is None or option_list.highlighted is None:
            return None
        try:
            return option_list.get_option_at_index(option_list.highlighted).id
        except Exception:
            return None

    def _option_index(self, option_id: str | None) -> int | None:
        if option_id is None:
            return None
        option_list = self._option_list()
        if option_list is None:
            return None
        for index in range(option_list.option_count):
            if option_list.get_option_at_index(index).id == option_id:
                return index
        if option_id.startswith("phase:"):
            row = self._rows.get(option_id)
            snapshot = self._snapshot
            if (
                row is not None
                and row.issue is not None
                and row.issue.parent_id
                and snapshot is not None
            ):
                return self._option_index(
                    row_option_id(
                        snapshot,
                        "epic",
                        row.project,
                        row.issue.parent_id,
                    )
                )
        return None

    def _first_selectable_index(self) -> int | None:
        option_list = self._option_list()
        if option_list is None:
            return None
        for index in range(option_list.option_count):
            if not option_list.get_option_at_index(index).disabled:
                return index
        return None

    def _update_status(self) -> None:
        self._update_static("#plans-status", self._status_text())

    def _update_static(self, selector: str, content: Any) -> None:
        if not self.is_mounted:
            return
        try:
            self.query_one(selector, Static).update(content)
        except Exception:
            pass


__all__ = ["ArtifactsPlansPane", "PlanRow"]
