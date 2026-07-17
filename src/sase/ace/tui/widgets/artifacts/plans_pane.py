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
from ...keymaps import KeymapRegistry, load_keymap_registry
from .._prompt_preview_target import PreviewPayload
from .entry_navigation import ArtifactEntryTarget
from .panes import ArtifactsPaneLifecycle
from .plans_data import (
    PlansSnapshot,
    load_plans_snapshot,
)
from .plans_detail import (
    archive_preview_markdown,
    archive_properties_header,
    bead_body_markdown,
    bead_preview_markdown,
    bead_properties_header,
    proposal_properties_header,
)
from .plans_list import (
    PlanRow,
    build_plan_options,
    plan_row_target,
    row_option_id,
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
        self._refresh_options()

    def on_unmount(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        if self._worker is not None and not self._worker.is_finished:
            self._worker.cancel()

    def on_first_activate(self) -> None:
        self._request_load(force=False)

    def on_activate(self) -> None:
        self.focus_list()
        if self._snapshot is None or self._snapshot.project != self.project_scope:
            self._request_load(force=False)

    def on_deactivate(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()

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
                self._snapshot = result
                self._load_error = None
                self._refresh_options(preferred_id=preferred)
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
        options, rows = build_plan_options(
            self._snapshot,
            project_scope=self.project_scope,
            loading=self._loading,
            expanded_epics=self._expanded_epics,
            jump_hints=self._entry_jump_hints,
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
        if update_detail:
            self._update_detail()

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
            body.update(bead_body_markdown(row.issue))
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
        )

    def _status_text(self) -> Text:
        return build_plans_status(
            self._snapshot,
            loading=self._loading,
            load_error=self._load_error,
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
