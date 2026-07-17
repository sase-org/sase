"""Generic custom notification-gate review modal."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from rich.markup import escape
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, SelectionList, Static

from sase.notification_gates.models import GateChoice, GateExtra
from sase.notification_gates.debug import GateDebugContext

from .base import CopyModeForwardingMixin


@dataclass(frozen=True)
class CustomGateModalData:
    """Verified display data loaded from one custom gate bundle."""

    request_id: str
    sender: str
    icon: str
    notes: tuple[str, ...]
    attachments: tuple[str, ...]
    preview_name: str | None
    preview_text: str | None
    choices: tuple[GateChoice, ...]


@dataclass(frozen=True)
class CustomGateModalResult:
    """One terminal choice and the user's optional add-ons."""

    choice_id: str
    selected_extra_ids: tuple[str, ...]
    feedback: str | None


class GateExtrasSelectionList(SelectionList[str]):
    """Reusable ordered checkbox list for gate add-on commands."""

    def __init__(
        self,
        extras: Iterable[GateExtra],
        *,
        id: str | None = None,
    ) -> None:
        self.gate_extras = tuple(extras)
        super().__init__(
            *(
                (
                    self._extra_label(extra.icon, extra.label),
                    extra.id,
                    extra.default_selected,
                )
                for extra in self.gate_extras
            ),
            id=id,
        )

    @property
    def selected_extra_ids(self) -> tuple[str, ...]:
        """Return selected ids in the stable envelope order."""
        selected = set(self.selected)
        return tuple(extra.id for extra in self.gate_extras if extra.id in selected)

    def apply_selection(self, selected_extra_ids: Iterable[str]) -> None:
        """Replace the current selection with one preset."""
        selected = set(selected_extra_ids)
        for extra in self.gate_extras:
            if extra.id in selected:
                self.select(extra.id)
            else:
                self.deselect(extra.id)

    @staticmethod
    def _extra_label(icon: str | None, label: str) -> str:
        value = f"{icon} {label}" if icon else label
        return escape(value)


