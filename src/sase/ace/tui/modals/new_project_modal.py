"""Wizard shell and stages for the New Project flow."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import replace

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import ContentSwitcher, Static

from sase import workspace_provider
from sase.ace.tui.util.pump_tasks import cancel_pump_free_tasks, spawn_pump_free_task
from sase.project_onboarding import (
    CandidateInputs,
    OwnerResult,
    Preferences,
    load_candidate_inputs,
    load_preferences,
    preferences_path,
    save_preferences,
)
from sase.workspace_provider import WorkflowMetadata

from ..widgets.panel_tab_strip import PanelTab, PanelTabStrip
from .new_project_apply import NewProjectApplyMixin, NewProjectInitHost
from .new_project_configure_flow import NewProjectConfigureFlowMixin
from .new_project_rendering import clean_source_text, render_stepper
from .new_project_configure import NewProjectConfigure
from .new_project_configure_model import ConfigureDraft, check_identity
from .new_project_create import NewProjectCreateConfigure, NewProjectCreateFlowMixin
from .new_project_failed import NewProjectFailed
from .new_project_progress import NewProjectProgress
from .new_project_progress_model import ProgressResult
from .new_project_ready import NewProjectReady
from .new_project_review import NewProjectReview
from .new_project_review_model import ApplySubmission
from .new_project_source import NewProjectSource
from .new_project_source_model import SourceRow, create_source_row
from .new_project_state import NewProjectStateMachine

_TASKS = "_new_project_modal_tasks"
_PROVIDER_ACCENTS = {"gh": "#87D7FF", "git": "#00D7AF"}


class NewProjectModal(
    NewProjectConfigureFlowMixin,
    NewProjectCreateFlowMixin,
    NewProjectApplyMixin,
    ModalScreen["NewProjectSelection | None"],
):
    """Wizard shell with provider strip and an interactive Source stage.

    ``provider_metadata`` and ``candidate_inputs`` allow a parent with a
    prewarmed inventory to push the modal directly. The normal entry path
    gathers them asynchronously after the shell has painted.
    """

    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("ctrl+s", "confirm_configure", "Confirm"),
        ("[", "previous_provider", "Previous provider"),
        (
            "]",
            "next_provider",
            "Next provider",
        ),
    ]

    def __init__(
        self,
        *,
        current_workflow_type: str | None = None,
        current_project_owner: str = "",
        provider_metadata: Sequence[WorkflowMetadata] | None = None,
        candidate_inputs: Mapping[str, CandidateInputs] | None = None,
        preferences: Preferences | None = None,
    ) -> None:
        super().__init__()
        self._current_workflow_type = current_workflow_type or ""
        self._current_project_owner = current_project_owner
        self._provided_metadata = (
            tuple(provider_metadata) if provider_metadata is not None else None
        )
        self._provided_inputs = dict(candidate_inputs or {})
        self._provided_preferences = preferences
        self._providers: tuple[WorkflowMetadata, ...] = ()
        self._provider_by_id: dict[str, WorkflowMetadata] = {}
        self._inputs: dict[str, CandidateInputs] = {}
        self._loaded: set[str] = set()
        self._loading: set[str] = set()
        self._pending_by_provider: dict[str, set[str]] = {}
        self._preferences = preferences or Preferences()
        self._state = NewProjectStateMachine()
        self._owner_semaphore = asyncio.Semaphore(3)
        self._preview_generation = 0
        self._resume_generation = 0
        self._active_target: dict[str, object] = {}
        self._active_records: list[dict[str, object]] = []
        self._observed_facts: dict[str, object] = {}
        self._local_plan: dict[str, object] = {}
        self._local_plan_draft: ConfigureDraft | None = None
        self._create_support: dict[str, str] = {}
        self._create_support_loading: set[str] = set()
        self._apply_submission: ApplySubmission | None = None
        self._review_document: dict[str, object] = {}
        self._progress_result: ProgressResult | None = None
        self._ready_key = ""
        self._ready_name = ""
        self._ready_accent = ""
        self._needs_init = False
        self._init_host: NewProjectInitHost | None = None
        self._init_create_state()

    def compose(self) -> ComposeResult:
        with Container(id="new-project-frame"):
            yield Static("✚ New Project", id="new-project-title")
            yield Static(render_stepper("source"), id="new-project-stepper")
            with Horizontal(id="new-project-provider-row"):
                yield PanelTabStrip(
                    (), None, id="new-project-providers", fill_width=False
                )
                yield Static("Loading providers…", id="new-project-health")
            with ContentSwitcher(
                initial="new-project-source-stage", id="new-project-stages"
            ):
                yield NewProjectSource(id="new-project-source-stage")
                yield NewProjectConfigure(id="new-project-configure-stage")
                yield NewProjectCreateConfigure(id="new-project-create-stage")
                yield NewProjectReview(id="new-project-review-stage")
                yield NewProjectProgress(id="new-project-progress-stage")
                yield NewProjectReady(id="new-project-ready-stage")
                yield NewProjectFailed(id="new-project-failed-stage")
            yield Static(
                "⏎ choose · n new · [ ] provider · / filter · f forks · . all · R refresh · t provider login · esc close",
                id="new-project-hints",
            )

    def on_mount(self) -> None:
        source = self.query_one(NewProjectSource)
        source.set_refresh_callback(self.action_refresh_provider)
        if self._provided_metadata is not None:
            self._configure_providers(
                self._provided_metadata,
                self._provided_preferences or Preferences(),
                self._provided_inputs,
            )
            return
        spawn_pump_free_task(
            self,
            self._bootstrap(),
            name="new-project-bootstrap",
            registry_attr=_TASKS,
        )

    def on_unmount(self) -> None:
        cancel_pump_free_tasks(self)

    @on(PanelTabStrip.TabClicked)
    def _provider_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        self.select_provider(event.tab_id)

    @on(NewProjectSource.RowChosen)
    def _source_chosen(self, event: NewProjectSource.RowChosen) -> None:
        row = event.row
        previous = self._state.selected
        outcome = self._state.select_source(row)
        if outcome == "show-project":
            project_key = self._project_key_for_row(row)
            self.dismiss(
                NewProjectSelection(
                    "show-project", self._state.workflow_type, row, project_key
                )
            )
            return
        if outcome == "jump-resume":
            self.dismiss(
                NewProjectSelection("jump-resume", self._state.workflow_type, row)
            )
            return
        if outcome == "create":
            self._enter_create_from_source(row)
            return
        if outcome == "resume":
            self._start_failed_resume(row)
            return
        if outcome == "configure":
            self._state.to_configure()
            self._prepare_configure(
                row,
                preserve=(previous is not None and previous.row_id == row.row_id),
            )
        self._show_stage(self._state.stage)
        if outcome == "configure":
            self.query_one(NewProjectConfigure).focus_name()

    def _enter_create_from_source(self, row: SourceRow) -> None:
        """Open create Configure from the pinned Source Create row."""
        workflow_type = self._state.workflow_type
        inputs = self._inputs.get(workflow_type)
        if inputs is None:
            return
        owners = [owner.name for owner in inputs.owners if owner.name]
        unavailable = {
            owner.name
            for owner in inputs.owners
            if owner.name and owner.status == "error"
        }
        if not owners and workflow_type != "git":
            self.notify("No owners available for this provider.", severity="warning")
            return
        _ = row
        self.enter_create_configure(
            workflow_type=workflow_type,
            owners=owners,
            account=inputs.account,
            current_project_owner=(
                self._current_project_owner
                if workflow_type == self._current_workflow_type
                else ""
            ),
            unavailable_owners=unavailable,
        )

    def _project_key_for_row(self, row: SourceRow) -> str:
        """Resolve a hidden existing-project row to its canonical project key."""
        direct = str(row.data.get("project_key") or "")
        if direct:
            return direct
        identity = str(row.data.get("identity_key") or "").casefold()
        inputs = self._inputs.get(self._state.workflow_type)
        if not identity or inputs is None:
            return ""
        for project in inputs.projects:
            identities = project.get("identity_keys", [])
            if isinstance(identities, (list, tuple)) and identity in {
                str(item).casefold() for item in identities
            }:
                return str(project.get("key") or "")
        return ""

    @on(events.Paste)
    def _paste_anywhere(self, event: events.Paste) -> None:
        # Bracketed pastes land in the focused create editor natively; only
        # the Source stage forwards them into the hidden Source filter.
        if self._state.stage != "source":
            return
        event.stop()
        event.prevent_default()
        self.query_one(NewProjectSource).paste_filter(event.text)

    def action_cancel(self) -> None:
        """Blur, navigate back, or close according to the active stage."""
        stage = self._state.stage
        if stage == "configure":
            if self.query_one(NewProjectConfigure).blur_input():
                return
            self._state.back_to_source()
            self._show_stage("source")
        elif stage == "create-configure":
            if self.query_one(NewProjectCreateConfigure).blur_input():
                return
            self._on_create_back_requested()
        elif stage == "review":
            self._leave_review()
        elif stage == "ready":
            self._dismiss_ready("added")
        else:
            self.dismiss(None)

    def action_confirm_configure(self) -> None:
        """Advance only when the focused control is the valid Review button."""
        if self._state.stage != "configure":
            return
        configure = self.query_one(NewProjectConfigure)
        button = configure.query_one("#new-project-configure-review")
        if self.screen.focused is button:
            self._enter_review()

    def action_previous_provider(self) -> None:
        """Select the previous provider tab."""
        self._cycle_provider(-1)

    def action_next_provider(self) -> None:
        """Select the next provider tab."""
        self._cycle_provider(1)

    def _cycle_provider(self, offset: int) -> None:
        if self._state.stage != "source":
            return
        if not self._providers:
            return
        current = self._state.workflow_type
        try:
            index = next(
                i
                for i, item in enumerate(self._providers)
                if item.workflow_type == current
            )
        except StopIteration:
            index = 0
        target = self._providers[(index + offset) % len(self._providers)]
        self.select_provider(target.workflow_type)

    def action_refresh_provider(self) -> None:
        """Revalidate every owner for the selected provider, bypassing cache."""
        workflow_type = self._state.workflow_type
        if workflow_type:
            if workflow_type in self._loading:
                return
            self._loading.add(workflow_type)
            self._maybe_discover_create_support(workflow_type, force=True)
            spawn_pump_free_task(
                self,
                self._refresh_all_owners(workflow_type, force=True),
                name=f"new-project-refresh:{workflow_type}",
                registry_attr=_TASKS,
            )

    async def _bootstrap(self) -> None:
        metadata, preferences = await asyncio.gather(
            asyncio.to_thread(workspace_provider.get_all_workflow_metadata),
            asyncio.to_thread(load_preferences),
        )
        if not self.is_mounted:
            return
        self._configure_providers(tuple(metadata), preferences, {})

    def _configure_providers(
        self,
        metadata: Sequence[WorkflowMetadata],
        preferences: Preferences,
        inputs: Mapping[str, CandidateInputs],
    ) -> None:
        self._providers = tuple(metadata)
        self._provider_by_id = {item.workflow_type: item for item in self._providers}
        self._preferences = preferences
        self._inputs.update(inputs)
        self._loaded.update(inputs)
        tabs = tuple(
            PanelTab(
                item.workflow_type,
                clean_source_text(item.display_name or item.workflow_type),
                _PROVIDER_ACCENTS.get(item.workflow_type, "#AF87D7"),
                compact_label=clean_source_text(item.workflow_type),
            )
            for item in self._providers
        )
        selected = (
            preferences.last_provider
            if preferences.last_provider in self._provider_by_id
            else self._current_workflow_type
            if self._current_workflow_type in self._provider_by_id
            else self._providers[0].workflow_type
            if self._providers
            else None
        )
        strip = self.query_one("#new-project-providers", PanelTabStrip)
        strip.set_tabs(tabs, active_tab=selected)
        self._state.workflow_type = selected or ""
        source = self.query_one(NewProjectSource)
        source.set_workflow_type(selected or "")
        source.set_inputs(self._inputs.get(selected or ""))
        if selected is not None:
            self._maybe_discover_create_support(selected)
        if selected is None:
            self.query_one("#new-project-health", Static).update(
                "No workspace providers are available."
            )
            return
        source.set_refresh_callback(self.action_refresh_provider)
        self._update_health(selected)
        if selected in self._provided_inputs:
            return
        if selected not in self._loaded:
            self._start_provider_load(selected)

    def select_provider(self, workflow_type: str) -> None:
        """Switch the selected provider tab, preserving the Source filter."""
        if self._state.stage != "source":
            return
        if workflow_type not in self._provider_by_id:
            return
        self._state.workflow_type = workflow_type
        self.query_one("#new-project-providers", PanelTabStrip).set_active_tab(
            workflow_type
        )
        source = self.query_one(NewProjectSource)
        source.set_workflow_type(workflow_type)
        source.set_create_row(None)
        source.set_inputs(
            self._inputs.get(workflow_type),
            pending_owners=frozenset(
                self._pending_by_provider.get(workflow_type, set())
            ),
        )
        self._update_health(workflow_type)
        self._start_provider_load(workflow_type)
        self._maybe_discover_create_support(workflow_type)
        self._persist_provider_selection(workflow_type)

    def _start_provider_load(self, workflow_type: str) -> None:
        if workflow_type in self._loaded or workflow_type in self._loading:
            return
        self._loading.add(workflow_type)
        spawn_pump_free_task(
            self,
            self._load_provider(workflow_type),
            name=f"new-project-load:{workflow_type}",
            registry_attr=_TASKS,
        )

    def _maybe_discover_create_support(
        self, workflow_type: str, *, force: bool = False
    ) -> None:
        """Describe the provider creation form off-thread, once per provider.

        A non-None form pins the first Source Create row; None (or a
        failure) leaves the ordinary add-only Source list.
        """
        if not workflow_type:
            return
        if workflow_type in self._create_support_loading:
            return
        if not force and workflow_type in self._create_support:
            self._apply_create_support(workflow_type)
            return
        if force:
            self._create_support.pop(workflow_type, None)
        self._create_support_loading.add(workflow_type)
        spawn_pump_free_task(
            self,
            self._observe_create_support(workflow_type),
            name=f"new-project-create-support:{workflow_type}",
            registry_attr=_TASKS,
        )

    async def _observe_create_support(self, workflow_type: str) -> None:
        inputs = self._inputs.get(workflow_type)
        namespace = ""
        if inputs is not None:
            namespace = inputs.account or next(
                (owner.name for owner in inputs.owners if owner.name), ""
            )
        try:
            form = await asyncio.to_thread(
                workspace_provider.describe_repo_creation, workflow_type, namespace
            )
        except Exception:
            form = None
        if not self.is_mounted:
            self._create_support_loading.discard(workflow_type)
            return
        self._create_support_loading.discard(workflow_type)
        self._create_support[workflow_type] = (
            "supported" if form is not None else "unsupported"
        )
        self._apply_create_support(workflow_type)

    def _apply_create_support(self, workflow_type: str) -> None:
        """Pin or clear the Source Create row from cached discovery."""
        if not self.is_mounted or workflow_type != self._state.workflow_type:
            return
        if self._create_support.get(workflow_type) != "supported":
            self.query_one(NewProjectSource).set_create_row(None)
            return
        metadata = self._provider_by_id.get(workflow_type)
        display = str(getattr(metadata, "display_name", "") or workflow_type)
        self.query_one(NewProjectSource).set_create_row(
            create_source_row(display, workflow_type)
        )

    async def _load_provider(self, workflow_type: str) -> None:
        try:
            inputs = await asyncio.to_thread(
                load_candidate_inputs, workflow_type, cache_only=True
            )
        except Exception as error:
            inputs = CandidateInputs(workflow_type, workflow_type, "")
            inputs.owners = [
                OwnerResult(name="provider", status="error", message=str(error))
            ]
        self._inputs[workflow_type] = inputs
        self._loaded.add(workflow_type)
        pending = {owner.name for owner in inputs.owners}
        self._pending_by_provider[workflow_type] = pending
        self._show_inputs_if_selected(workflow_type)
        await self._refresh_owner_set(workflow_type, inputs, pending, force=False)
        self._loading.discard(workflow_type)
        self._update_health(workflow_type)

    async def _refresh_all_owners(self, workflow_type: str, *, force: bool) -> None:
        inputs = self._inputs.get(workflow_type)
        if inputs is None:
            self._loading.discard(workflow_type)
            self._start_provider_load(workflow_type)
            return
        pending = {owner.name for owner in inputs.owners}
        self._pending_by_provider[workflow_type] = pending
        self._show_inputs_if_selected(workflow_type)
        await self._refresh_owner_set(workflow_type, inputs, pending, force=force)
        self._loading.discard(workflow_type)
        self._update_health(workflow_type)

    async def _refresh_owner_set(
        self,
        workflow_type: str,
        inputs: CandidateInputs,
        pending: set[str],
        *,
        force: bool,
    ) -> None:
        async def refresh_owner(owner_name: str) -> tuple[str, CandidateInputs | None]:
            async with self._owner_semaphore:
                try:
                    updated = await asyncio.to_thread(
                        load_candidate_inputs,
                        workflow_type,
                        cache_only=False,
                        refresh=force,
                        namespaces=[owner_name],
                    )
                    return owner_name, updated
                except Exception:
                    return owner_name, None

        jobs = [asyncio.create_task(refresh_owner(name)) for name in tuple(pending)]
        for completed in asyncio.as_completed(jobs):
            owner_name, updated = await completed
            pending.discard(owner_name)
            current = self._inputs.get(workflow_type, inputs)
            if updated is not None:
                fresh_owner = next(
                    (owner for owner in updated.owners if owner.name == owner_name),
                    None,
                )
                if fresh_owner is not None:
                    owners = [
                        fresh_owner if owner.name == owner_name else owner
                        for owner in current.owners
                    ]
                    if not any(owner.name == owner_name for owner in current.owners):
                        owners.append(fresh_owner)
                    current = replace(
                        current,
                        owners=owners,
                        remote=[entry for owner in owners for entry in owner.entries],
                    )
                    self._inputs[workflow_type] = current
            self._pending_by_provider[workflow_type] = pending
            self._show_inputs_if_selected(workflow_type)
            self._update_health(workflow_type)
        self._maybe_discover_create_support(workflow_type)

    def _show_inputs_if_selected(self, workflow_type: str) -> None:
        if workflow_type != self._state.workflow_type or not self.is_mounted:
            return
        self.query_one(NewProjectSource).set_inputs(
            self._inputs.get(workflow_type),
            pending_owners=frozenset(
                self._pending_by_provider.get(workflow_type, set())
            ),
        )

    def _update_health(self, workflow_type: str) -> None:
        if workflow_type != self._state.workflow_type:
            return
        inputs = self._inputs.get(workflow_type)
        pending = self._pending_by_provider.get(workflow_type, set())
        if inputs is None:
            text = "◌ loading cached candidates…"
        elif pending:
            text = f"◌ loading {len(inputs.owners) - len(pending)} of {len(inputs.owners)} owners"
        else:
            failures = [owner for owner in inputs.owners if owner.status == "error"]
            if failures:
                remedy: list[str] = next(
                    (owner.remedy_argv for owner in failures if owner.remedy_argv), []
                )
                text = f"⚠ {len(failures)} owner issue(s)"
                if remedy:
                    text += f" · t {' '.join(remedy)}"
            elif inputs.account:
                text = f"✓ {clean_source_text(inputs.account)} · {len(inputs.owners)} owners · cached"
            elif inputs.owners:
                text = f"✓ {len(inputs.owners)} owners · cached"
            else:
                text = "○ no owners · paste owner/repo"
        self.query_one("#new-project-health", Static).update(
            Text(
                text,
                style="#00D7AF"
                if text.startswith("✓")
                else "#FFAF5F"
                if text.startswith("⚠")
                else "dim",
            )
        )

    def _persist_provider_selection(self, workflow_type: str) -> None:
        self._preferences.last_provider = workflow_type
        spawn_pump_free_task(
            self,
            self._save_preferences(),
            name="new-project-save-provider-preference",
            registry_attr=_TASKS,
        )

    @on(NewProjectConfigure.DraftChanged)
    def _draft_changed(self, event: NewProjectConfigure.DraftChanged) -> None:
        self._state.set_draft(event.draft)
        self._local_plan = {}
        self._local_plan_draft = None
        self.query_one(NewProjectConfigure).mark_preview_pending()

    @on(NewProjectConfigure.PreviewRequested)
    def _preview_requested(self, _event: NewProjectConfigure.PreviewRequested) -> None:
        if self.query_one(NewProjectConfigure)._preview_due:
            self._schedule_local_preview()

    @on(NewProjectConfigure.ReviewRequested)
    def _configure_review_requested(
        self, _event: NewProjectConfigure.ReviewRequested
    ) -> None:
        self._enter_review()

    def _enter_review(self) -> None:
        if (
            not self._local_plan
            or self._state.draft != self._local_plan_draft
            or check_identity(self._local_plan).status != "unique"
        ):
            return
        self._state.to_review()
        self._show_stage("review")
        review = self.query_one(NewProjectReview)
        review.start_check(self._local_plan)
        review.query_one("#new-project-review-back").focus()

    @on(NewProjectConfigure.BackRequested)
    def _configure_back_requested(
        self, _event: NewProjectConfigure.BackRequested
    ) -> None:
        self._state.back_to_source()
        self._show_stage("source")

    @on(NewProjectCreateConfigure.DraftChanged)
    def _create_draft_changed(
        self, event: NewProjectCreateConfigure.DraftChanged
    ) -> None:
        self._on_create_draft_changed(event.draft)

    @on(NewProjectCreateConfigure.AvailabilityRequested)
    def _create_check_requested(
        self, _event: NewProjectCreateConfigure.AvailabilityRequested
    ) -> None:
        self._on_create_check_requested()

    @on(NewProjectCreateConfigure.OwnerSelected)
    def _create_owner_selected(
        self, event: NewProjectCreateConfigure.OwnerSelected
    ) -> None:
        self._on_create_owner_selected(event.owner)

    @on(NewProjectCreateConfigure.ReviewRequested)
    def _create_review_requested(
        self, _event: NewProjectCreateConfigure.ReviewRequested
    ) -> None:
        self._on_create_review_requested()

    @on(NewProjectCreateConfigure.BackRequested)
    def _create_back_requested(
        self, _event: NewProjectCreateConfigure.BackRequested
    ) -> None:
        self._on_create_back_requested()

    @on(NewProjectCreateConfigure.AddInsteadRequested)
    def _create_add_instead_requested(
        self, event: NewProjectCreateConfigure.AddInsteadRequested
    ) -> None:
        self._on_create_add_instead(event.identity)

    @on(NewProjectReview.BackRequested)
    def _review_back_requested(self, _event: NewProjectReview.BackRequested) -> None:
        self._leave_review()

    def _leave_review(self) -> None:
        """Return from Review to add or create Configure with drafts intact."""
        self.query_one(NewProjectReview).invalidate_check()
        self._state.back_to_configure()
        self._show_stage(self._state.stage)
        if self._state.wizard_mode == "create":
            if self._create_resume_pending_restore:
                self._restore_create_configure_from_resume()
                return
            self.query_one(NewProjectCreateConfigure).focus_name()
            return
        self.query_one(NewProjectConfigure).focus_name()

    async def _save_preferences(self) -> None:
        try:
            await asyncio.to_thread(save_preferences, self._preferences)
        except Exception as error:
            self.notify(
                f"Could not save {preferences_path().name}: {error}",
                severity="warning",
            )

    def _show_stage(self, stage: str) -> None:
        stage_ids = {
            "source": "new-project-source-stage",
            "configure": "new-project-configure-stage",
            "create-configure": "new-project-create-stage",
            "review": "new-project-review-stage",
            "progress": "new-project-progress-stage",
            "ready": "new-project-ready-stage",
            "failed": "new-project-failed-stage",
        }
        stepper_stage = "configure" if stage == "create-configure" else stage
        self.query_one("#new-project-stepper", Static).update(
            render_stepper(stepper_stage)
        )
        self.query_one("#new-project-stages", ContentSwitcher).current = stage_ids.get(
            stage, stage_ids["source"]
        )
        self._update_apply_chrome(stage)


class NewProjectSelection:
    """Typed result for source rows and Ready outcomes that leave the wizard."""

    def __init__(
        self,
        outcome: str,
        workflow_type: str = "",
        row: SourceRow | None = None,
        project_key: str = "",
    ) -> None:
        self.outcome = outcome
        self.workflow_type = workflow_type
        self.row = row
        self.project_key = project_key


__all__ = ["NewProjectModal", "NewProjectSelection"]
