"""New Project wizard shell.

Facade preserving the original module's public import path. The
implementation now lives in sibling modules (each at most 500 lines):

- :mod:`sase.ace.tui.modals.new_project_modal_selection` — typed wizard result.
- :mod:`sase.ace.tui.modals.new_project_modal_shell` — frame compose and stage chrome.
- :mod:`sase.ace.tui.modals.new_project_modal_providers` — provider tabs and inventory loads.
- :mod:`sase.ace.tui.modals.new_project_modal_source` — Source helpers and Review glue.

``@on`` handlers stay on this concrete modal so Textual's message-pump
metaclass registers them; plain helpers live in the sibling mixins.

Shared constants live in the private
:mod:`sase.ace.tui.modals._new_project_modal_shared` module under public
names so siblings never import ``_``-prefixed names across modules.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence

from textual import events, on
from textual.css.query import NoMatches
from textual.screen import ModalScreen

from sase.project_onboarding import (
    CandidateInputs,
    Preferences,
)
from sase.workspace_provider import WorkflowMetadata

from ..widgets.panel_tab_strip import PanelTabStrip
from .new_project_apply import NewProjectApplyMixin, NewProjectInitHost
from .new_project_configure import NewProjectConfigure
from .new_project_configure_flow import NewProjectConfigureFlowMixin
from .new_project_configure_model import ConfigureDraft
from .new_project_create import NewProjectCreateConfigure, NewProjectCreateFlowMixin
from .new_project_modal_providers import (
    NewProjectModalProvidersMixin as NewProjectModalProvidersMixin,
)
from .new_project_modal_selection import (
    NewProjectSelection as NewProjectSelection,
)
from .new_project_modal_shell import (
    NewProjectModalShellMixin as NewProjectModalShellMixin,
)
from .new_project_modal_source import (
    NewProjectModalSourceMixin as NewProjectModalSourceMixin,
)
from .new_project_progress_model import ProgressResult
from .new_project_review import NewProjectReview
from .new_project_review_model import ApplySubmission
from .new_project_source import NewProjectSource
from .new_project_state import NewProjectStateMachine


class NewProjectModal(
    NewProjectModalShellMixin,
    NewProjectModalProvidersMixin,
    NewProjectModalSourceMixin,
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
        self._owner_jobs: set[asyncio.Task[tuple[str, CandidateInputs | None]]] = set()
        self._refresh_queued: set[str] = set()
        self._revalidated_live: set[str] = set()
        self._teardown_started = False
        self._disabled_providers: set[str] = set()
        self._tabs_disabled_snapshot: frozenset[str] = frozenset()
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
        self._apply_proc_id = ""
        self._review_document: dict[str, object] = {}
        self._progress_result: ProgressResult | None = None
        self._ready_key = ""
        self._ready_name = ""
        self._ready_accent = ""
        self._needs_init = False
        self._init_host: NewProjectInitHost | None = None
        self._init_create_state()

    @on(PanelTabStrip.TabClicked)
    def _provider_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        self.select_provider(event.tab_id)

    def on_resize(self, event: events.Resize) -> None:
        """Re-fit width-aware Source chrome after a terminal resize."""
        if self._teardown_started or self._state.stage != "source":
            return
        try:
            self._update_apply_chrome("source")
        except NoMatches:
            return
        matches = self.query(NewProjectSource)
        if matches:
            source = matches.first()
            source._select_detail(source.selected_row(), schedule_probe=False)

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

    @on(events.Paste)
    def _paste_anywhere(self, event: events.Paste) -> None:
        # Bracketed pastes land in the focused create editor natively; only
        # the Source stage forwards them into the hidden Source filter.
        if self._state.stage != "source":
            return
        event.stop()
        event.prevent_default()
        self.query_one(NewProjectSource).paste_filter(event.text)

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


__all__ = ["NewProjectModal", "NewProjectSelection"]
