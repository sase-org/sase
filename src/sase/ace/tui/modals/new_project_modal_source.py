"""Source helpers, stage navigation, and review glue for the New Project wizard.

``@on`` handlers stay on the concrete modal so Textual's message-pump
metaclass registers them; this mixin holds only plain helpers and actions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .new_project_configure import NewProjectConfigure
from .new_project_configure_model import check_identity
from .new_project_create import NewProjectCreateConfigure
from .new_project_review import NewProjectReview
from .new_project_source_model import SourceRow

if TYPE_CHECKING:
    from textual.app import App
    from textual.widget import Widget as _MixinBase

    from .new_project_state import NewProjectStateMachine
else:
    _MixinBase = object


class NewProjectModalSourceMixin(_MixinBase):
    """Drive Source selection, wizard navigation, and Review entry."""

    if TYPE_CHECKING:
        app: App[Any]
        is_mounted: bool
        screen: Any
        _create_resume_pending_restore: bool
        _current_project_owner: str
        _current_workflow_type: str
        _inputs: dict[str, Any]
        _local_plan: dict[str, object]
        _local_plan_draft: Any
        _state: NewProjectStateMachine

        def dismiss(self, *args: Any, **kwargs: Any) -> Any: ...
        def _dismiss_ready(self, outcome: str | None) -> None: ...
        def notify(self, message: str, **kwargs: Any) -> None: ...
        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...
        def _restore_create_configure_from_resume(self) -> None: ...
        def _show_stage(self, stage: str) -> None: ...
        def _on_create_back_requested(self) -> None: ...
        def enter_create_configure(self, *args: Any, **kwargs: Any) -> None: ...

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


__all__ = ["NewProjectModalSourceMixin"]
