"""Paint and form-slot sync for the create-Configure stage widget."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text

from .new_project_create_types import (
    CreateAvailabilityInfo,
    CreateDraft,
    CreateFormStatus,
    CreateIdentity,
)

if TYPE_CHECKING:
    from sase.workspace_provider._hookspec import RepoCreationForm


class NewProjectCreateRenderingMixin:
    """Sync mounted controls and paint create-Configure cards."""

    if TYPE_CHECKING:
        is_mounted: bool
        _availability: CreateAvailabilityInfo
        _confirmable: bool
        _document: dict[str, Any]
        _draft: CreateDraft
        _form: RepoCreationForm | None
        _form_message: str
        _form_remedy: tuple[str, ...]
        _form_status: CreateFormStatus
        _form_widget_for: RepoCreationForm | None
        _identity: CreateIdentity
        _identity_check_reason: str
        _identity_check_valid: bool
        _ignore_checkbox_values: dict[str, bool]
        _ignore_input_values: dict[str, str]
        _owners: tuple[str, ...]
        _syncing: bool
        _supported_visibilities: tuple[str, ...]

        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...

    def _form_widget(self) -> Any | None:
        try:
            from sase.ace.tui.widgets.repo_creation_form import (
                RepoCreationFormWidget as _FormWidget,
            )

            return self.query_one("#new-project-create-form-slot").query_one(
                _FormWidget
            )
        except Exception:
            return None

    def _sync_form(self) -> None:
        from textual.widgets import Button as _Button
        from textual.widgets import Checkbox as _Checkbox
        from textual.widgets import Input as _Input
        from textual.widgets import Static as _Static

        self._syncing = True
        try:
            owner_button = self.query_one("#new-project-create-owner", _Button)
            owner_button.label = self._draft.owner or "No owners available"
            owner_button.disabled = not self._owners
            visibility_button = self.query_one(
                "#new-project-create-visibility", _Button
            )
            visibility_button.label = self._draft.visibility or "private"
            self.query_one("#new-project-create-visibility-row").display = bool(
                self._supported_visibilities
            )
            self._sync_text_input(
                "#new-project-create-name", self._draft.raw_name, _Input
            )
            self._sync_text_input(
                "#new-project-create-project-name",
                self._draft.project.name,
                _Input,
            )
            self._sync_text_input(
                "#new-project-create-project-aliases",
                ", ".join(self._draft.project.aliases),
                _Input,
            )
            current = self.query_one("#new-project-create-current", _Checkbox)
            if current.value != self._draft.project.make_current:
                self._ignore_checkbox_values[current.id or ""] = (
                    self._draft.project.make_current
                )
                current.value = self._draft.project.make_current
            self._sync_form_slot()
            self._render_target()
            self._render_project()
            self._render_setup()
            self._render_actions()
        finally:
            self._syncing = False
        _ = _Static

    def _sync_text_input(self, selector: str, value: str, input_type: Any) -> None:
        control = self.query_one(selector, input_type)
        if control.value != value:
            self._ignore_input_values[control.id or ""] = value
            control.value = value

    def _sync_project_inputs(self) -> None:
        from textual.widgets import Input as _Input

        self._sync_text_input(
            "#new-project-create-project-name",
            self._draft.project.name,
            _Input,
        )

    def _sync_form_slot(self) -> None:
        from textual.widgets import Static as _Static

        slot = self.query_one("#new-project-create-form-slot")
        if self._form_status != "ready" or self._form is None:
            self._form_widget_for = None
            slot.remove_children()
            if self._form_status == "loading":
                text = "◌ Loading provider options…"
            elif self._form_message:
                text = self._form_message
            else:
                text = "This provider does not support repository creation."
            slot.mount(_Static(text, markup=False))
            return
        if self._form_widget_for == self._form:
            widget = self._form_widget()
            if widget is not None and widget.is_mounted:
                widget.set_values(dict(self._draft.provider_values))
                return
            self._form_widget_for = None
        slot.remove_children()
        from sase.ace.tui.widgets.repo_creation_form import (
            RepoCreationFormWidget as _FormWidget,
        )

        values = dict(self._draft.provider_values) or None
        slot.mount(_FormWidget(self._form, values))
        self._form_widget_for = self._form

    def _render_target(self) -> None:
        from textual.widgets import Button as _Button
        from textual.widgets import Static as _Static

        from .new_project_rendering import clean_source_text as _clean

        owner_button = self.query_one("#new-project-create-owner", _Button)
        owner_button.label = self._draft.owner or "No owners available"
        capability = self.query_one("#new-project-create-capability", _Static)
        if self._form is None and self._form_status == "loading":
            capability.update(Text("◌ Loading provider options…", style="dim"))
        elif self._form is None:
            capability.update(
                Text(
                    _clean(self._form_message or "Creation unavailable."),
                    style="#FF5F5F",
                )
            )
        else:
            chip = {
                True: ("Creation capability: available", "#00D7AF"),
                False: ("Creation capability: unavailable", "#FF5F5F"),
                None: ("Creation capability: unknown", "#FFAF5F"),
            }[self._form.can_create]
            text = Text(chip[0], style=chip[1])
            if self._form.message:
                text.append("\n" + _clean(self._form.message), style="dim")
            if self._form.remedy_argv:
                remedy = " ".join(_clean(item) for item in self._form.remedy_argv)
                text.append("\nRemedy: " + remedy, style="dim")
            capability.update(text)
        normalized = self.query_one("#new-project-create-normalized", _Static)
        if not self._identity.valid:
            normalized.update(Text(_clean(self._identity.error), style="#FF5F5F"))
        elif self._identity.normalized_label:
            normalized.update(
                Text(_clean(self._identity.normalized_label), style="dim")
            )
        else:
            normalized.update(Text(""))
        availability = self.query_one("#new-project-create-availability", _Static)
        styles = {
            "checking": ("◌ Checking name availability…", "dim"),
            "available": ("✓ " + self._availability.reason, "#00D7AF"),
            "taken": (
                "⚠ " + self._availability.reason + "  ⏎ Add existing instead",
                "#FFAF5F",
            ),
            "unavailable": ("? " + self._availability.reason, "#FF5F5F"),
        }
        line, style = styles[self._availability.status]
        availability.update(Text(_clean(line), style=style))

    def _render_project(self) -> None:
        from textual.widgets import Button as _Button
        from textual.widgets import Static as _Static

        from rich.text import Text as _Text

        from .new_project_configure_model import build_project_card as _card
        from .new_project_rendering import clean_source_text as _clean

        card = _card(self._document, self._draft.project)
        checkout = _Text()
        checkout.append("Source  ", style="dim")
        checkout.append(
            _clean(self._identity.display or self._identity.canonical_ref),
            style="bold",
        )
        checkout.append("\n" + _clean(card.checkout_line))
        self.query_one("#new-project-create-checkout", _Static).update(checkout)
        identity = _Text()
        if self._identity_check_valid:
            identity.append("Identity  UNIQUE", style="#00D7AF")
        else:
            identity.append("Identity  BLOCKED", style="#FFAF5F")
        if self._identity_check_reason:
            identity.append("\n" + _clean(self._identity_check_reason), style="dim")
        identity.append("\nKey  ", style="dim")
        identity.append(_clean(card.key or "pending"))
        if card.accent:
            identity.append("   ■", style=_clean(card.accent))
        self.query_one("#new-project-create-identity", _Static).update(identity)
        enabled = _Text("● enabled", style="#00D7AF")
        if card.reenable_note:
            enabled.append("   " + _clean(card.reenable_note), style="dim")
        self.query_one("#new-project-create-enabled", _Static).update(enabled)
        _ = _Button

    def _render_setup(self) -> None:
        from textual.widgets import Checkbox as _Checkbox
        from textual.widgets import Static as _Static

        from rich.text import Text as _Text

        from .new_project_configure_model import build_setup_card as _setup
        from .new_project_rendering import clean_source_text as _clean

        card = _setup(self._document, self._draft.project)
        checkbox = self.query_one("#new-project-create-setup", _Checkbox)
        checkbox.display = card.show_checkbox
        checkbox.disabled = not card.show_checkbox
        if checkbox.value != card.checked:
            self._ignore_checkbox_values[checkbox.id or ""] = card.checked
            checkbox.value = card.checked
        reason = _Text(_clean(card.reason or "Setup choice follows the local plan."))
        if card.reason_style == "amber":
            reason.stylize("#FFAF5F")
        if card.follow_up:
            reason.append(
                "\nHuman follow-up: " + _clean(card.follow_up),
                style="#FFAF5F",
            )
        self.query_one("#new-project-create-setup-reason", _Static).update(reason)
        note = _clean(card.note or "")
        self.query_one("#new-project-create-setup-note", _Static).update(
            _Text(note, style="dim")
        )

    def _render_actions(self) -> None:
        from textual.widgets import Button as _Button
        from textual.widgets import Static as _Static

        from rich.text import Text as _Text

        add_instead = self.query_one("#new-project-create-add-instead", _Button)
        add_instead.display = self._availability.status == "taken"
        review = self.query_one("#new-project-create-review", _Button)
        review.disabled = not self._confirmable
        status = self.query_one("#new-project-create-status", _Static)
        if self._form_status != "ready" or self._form is None:
            status.update(_Text("Provider options unavailable.", style="dim"))
        elif not self._identity.valid:
            status.update(_Text("Enter a valid repository name.", style="dim"))
        else:
            status.update(
                _Text(
                    "Preview updates as you edit · tab moves between fields",
                    style="dim",
                )
            )


__all__ = ["NewProjectCreateRenderingMixin"]