class CustomGateModal(
    CopyModeForwardingMixin, ModalScreen[CustomGateModalResult | None]
):
    """Review and answer an open-shape custom notification gate."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("d", "debug_view", "Debug"),
        ("left", "previous_choice", "Previous choice"),
        ("right", "next_choice", "Next choice"),
        ("j", "next_command", "Next command"),
        ("k", "previous_command", "Previous command"),
        ("space", "toggle_command", "Toggle command"),
        ("ctrl+s", "submit", "Submit"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("g", "scroll_to_top", "Top"),
        ("G", "scroll_to_bottom", "Bottom"),
    ]

    def __init__(
        self,
        data: CustomGateModalData,
        *,
        debug_context: GateDebugContext | None = None,
    ) -> None:
        super().__init__()
        self._data = data
        self._choice_index = 0
        self._debug_context = debug_context

    def compose(self) -> ComposeResult:
        with Container(id="custom-gate-container"):
            yield Static(self._title(), id="custom-gate-title")
            with VerticalScroll(id="custom-gate-review-scroll"):
                yield Static(self._notes(), id="custom-gate-notes")
                if self._data.preview_text is not None:
                    preview_name = self._data.preview_name or "Preview"
                    yield Static(
                        f"[bold #87D7FF]{escape(preview_name)}[/bold #87D7FF]",
                        classes="custom-gate-section-title",
                    )
                    yield Static(
                        Syntax(
                            self._data.preview_text,
                            "markdown",
                            theme="monokai",
                            word_wrap=True,
                        ),
                        id="custom-gate-preview",
                    )
                if self._data.attachments:
                    yield Static(
                        self._attachment_summary(),
                        id="custom-gate-attachments",
                    )

            yield Static(
                "[bold]Choose one outcome[/bold]",
                id="custom-gate-choice-label",
            )
            with Horizontal(id="custom-gate-choice-buttons"):
                for index, choice in enumerate(self._data.choices):
                    yield Button(
                        self._choice_label(choice),
                        id=f"custom-gate-choice-{index}",
                        variant="primary" if index == 0 else "default",
                    )

            with Vertical(id="custom-gate-choice-details"):
                for index, choice in enumerate(self._data.choices):
                    classes = "custom-gate-choice-panel"
                    if index != 0:
                        classes += " hidden"
                    with Vertical(
                        id=f"custom-gate-choice-panel-{index}", classes=classes
                    ):
                        if choice.extras:
                            yield Static(
                                "Optional add-on commands",
                                classes="custom-gate-field-label",
                            )
                            yield GateExtrasSelectionList(
                                choice.extras,
                                id=f"custom-gate-extras-{index}",
                            )
                        else:
                            yield Static(
                                "No add-on commands for this choice.",
                                classes="custom-gate-empty-extras",
                            )

                        if choice.feedback == "disabled":
                            yield Static(
                                "Feedback is not requested for this choice.",
                                classes="custom-gate-feedback-disabled",
                            )
                        else:
                            required = choice.feedback == "required"
                            yield Static(
                                (
                                    "Feedback (required)"
                                    if required
                                    else "Feedback (optional)"
                                ),
                                classes="custom-gate-field-label",
                            )
                            yield Input(
                                placeholder=(
                                    "Explain your decision before submitting…"
                                    if required
                                    else "Add context for the sender…"
                                ),
                                id=f"custom-gate-feedback-{index}",
                            )

            with Horizontal(id="custom-gate-submit-buttons"):
                yield Button("Cancel", id="custom-gate-cancel")
                yield Button(
                    self._submit_label(self._data.choices[0]),
                    id="custom-gate-submit",
                    variant="success",
                    disabled=self._data.choices[0].feedback == "required",
                )
            yield Static(
                "←/→ choice  j/k commands  space toggle  Ctrl+S submit  d debug  q cancel",
                id="custom-gate-footer",
            )

    def on_mount(self) -> None:
        self.query_one("#custom-gate-choice-0", Button).focus(scroll_visible=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("custom-gate-choice-"):
            self._select_choice(int(button_id.rsplit("-", 1)[1]))
        elif button_id == "custom-gate-submit":
            self.action_submit()
        elif button_id == "custom-gate-cancel":
            self.action_cancel()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == f"custom-gate-feedback-{self._choice_index}":
            self._update_submit_state()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_debug_view(self) -> None:
        from .gate_debug_modal import show_gate_debug

        show_gate_debug(self, self._debug_context)

    def action_previous_choice(self) -> None:
        self._move_choice(-1)

    def action_next_choice(self) -> None:
        self._move_choice(1)

    def action_next_command(self) -> None:
        extras = self._focus_active_extras()
        if extras is not None:
            extras.action_cursor_down()

    def action_previous_command(self) -> None:
        extras = self._focus_active_extras()
        if extras is not None:
            extras.action_cursor_up()

    def action_toggle_command(self) -> None:
        extras = self._focus_active_extras()
        if extras is not None:
            extras.action_select()

    def action_submit(self) -> None:
        choice = self._data.choices[self._choice_index]
        feedback = self._feedback_value(self._choice_index, choice)
        if choice.feedback == "required" and feedback is None:
            self.notify("Feedback is required for this choice", severity="warning")
            self.query_one(f"#custom-gate-feedback-{self._choice_index}", Input).focus()
            return

        selected: tuple[str, ...] = ()
        if choice.extras:
            selected = self.query_one(
                f"#custom-gate-extras-{self._choice_index}",
                GateExtrasSelectionList,
            ).selected_extra_ids
        self.dismiss(
            CustomGateModalResult(
                choice_id=choice.id,
                selected_extra_ids=selected,
                feedback=feedback,
            )
        )

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#custom-gate-review-scroll", VerticalScroll)
        scroll.scroll_relative(y=scroll.scrollable_content_region.height // 2)

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#custom-gate-review-scroll", VerticalScroll)
        scroll.scroll_relative(y=-(scroll.scrollable_content_region.height // 2))

    def action_scroll_to_top(self) -> None:
        self.query_one("#custom-gate-review-scroll", VerticalScroll).scroll_home(
            animate=False
        )

    def action_scroll_to_bottom(self) -> None:
        self.query_one("#custom-gate-review-scroll", VerticalScroll).scroll_end(
            animate=False
        )

    def _move_choice(self, delta: int) -> None:
        count = len(self._data.choices)
        self._select_choice((self._choice_index + delta) % count)
        self.query_one(f"#custom-gate-choice-{self._choice_index}", Button).focus()

    def _focus_active_extras(self) -> GateExtrasSelectionList | None:
        if not self._data.choices[self._choice_index].extras:
            return None
        extras = self.query_one(
            f"#custom-gate-extras-{self._choice_index}",
            GateExtrasSelectionList,
        )
        extras.focus(scroll_visible=False)
        return extras

    def _select_choice(self, index: int) -> None:
        if index == self._choice_index:
            self._update_submit_state()
            return
        old_index = self._choice_index
        self.query_one(f"#custom-gate-choice-panel-{old_index}", Vertical).add_class(
            "hidden"
        )
        self.query_one(f"#custom-gate-choice-{old_index}", Button).variant = "default"
        self._choice_index = index
        self.query_one(f"#custom-gate-choice-panel-{index}", Vertical).remove_class(
            "hidden"
        )
        self.query_one(f"#custom-gate-choice-{index}", Button).variant = "primary"
        self.query_one("#custom-gate-submit", Button).label = self._submit_label(
            self._data.choices[index]
        )
        self._update_submit_state()

    def _update_submit_state(self) -> None:
        choice = self._data.choices[self._choice_index]
        feedback = self._feedback_value(self._choice_index, choice)
        self.query_one("#custom-gate-submit", Button).disabled = (
            choice.feedback == "required" and feedback is None
        )

    def _feedback_value(self, index: int, choice: GateChoice) -> str | None:
        if choice.feedback == "disabled":
            return None
        value = self.query_one(f"#custom-gate-feedback-{index}", Input).value.strip()
        return value or None

    def _title(self) -> str:
        return (
            f"[bold cyan]{escape(self._data.icon)} Custom Gate[/bold cyan]  "
            f"[bold]{escape(self._data.sender)}[/bold]  "
            f"[dim]{escape(self._data.request_id)}[/dim]"
        )

    def _notes(self) -> Text:
        text = Text()
        if not self._data.notes:
            text.append("No notes were provided.", style="dim italic")
            return text
        for index, note in enumerate(self._data.notes):
            if index:
                text.append("\n")
            text.append(note)
        return text

    def _attachment_summary(self) -> Text:
        text = Text("Attachments\n", style="bold #87D7FF")
        for attachment in self._data.attachments:
            text.append(f"• {attachment}\n", style="dim")
        return text

    @staticmethod
    def _choice_label(choice: GateChoice) -> str:
        label = f"{choice.icon} {choice.label}" if choice.icon else choice.label
        return escape(label)

    @classmethod
    def _submit_label(cls, choice: GateChoice) -> str:
        return f"Submit · {cls._choice_label(choice)}"


__all__ = [
    "CustomGateModal",
    "CustomGateModalData",
    "CustomGateModalResult",
    "GateExtrasSelectionList",
]
