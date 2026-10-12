"""Configure stage for adding an existing repository to the New Project wizard."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Checkbox, Input, Static

from .new_project_configure_model import (
    ConfigureDraft,
    IdentityCheck,
    ProjectCard,
    SetupCard,
    build_project_card,
    build_setup_card,
)
from .new_project_rendering import clean_source_text
from .new_project_source_model import SourceRow


class NewProjectConfigure(VerticalScroll):
    """Editable Project and SASE setup cards for one selected source row."""

    class DraftChanged(Message):
        """The editable draft changed and needs a debounced local preview."""

        def __init__(self, draft: ConfigureDraft) -> None:
            super().__init__()
            self.draft = draft

    class PreviewRequested(Message):
        """The debounce timer expired; the parent should schedule preview work."""

    class ReviewRequested(Message):
        """The user asked to continue to Review."""

    class BackRequested(Message):
        """The user asked to return to Source."""

    BINDINGS = [
        ("b", "back", "Back"),
        ("space", "toggle_focused_checkbox", "Toggle"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._row: SourceRow | None = None
        self._draft = ConfigureDraft()
        self._document: dict[str, Any] = {}
        self._identity = IdentityCheck("invalid", "Waiting for the local plan…")
        self._preview_timer: Any | None = None
        self._preview_due = False
        self._ignore_input_values: dict[str, str] = {}
        self._ignore_checkbox_values: dict[str, bool] = {}

    def compose(self) -> ComposeResult:
        with Vertical(
            id="new-project-configure-project-card", classes="new-project-card"
        ):
            yield Static("PROJECT", classes="new-project-card-heading")
            with Horizontal(classes="new-project-configure-field"):
                yield Static("Name", classes="new-project-field-label")
                yield Input(placeholder="Project name", id="new-project-configure-name")
            with Horizontal(classes="new-project-configure-field"):
                yield Static("Aliases", classes="new-project-field-label")
                yield Input(
                    placeholder="Comma-separated aliases (optional)",
                    id="new-project-configure-aliases",
                )
            yield Static("", id="new-project-configure-checkout", markup=False)
            yield Static("", id="new-project-configure-identity", markup=False)
            yield Static("", id="new-project-configure-enabled", markup=False)
        with Vertical(
            id="new-project-configure-setup-card", classes="new-project-card"
        ):
            yield Static("SASE SETUP", classes="new-project-card-heading")
            with Horizontal(id="new-project-configure-setup-toggle-row"):
                yield Checkbox(
                    "Set up SASE in this repository",
                    id="new-project-configure-setup",
                )
            yield Static("", id="new-project-configure-setup-reason", markup=False)
            yield Static("", id="new-project-configure-setup-note", markup=False)
            yield Checkbox(
                "Make this the current project after adding",
                id="new-project-configure-current",
            )
        with Horizontal(id="new-project-configure-actions"):
            yield Button("‹ Source", id="new-project-configure-back")
            yield Static("", id="new-project-configure-status", markup=False)
            yield Button("Review ›", id="new-project-configure-review")

    def set_source(
        self,
        row: SourceRow,
        draft: ConfigureDraft,
        document: dict[str, Any] | None = None,
        identity: IdentityCheck | None = None,
    ) -> None:
        """Show *row* with its preserved *draft* and latest local preview."""
        self._row = row
        self._draft = draft
        if document is not None:
            self._document = document
        if identity is not None:
            self._identity = identity
        if self.is_mounted:
            self._sync_form()

    def apply_preview(
        self,
        document: dict[str, Any],
        identity: IdentityCheck,
    ) -> None:
        """Paint the latest local plan and identity verdict."""
        self._document = document
        self._identity = identity
        if self.is_mounted:
            self._render_cards()

    def mark_preview_pending(self) -> None:
        """Disable Review while a newer draft waits for its local plan."""
        self._identity = IdentityCheck("invalid", "Updating the local plan…")
        if self.is_mounted:
            self._render_cards()

    def focus_name(self) -> None:
        """Focus the first inline editor when Configure opens."""
        self.query_one("#new-project-configure-name", Input).focus()

    def focused_input(self) -> Input | None:
        """Return the active inline editor, if any."""
        focused = self.screen.focused
        if isinstance(focused, Input) and focused.id in {
            "new-project-configure-name",
            "new-project-configure-aliases",
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

    def request_preview(self) -> None:
        """Schedule the standard preview debounce after a user edit."""
        self._preview_due = False
        if self._preview_timer is not None:
            self._preview_timer.stop()
        self._preview_timer = self.set_timer(0.3, self._preview_timer_fired)

    def _preview_timer_fired(self) -> None:
        # Timer callbacks only set a flag and post a message. Planning is handled
        # by the parent's pump-free worker.
        self._preview_due = True
        self.post_message(self.PreviewRequested())

    @on(Input.Changed, "#new-project-configure-name")
    @on(Input.Changed, "#new-project-configure-aliases")
    def _input_changed(self, event: Input.Changed) -> None:
        input_id = event.input.id or ""
        if self._ignore_input_values.get(input_id) == event.value:
            self._ignore_input_values.pop(input_id, None)
            return
        if event.input.id == "new-project-configure-name":
            self._draft = replace(self._draft, name=event.value)
        else:
            aliases = tuple(
                item.strip() for item in event.value.split(",") if item.strip()
            )
            self._draft = replace(self._draft, aliases=aliases)
        self.post_message(self.DraftChanged(self._draft))
        self.request_preview()

    @on(Checkbox.Changed, "#new-project-configure-setup")
    def _setup_changed(self, event: Checkbox.Changed) -> None:
        checkbox_id = event.checkbox.id or ""
        if self._ignore_checkbox_values.get(checkbox_id) == event.value:
            self._ignore_checkbox_values.pop(checkbox_id, None)
            return
        self._draft = replace(
            self._draft,
            setup_override="on" if event.value else "off",
        )
        self.post_message(self.DraftChanged(self._draft))
        self.request_preview()

    @on(Checkbox.Changed, "#new-project-configure-current")
    def _current_changed(self, event: Checkbox.Changed) -> None:
        checkbox_id = event.checkbox.id or ""
        if self._ignore_checkbox_values.get(checkbox_id) == event.value:
            self._ignore_checkbox_values.pop(checkbox_id, None)
            return
        self._draft = replace(self._draft, make_current=event.value)
        self.post_message(self.DraftChanged(self._draft))
        self.request_preview()

    @on(Button.Pressed, "#new-project-configure-back")
    def _back_pressed(self) -> None:
        self.post_message(self.BackRequested())

    @on(Button.Pressed, "#new-project-configure-review")
    def _review_pressed(self) -> None:
        if self._identity.status == "unique":
            self.post_message(self.ReviewRequested())

    def action_back(self) -> None:
        self.post_message(self.BackRequested())

    def action_toggle_focused_checkbox(self) -> None:
        focused = self.screen.focused
        if isinstance(focused, Checkbox) and not focused.disabled:
            focused.value = not focused.value

    def _sync_form(self) -> None:
        name = self.query_one("#new-project-configure-name", Input)
        aliases = self.query_one("#new-project-configure-aliases", Input)
        current = self.query_one("#new-project-configure-current", Checkbox)
        aliases_value = ", ".join(self._draft.aliases)
        if name.value != self._draft.name:
            self._ignore_input_values[name.id or ""] = self._draft.name
        if aliases.value != aliases_value:
            self._ignore_input_values[aliases.id or ""] = aliases_value
        if current.value != self._draft.make_current:
            self._ignore_checkbox_values[current.id or ""] = self._draft.make_current
        name.value = self._draft.name
        aliases.value = aliases_value
        current.value = self._draft.make_current
        self._render_cards()

    def _render_cards(self) -> None:
        project = build_project_card(self._document, self._draft)
        setup = build_setup_card(self._document, self._draft)
        self._render_project(project)
        self._render_setup(setup)
        review = self.query_one("#new-project-configure-review", Button)
        review.disabled = self._identity.status != "unique"

    def _render_project(self, card: ProjectCard) -> None:
        checkout = Text()
        checkout.append("Source  ", style="dim")
        checkout.append(
            clean_source_text(self._row.display if self._row else ""), style="bold"
        )
        checkout.append("\n" + clean_source_text(card.checkout_line))
        self.query_one("#new-project-configure-checkout", Static).update(checkout)

        identity = Text()
        verdict_styles = {"unique": "#00D7AF", "taken": "#FFAF5F", "invalid": "#FF5F5F"}
        identity.append(
            f"Identity  {self._identity.status.upper()}",
            style=verdict_styles[self._identity.status],
        )
        if self._identity.reason:
            identity.append(
                "\n" + clean_source_text(self._identity.reason), style="dim"
            )
        identity.append("\nKey  ", style="dim")
        identity.append(clean_source_text(card.key or "pending"))
        if card.accent:
            identity.append("   ■", style=clean_source_text(card.accent))
        self.query_one("#new-project-configure-identity", Static).update(identity)

        enabled = Text("● enabled", style="#00D7AF")
        if card.reenable_note:
            enabled.append("   " + clean_source_text(card.reenable_note), style="dim")
        self.query_one("#new-project-configure-enabled", Static).update(enabled)

    def _render_setup(self, card: SetupCard) -> None:
        checkbox = self.query_one("#new-project-configure-setup", Checkbox)
        checkbox.display = card.show_checkbox
        checkbox.disabled = not card.show_checkbox
        if checkbox.value != card.checked:
            self._ignore_checkbox_values[checkbox.id or ""] = card.checked
            checkbox.value = card.checked
        reason = Text(
            clean_source_text(card.reason or "Setup choice follows the local plan.")
        )
        if card.reason_style == "amber":
            reason.stylize("#FFAF5F")
        if card.follow_up:
            reason.append(
                "\nHuman follow-up: " + clean_source_text(card.follow_up),
                style="#FFAF5F",
            )
        self.query_one("#new-project-configure-setup-reason", Static).update(reason)
        note = clean_source_text(card.note or "")
        self.query_one("#new-project-configure-setup-note", Static).update(
            Text(note, style="dim")
        )
        if card.show_checkbox and self._draft.setup_override == "auto":
            checkbox.value = card.checked
        self.query_one("#new-project-configure-status", Static).update(
            Text("Preview updates as you edit · tab moves between fields", style="dim")
        )


__all__ = ["NewProjectConfigure"]
