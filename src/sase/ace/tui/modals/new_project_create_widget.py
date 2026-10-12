"""Configure-stage widget for creating a new provider repository."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message

from sase.workspace_provider._hookspec import RepoCreationForm

from .new_project_create_model import normalize_create_name
from .new_project_create_rendering import NewProjectCreateRenderingMixin
from .new_project_create_types import (
    CreateAvailabilityInfo,
    CreateDraft,
    CreateFormStatus,
    CreateIdentity,
)

AVAILABILITY_DEBOUNCE_SECONDS = 0.3


class NewProjectCreateConfigure(NewProjectCreateRenderingMixin, VerticalScroll):
    """Configure stage for creating a new provider repository.

    The owner button cycles namespaces, the name field normalizes on every
    edit, and the provider form supplies creation options. Project cards are
    shared with the add path through the same model helpers.
    """

    class DraftChanged(Message):
        """The editable create draft changed and needs a debounced refresh."""

        def __init__(self, draft: CreateDraft) -> None:
            super().__init__()
            self.draft = draft

    class AvailabilityRequested(Message):
        """The debounce timer expired; the parent should schedule a check."""

    class OwnerSelected(Message):
        """The user switched the create namespace owner."""

        def __init__(self, owner: str) -> None:
            super().__init__()
            self.owner = owner

    class ReviewRequested(Message):
        """The user asked to continue to Review with the create intent."""

    class BackRequested(Message):
        """The user asked to return to Source."""

    class AddInsteadRequested(Message):
        """The user chose to add the taken canonical ref instead."""

        def __init__(self, identity: CreateIdentity) -> None:
            super().__init__()
            self.identity = identity

    BINDINGS = [
        ("b", "back", "Back"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._workflow_type = ""
        self._owners: tuple[str, ...] = ()
        self._supported_visibilities: tuple[str, ...] = ("private", "public")
        self._draft = CreateDraft()
        self._identity = CreateIdentity(valid=False, error="Enter a repository name.")
        self._availability = CreateAvailabilityInfo(status="checking")
        self._form: RepoCreationForm | None = None
        self._form_status: CreateFormStatus = "loading"
        self._form_message = ""
        self._form_remedy: tuple[str, ...] = ()
        self._form_widget_for: RepoCreationForm | None = None
        self._document: dict[str, Any] = {}
        self._identity_check_valid = False
        self._identity_check_reason = "Building the local plan…"
        self._confirmable = False
        self._check_timer: Any | None = None
        self._check_due = False
        self._ignore_input_values: dict[str, str] = {}
        self._ignore_checkbox_values: dict[str, bool] = {}

    def compose(self) -> ComposeResult:
        from textual.containers import Vertical as _Vertical
        from textual.containers import Horizontal as _Horizontal
        from textual.widgets import Button as _Button
        from textual.widgets import Checkbox as _Checkbox
        from textual.widgets import Input as _Input
        from textual.widgets import Static as _Static

        with _Vertical(id="new-project-create-target-card", classes="new-project-card"):
            yield _Static("NEW REPOSITORY", classes="new-project-card-heading")
            with _Horizontal(classes="new-project-configure-field"):
                yield _Static("Owner", classes="new-project-field-label")
                yield _Button("…", id="new-project-create-owner")
            yield _Static("", id="new-project-create-capability", markup=False)
            with _Horizontal(classes="new-project-configure-field"):
                yield _Static("Name", classes="new-project-field-label")
                yield _Input(
                    placeholder="Repository name",
                    id="new-project-create-name",
                )
            yield _Static("", id="new-project-create-normalized", markup=False)
            yield _Static("", id="new-project-create-availability", markup=False)
            with _Horizontal(classes="new-project-configure-field"):
                yield _Static("Visibility", classes="new-project-field-label")
                yield _Button("private", id="new-project-create-visibility")
        with _Vertical(
            id="new-project-create-options-card", classes="new-project-card"
        ):
            yield _Static("OPTIONS", classes="new-project-card-heading")
            with _Vertical(id="new-project-create-form-slot"):
                yield _Static(
                    "◌ Loading provider options…",
                    id="new-project-create-form-status",
                    markup=False,
                )
        with _Vertical(
            id="new-project-create-project-card", classes="new-project-card"
        ):
            yield _Static("PROJECT", classes="new-project-card-heading")
            with _Horizontal(classes="new-project-configure-field"):
                yield _Static("Name", classes="new-project-field-label")
                yield _Input(
                    placeholder="Project name",
                    id="new-project-create-project-name",
                )
            with _Horizontal(classes="new-project-configure-field"):
                yield _Static("Aliases", classes="new-project-field-label")
                yield _Input(
                    placeholder="Comma-separated aliases (optional)",
                    id="new-project-create-project-aliases",
                )
            yield _Static("", id="new-project-create-checkout", markup=False)
            yield _Static("", id="new-project-create-identity", markup=False)
            yield _Static("", id="new-project-create-enabled", markup=False)
        with _Vertical(id="new-project-create-setup-card", classes="new-project-card"):
            yield _Static("SASE SETUP", classes="new-project-card-heading")
            with _Horizontal(id="new-project-create-setup-toggle-row"):
                yield _Checkbox(
                    "Set up SASE in this repository",
                    id="new-project-create-setup",
                )
            yield _Static("", id="new-project-create-setup-reason", markup=False)
            yield _Static("", id="new-project-create-setup-note", markup=False)
            yield _Checkbox(
                "Make this the current project after creating",
                id="new-project-create-current",
            )
        with _Horizontal(id="new-project-create-actions"):
            yield _Button("‹ Source", id="new-project-create-back")
            yield _Button(
                "Add existing instead",
                id="new-project-create-add-instead",
            )
            yield _Static("", id="new-project-create-status", markup=False)
            yield _Button("Review ›", id="new-project-create-review")

    def on_unmount(self) -> None:
        """Cancel the pending availability timer with the widget."""
        self.cancel_pending()

    def cancel_pending(self) -> None:
        """Stop the debounce timer without firing it."""
        if self._check_timer is not None:
            self._check_timer.stop()
            self._check_timer = None
        self._check_due = False

    def request_check(self) -> None:
        """Schedule the standard availability debounce after a user edit."""
        self._check_due = False
        if self._check_timer is not None:
            self._check_timer.stop()
        self._check_timer = self.set_timer(
            AVAILABILITY_DEBOUNCE_SECONDS, self._check_timer_fired
        )

    def _check_timer_fired(self) -> None:
        self._check_due = True
        self.post_message(self.AvailabilityRequested())

    @property
    def draft(self) -> CreateDraft:
        """Current editable create draft."""
        return self._draft

    @property
    def identity(self) -> CreateIdentity:
        """Latest pure normalization of the typed target."""
        return self._identity

    def set_context(
        self,
        *,
        workflow_type: str,
        owners: Sequence[str],
        supported_visibilities: Sequence[str],
        draft: CreateDraft,
        identity: CreateIdentity,
        availability: CreateAvailabilityInfo,
        form: RepoCreationForm | None,
        form_status: CreateFormStatus,
        form_message: str = "",
        form_remedy: Sequence[str] = (),
        document: Mapping[str, Any] | None = None,
        identity_valid: bool = False,
        identity_reason: str = "",
        confirmable: bool = False,
    ) -> None:
        """Repaint the stage from flow-owned state, preserving focus text."""
        self._workflow_type = workflow_type
        self._owners = tuple(owners)
        self._supported_visibilities = tuple(supported_visibilities) or (
            "private",
            "public",
        )
        self._draft = draft
        self._identity = identity
        self._availability = availability
        self._form = form
        self._form_status = form_status
        self._form_message = form_message
        self._form_remedy = tuple(form_remedy)
        if document is not None:
            self._document = dict(document)
        self._identity_check_valid = identity_valid
        self._identity_check_reason = identity_reason
        self._confirmable = confirmable and identity.valid
        if self.is_mounted:
            self._sync_form()

    def mark_check_pending(self) -> None:
        """Invalidate availability immediately on any target change."""
        self._availability = CreateAvailabilityInfo(status="checking")
        self._confirmable = False
        if self.is_mounted:
            self._render_target()
            self._render_actions()

    def apply_check(
        self,
        *,
        availability: CreateAvailabilityInfo,
        document: Mapping[str, Any],
        identity_valid: bool,
        identity_reason: str,
        confirmable: bool,
    ) -> None:
        """Paint the latest off-thread availability and local plan."""
        self._availability = availability
        self._document = dict(document)
        self._identity_check_valid = identity_valid
        self._identity_check_reason = identity_reason
        self._confirmable = confirmable and self._identity.valid
        if self.is_mounted:
            self._render_target()
            self._render_project()
            self._render_setup()
            self._render_actions()

    def focus_name(self) -> None:
        """Focus the repository name editor when the stage opens."""
        from textual.widgets import Input as _Input

        self.query_one("#new-project-create-name", _Input).focus()

    def focused_input(self) -> Any | None:
        """Return the active inline editor, if any."""
        from textual.widgets import Input as _Input

        focused = self.screen.focused
        if isinstance(focused, _Input) and focused.id in {
            "new-project-create-name",
            "new-project-create-project-name",
            "new-project-create-project-aliases",
        }:
            return focused
        return None

    def blur_input(self) -> bool:
        """Blur an active text field; return whether a field was blurred."""
        focused = self.focused_input()
        if focused is None:
            return False
        focused.blur()
        return True

    def on_input_changed(self, event: Any) -> None:
        """Normalize the repository name on every edit; track project edits."""
        from textual.widgets import Input as _Input

        if not isinstance(event, _Input.Changed):
            return
        control_id = event.input.id or ""
        if control_id not in {
            "new-project-create-name",
            "new-project-create-project-name",
            "new-project-create-project-aliases",
        }:
            return
        if self._ignore_input_values.get(control_id) == event.value:
            self._ignore_input_values.pop(control_id, None)
            return
        if control_id == "new-project-create-name":
            self._rename_target(event.value)
        elif control_id == "new-project-create-project-name":
            project = replace(
                self._draft.project,
                name=event.value,
            )
            self._draft = replace(
                self._draft, project=project, project_name_edited=True
            )
            self.post_message(self.DraftChanged(self._draft))
            self.request_check()
        else:
            aliases = tuple(
                item.strip() for item in event.value.split(",") if item.strip()
            )
            project = replace(self._draft.project, aliases=aliases)
            self._draft = replace(self._draft, project=project)
            self.post_message(self.DraftChanged(self._draft))
            self.request_check()

    def _rename_target(self, raw_name: str) -> None:
        """Apply pure normalization and follow it with the project name."""
        identity = normalize_create_name(
            self._workflow_type, self._draft.owner, raw_name
        )
        draft = replace(self._draft, raw_name=raw_name)
        if not draft.project_name_edited:
            base = identity.project_name_base or identity.name
            if base and base != draft.project.name:
                draft = replace(draft, project=replace(draft.project, name=base))
        self._draft = draft
        self._identity = identity
        self.mark_check_pending()
        if self.is_mounted:
            self._render_target()
            self._sync_project_inputs()
        self.post_message(self.DraftChanged(self._draft))
        self.request_check()

    def on_checkbox_changed(self, event: Any) -> None:
        """Track setup and make-current toggles."""
        from textual.widgets import Checkbox as _Checkbox

        if not isinstance(event, _Checkbox.Changed):
            return
        checkbox_id = event.checkbox.id or ""
        if checkbox_id not in {
            "new-project-create-setup",
            "new-project-create-current",
        }:
            return
        if self._ignore_checkbox_values.get(checkbox_id) == event.value:
            self._ignore_checkbox_values.pop(checkbox_id, None)
            return
        if checkbox_id == "new-project-create-setup":
            project = replace(
                self._draft.project,
                setup_override="on" if event.value else "off",
            )
        else:
            project = replace(self._draft.project, make_current=event.value)
        self._draft = replace(self._draft, project=project)
        self.post_message(self.DraftChanged(self._draft))
        self.request_check()

    def on_repo_creation_form_widget_changed(self, event: Any) -> None:
        """Carry provider values into the draft without touching the pump."""
        from sase.ace.tui.widgets.repo_creation_form import (
            RepoCreationFormWidget as _FormWidget,
        )

        if not isinstance(event, _FormWidget.Changed):
            return
        form = self._form_widget()
        if form is None:
            return
        self._draft = replace(self._draft, provider_values=dict(form.raw_values))
        self.post_message(self.DraftChanged(self._draft))
        self.request_check()

    def on_button_pressed(self, event: Any) -> None:
        """Cycle owner/visibility, navigate, or trigger add-instead."""
        from textual.widgets import Button as _Button

        if not isinstance(event, _Button.Pressed):
            return
        pressed_id = event.button.id or ""
        if pressed_id == "new-project-create-back":
            self.post_message(self.BackRequested())
        elif pressed_id == "new-project-create-review":
            if self._confirmable:
                self.post_message(self.ReviewRequested())
        elif pressed_id == "new-project-create-add-instead":
            if self._availability.status == "taken":
                self.post_message(self.AddInsteadRequested(self._identity))
        elif pressed_id == "new-project-create-owner":
            self._cycle_owner()
        elif pressed_id == "new-project-create-visibility":
            self._cycle_visibility()

    def on_input_submitted(self, event: Any) -> None:
        """Offer add-instead on Enter only for taken names.

        Typing Enter in ordinary text fields never creates or applies
        anything.
        """
        from textual.widgets import Input as _Input

        if not isinstance(event, _Input.Submitted):
            return
        event.stop()
        event.prevent_default()
        if self._availability.status == "taken" and self._identity.valid:
            self.post_message(self.AddInsteadRequested(self._identity))

    def action_back(self) -> None:
        self.post_message(self.BackRequested())

    def _cycle_owner(self) -> None:
        if not self._owners:
            return
        try:
            index = self._owners.index(self._draft.owner)
        except ValueError:
            index = -1
        self.post_message(
            self.OwnerSelected(self._owners[(index + 1) % len(self._owners)])
        )

    def _cycle_visibility(self) -> None:
        options = self._supported_visibilities
        if not options:
            return
        try:
            index = options.index(self._draft.visibility)
        except ValueError:
            index = -1
        self._draft = replace(
            self._draft, visibility=options[(index + 1) % len(options)]
        )
        if self.is_mounted:
            self._sync_form()
        self.post_message(self.DraftChanged(self._draft))
        self.request_check()


__all__ = ["AVAILABILITY_DEBOUNCE_SECONDS", "NewProjectCreateConfigure"]
