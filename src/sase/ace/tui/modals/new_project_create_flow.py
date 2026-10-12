"""Seed create Configure, preserve per-owner drafts, and navigate the stage."""

from __future__ import annotations

from collections.abc import Container, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from sase.workspace_provider._hookspec import RepoCreationForm

from .new_project_configure_model import ConfigureDraft
from .new_project_create_checks import NewProjectCreateChecksMixin
from .new_project_create_model import (
    add_instead_seed,
    create_review_request,
    default_create_owner,
    default_create_visibility,
    lenient_effective_options,
    normalize_create_name,
    supported_create_visibilities,
)
from .new_project_create_types import (
    CreateAvailabilityInfo,
    CreateDraft,
    CreateFormStatus,
    CreateIdentity,
)
from .new_project_create_widget import NewProjectCreateConfigure

if TYPE_CHECKING:
    from textual.app import App

    from .new_project_source_model import SourceRow
    from .new_project_state import NewProjectStateMachine
    from sase.project_onboarding import Preferences


class NewProjectCreateFlowMixin(NewProjectCreateChecksMixin):
    """Seed create Configure, describe forms, and check names off-thread.

    Per-owner drafts survive navigation; defaults apply only when seeding a
    fresh owner draft. Late owner/form completions never replace the current
    owner's edits: every worker is discarded by generation, mode, owner, and
    canonical identity.
    """

    if TYPE_CHECKING:
        app: App[Any]
        is_mounted: bool
        _state: NewProjectStateMachine
        _preferences: Preferences
        _provider_by_id: dict[str, Any]
        _inputs: dict[str, Any]
        _local_plan: dict[str, Any]
        _active_target: dict[str, object]

        def notify(self, message: str, **kwargs: Any) -> None: ...
        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...
        def _show_stage(self, stage: str) -> None: ...
        def _prepare_configure(self, row: SourceRow, *, preserve: bool) -> None: ...

    _create_generation: int
    _create_form_generation: int
    _create_owners: tuple[str, ...]
    _create_drafts: dict[str, CreateDraft]
    _create_form: RepoCreationForm | None
    _create_form_status: CreateFormStatus
    _create_form_message: str
    _create_form_remedy: tuple[str, ...]
    _create_form_owner: str
    _create_identity: CreateIdentity
    _create_availability: CreateAvailabilityInfo
    _create_probe_cache: dict[tuple[str, str], Any]
    _create_records: list[dict[str, Any]]
    _create_plan: dict[str, Any]
    _create_plan_identity: str
    _create_review_request: dict[str, Any] | None
    _create_resume_pending_restore: bool

    def _init_create_state(self) -> None:
        """Reset create-flow state; called once from the modal constructor."""
        self._create_resume_pending_restore = False
        self._create_generation = 0
        self._create_form_generation = 0
        self._create_owners = ()
        self._create_drafts = {}
        self._create_form = None
        self._create_form_status = "loading"
        self._create_form_message = ""
        self._create_form_remedy = ()
        self._create_form_owner = ""
        self._create_identity = CreateIdentity(
            valid=False, error="Enter a repository name."
        )
        self._create_availability = CreateAvailabilityInfo(status="checking")
        self._create_probe_cache = {}
        self._create_records = []
        self._create_plan = {}
        self._create_plan_identity = ""
        self._create_review_request = None

    def enter_create_configure(
        self,
        *,
        workflow_type: str,
        owners: Sequence[str],
        account: str = "",
        current_project_owner: str = "",
        unavailable_owners: Container[str] = (),
        records: Sequence[Mapping[str, Any]] | None = None,
        raw_name: str = "",
    ) -> None:
        """Open create Configure from a test harness.

        Production Source affordances stay deferred; the recovery-entry phase
        adds the pinned Create row that will call this path.
        """
        self._state.workflow_type = workflow_type
        self._create_owners = tuple(dict.fromkeys(name for name in owners if name))
        if records is None:
            inputs = getattr(self, "_inputs", {}).get(workflow_type)
            records = inputs.projects if inputs is not None else []
        self._create_records = [dict(record) for record in records]
        preferences = getattr(self, "_preferences", None)
        last_owner = ""
        if preferences is not None:
            last_owner = preferences.last_owner.get(workflow_type, "")
        owner = default_create_owner(
            self._create_owners,
            account=account,
            last_owner=last_owner,
            current_project_owner=current_project_owner,
            workflow_type=workflow_type,
            unavailable=unavailable_owners,
        )
        draft = self._create_drafts.get(owner)
        if draft is None:
            draft = self._seed_create_draft(owner, raw_name=raw_name)
            self._create_drafts[owner] = draft
        identity = normalize_create_name(workflow_type, owner, draft.raw_name)
        self._create_identity = identity
        self._create_availability = CreateAvailabilityInfo(status="checking")
        self._create_plan = {}
        self._create_plan_identity = ""
        self._create_review_request = None
        self._state.to_create_configure(draft)
        self._create_resume_pending_restore = False
        self._show_stage("create-configure")
        self._paint_create_configure()
        self.query_one(NewProjectCreateConfigure).focus_name()
        self._describe_create_form(owner)

    def _seed_create_draft(self, owner: str, *, raw_name: str = "") -> CreateDraft:
        """Seed a fresh owner draft, applying defaults exactly once."""
        preferences = getattr(self, "_preferences", None)
        last_visibility: Mapping[str, str] = (
            preferences.last_visibility if preferences is not None else {}
        )
        supported = supported_create_visibilities(None)
        visibility = default_create_visibility(
            owner=owner, supported=supported, last_visibility=last_visibility
        )
        identity = normalize_create_name(self._state.workflow_type, owner, raw_name)
        base = identity.project_name_base or identity.name
        return CreateDraft(
            owner=owner,
            raw_name=raw_name,
            visibility=visibility,
            project=ConfigureDraft(name=base),
        )

    def _on_create_draft_changed(self, draft: CreateDraft) -> None:
        """Store the draft edit; the widget owns the debounce timer."""
        self._state.set_create_draft(draft)
        self._create_drafts[draft.owner] = draft
        self._create_availability = CreateAvailabilityInfo(status="checking")
        widget = self.query_one(NewProjectCreateConfigure)
        widget.mark_check_pending()

    def _on_create_check_requested(self) -> None:
        widget = self.query_one(NewProjectCreateConfigure)
        if not widget._check_due:
            return
        self._schedule_create_check()

    def _on_create_owner_selected(self, owner: str) -> None:
        """Switch owners, preserving each owner's draft and edits."""
        if owner == (
            self._state.create_draft.owner if self._state.create_draft else ""
        ):
            return
        self._create_generation += 1
        draft = self._create_drafts.get(owner)
        if draft is None:
            draft = self._seed_create_draft(owner)
            self._create_drafts[owner] = draft
        self._create_identity = normalize_create_name(
            self._state.workflow_type, owner, draft.raw_name
        )
        self._create_availability = CreateAvailabilityInfo(status="checking")
        self._create_plan = {}
        self._create_plan_identity = ""
        self._state.set_create_draft(draft)
        self._paint_create_configure()
        self._describe_create_form(owner)

    def _on_create_review_requested(self) -> None:
        """Hook create Configure into the shared Review pipeline."""
        draft = self._state.create_draft
        if draft is None or not self._create_confirmable(draft):
            return
        self._create_resume_pending_restore = False
        workflow_type = self._state.workflow_type
        metadata = getattr(self, "_provider_by_id", {}).get(workflow_type)
        self._create_review_request = create_review_request(
            identity=self._create_identity,
            workflow_type=workflow_type,
            provider_display=str(getattr(metadata, "display_name", "") or ""),
            storage_policy=str(getattr(metadata, "sdd_storage_policy", "") or ""),
            project=draft.project,
            visibility=draft.visibility,
            effective_options=lenient_effective_options(
                self._create_form, draft.provider_values
            ),
        )
        plan = dict(self._create_plan)
        if not plan:
            return
        self._local_plan = plan
        self._active_target = dict(self._create_review_request.get("target") or {})
        self._state.to_review()
        self._show_stage("review")
        review = self.query_one("#new-project-review-stage")
        start_check = getattr(review, "start_check", None)
        if callable(start_check):
            start_check(plan)
        back = review.query_one("#new-project-review-back")
        focus = getattr(back, "focus", None)
        if callable(focus):
            focus()

    def create_review_intent(self) -> dict[str, Any] | None:
        """Return the staged complete create intent, if Review was requested."""
        return (
            dict(self._create_review_request)
            if self._create_review_request is not None
            else None
        )

    def _restore_create_configure_from_resume(self) -> None:
        """Repaint create Configure after Back from a resumed create Review.

        The resume hydration jumps straight to checked Review, so the
        Configure widget was never painted. Restore the recovered draft,
        re-describe the owner form, and schedule a live check.
        """
        draft = self._state.create_draft
        if draft is None:
            return
        self._create_resume_pending_restore = False
        if draft.owner and draft.owner not in self._create_owners:
            self._create_owners = (*self._create_owners, draft.owner)
        self._create_drafts[draft.owner] = draft
        self._paint_create_configure()
        self._describe_create_form(draft.owner)
        self._schedule_create_check()
        try:
            self.query_one(NewProjectCreateConfigure).focus_name()
        except Exception:
            pass

    def _on_create_back_requested(self) -> None:
        """Return to Source, cancelling pending create work."""
        self._create_generation += 1
        self._create_form_generation += 1
        try:
            self.query_one(NewProjectCreateConfigure).cancel_pending()
        except Exception:
            pass
        self._state.back_to_source()
        self._state.wizard_mode = "add"
        self._show_stage("source")

    def _on_create_add_instead(self, identity: CreateIdentity) -> None:
        """Switch an explicitly taken remote to existing-repo Configure."""
        if not identity.valid:
            return
        from .new_project_source_model import SourceRow as _SourceRow

        self._create_generation += 1
        self._create_form_generation += 1
        try:
            self.query_one(NewProjectCreateConfigure).cancel_pending()
        except Exception:
            pass
        workflow_type = self._state.workflow_type
        metadata = getattr(self, "_provider_by_id", {}).get(workflow_type)
        seed = add_instead_seed(
            identity=identity,
            workflow_type=workflow_type,
            provider_display=str(getattr(metadata, "display_name", "") or ""),
            storage_policy=str(getattr(metadata, "sdd_storage_policy", "") or ""),
        )
        row = _SourceRow(
            row_id=f"create-add-instead:{identity.identity_key}",
            group="paste",
            display=identity.display or identity.canonical_ref,
            ref=identity.canonical_ref,
            owner=identity.owner,
            data={
                **seed,
                "name": identity.name,
                "project_name_base": identity.project_name_base,
                "project_key_base": identity.project_key_base,
                "identity_key": identity.identity_key,
                "web_url": identity.web_url,
            },
        )
        self._state.selected = row
        self._state.to_add_configure()
        self._prepare_configure(row, preserve=False)
        self._show_stage(self._state.stage)
        try:
            from .new_project_configure import NewProjectConfigure as _Configure

            self.query_one(_Configure).focus_name()
        except Exception:
            pass


__all__ = ["NewProjectCreateFlowMixin"]
