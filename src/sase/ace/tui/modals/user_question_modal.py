"""User question modal for the ace TUI.

Displays questions from Claude Code's AskUserQuestion tool and lets
the user select answers via a SelectionList.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, SelectionList, Static

from .base import CopyModeForwardingMixin

_OTHER_VALUE = "__other__"


@dataclass
class _QuestionAnswer:
    """Answer for a single question."""

    question: str
    selected: list[str] = field(default_factory=list)
    custom_feedback: str | None = None


@dataclass
class UserQuestionResult:
    """Result from the user question modal."""

    answers: list[_QuestionAnswer] = field(default_factory=list)
    global_note: str | None = None


class UserQuestionModal(
    CopyModeForwardingMixin, ModalScreen[UserQuestionResult | None]
):
    """Modal for answering Claude Code's AskUserQuestion prompts."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("n", "next_question", "Next"),
        ("p", "prev_question", "Previous"),
        ("g", "global_note", "Global note"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
    ]

    def __init__(self, questions: list[dict]) -> None:
        """Initialize the user question modal.

        Args:
            questions: Raw question dicts from question_request.json.
        """
        super().__init__()
        self._questions = questions
        self._current_idx = 0
        self._answers: dict[int, _QuestionAnswer] = {}
        self._other_text: dict[int, str] = {}
        self._global_note: str | None = None
        self._input_mode: str | None = None  # None | "other" | "global"

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        if not self._questions:
            return

        q = self._questions[0]
        total = len(self._questions)
        counter = f"  [{1}/{total}]" if total > 1 else ""
        header = q.get("header", "")
        header_display = f"  [dim]({header})[/dim]" if header else ""

        with Container(id="user-question-container"):
            yield Static(
                f"[bold cyan]User Question[/bold cyan]{counter}{header_display}",
                id="user-question-title",
            )
            yield Static(
                q.get("question", ""),
                id="user-question-text",
            )
            yield SelectionList[str](
                *self._build_selections(q),
                id="user-question-options",
            )
            yield Input(
                placeholder='Type your "Other" response and press Enter...',
                id="user-question-other-input",
            )
            yield Input(
                placeholder="Type a global note and press Enter...",
                id="user-question-global-input",
            )
            yield Static(
                self._build_footer_hints(),
                id="user-question-footer",
            )

    def on_mount(self) -> None:
        """Focus the selection list and hide input fields."""
        if not self._questions:
            self.dismiss(UserQuestionResult())
            return

        self.query_one("#user-question-other-input", Input).add_class("hidden")
        self.query_one("#user-question-global-input", Input).add_class("hidden")
        self.query_one("#user-question-options", SelectionList).focus()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_selections(
        question: dict,
    ) -> list[tuple[str, str]]:
        """Build SelectionList items from a question dict."""
        options = question.get("options", [])
        items: list[tuple[str, str]] = []
        for opt in options:
            label = opt.get("label", "")
            desc = opt.get("description", "")
            display = f"{label} — {desc}" if desc else label
            items.append((display, label))
        items.append(("Other...", _OTHER_VALUE))
        return items

    def _build_footer_hints(self) -> str:
        """Build the keybinding hints for the footer."""
        total = len(self._questions)
        parts = ["[green]Enter[/green]=Confirm"]
        if total > 1:
            parts.append("[cyan]n[/cyan]/[cyan]p[/cyan]=Next/Prev")
        parts.append("[yellow]g[/yellow]=Global note")
        parts.append("[dim]q[/dim]=Cancel")
        parts.append("Ctrl+D/U=Scroll")
        return "  ".join(parts)

    def _is_multi_select(self) -> bool:
        """Check whether the current question allows multiple selections."""
        if 0 <= self._current_idx < len(self._questions):
            return bool(self._questions[self._current_idx].get("multiSelect", False))
        return False

    def _save_current_answer(self) -> None:
        """Save the selections for the current question into _answers."""
        if self._current_idx >= len(self._questions):
            return

        q = self._questions[self._current_idx]
        sel_list = self.query_one("#user-question-options", SelectionList)
        selected_values = list(sel_list.selected)

        selected_labels: list[str] = []
        has_other = False
        for val in selected_values:
            if val == _OTHER_VALUE:
                has_other = True
            else:
                selected_labels.append(val)

        custom_feedback: str | None = None
        if has_other:
            selected_labels.append("Other")
            custom_feedback = self._other_text.get(self._current_idx, "")

        self._answers[self._current_idx] = _QuestionAnswer(
            question=q.get("question", ""),
            selected=selected_labels,
            custom_feedback=custom_feedback,
        )

    def _load_question(self, idx: int) -> None:
        """Load a question by index, rebuilding the UI."""
        if idx < 0 or idx >= len(self._questions):
            return

        self._current_idx = idx
        q = self._questions[idx]
        total = len(self._questions)
        counter = f"  [{idx + 1}/{total}]" if total > 1 else ""
        header = q.get("header", "")
        header_display = f"  [dim]({header})[/dim]" if header else ""

        # Update title
        title = self.query_one("#user-question-title", Static)
        title.update(f"[bold cyan]User Question[/bold cyan]{counter}{header_display}")

        # Update question text
        text = self.query_one("#user-question-text", Static)
        text.update(q.get("question", ""))

        # Rebuild selection list
        sel_list = self.query_one("#user-question-options", SelectionList)
        sel_list.clear_options()
        for label, value in self._build_selections(q):
            sel_list.add_option((label, value))

        # Restore previous selections
        if idx in self._answers:
            answer = self._answers[idx]
            for label in answer.selected:
                if label == "Other":
                    sel_list.select(_OTHER_VALUE)
                else:
                    sel_list.select(label)

        # Hide inputs, exit input mode
        self._input_mode = None
        self.query_one("#user-question-other-input", Input).add_class("hidden")
        self.query_one("#user-question-global-input", Input).add_class("hidden")
        sel_list.focus()

    def _build_result(self) -> UserQuestionResult:
        """Collect all answers into a result object."""
        answers: list[_QuestionAnswer] = []
        for idx in range(len(self._questions)):
            if idx in self._answers:
                answers.append(self._answers[idx])
            else:
                answers.append(
                    _QuestionAnswer(
                        question=self._questions[idx].get("question", ""),
                    )
                )
        return UserQuestionResult(
            answers=answers,
            global_note=self._global_note,
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_cancel(self) -> None:
        """Cancel the modal (no response written)."""
        self.dismiss(None)

    def action_next_question(self) -> None:
        """Advance to the next question."""
        if self._input_mode:
            return
        if self._current_idx < len(self._questions) - 1:
            self._save_current_answer()
            self._load_question(self._current_idx + 1)

    def action_prev_question(self) -> None:
        """Go back to the previous question."""
        if self._input_mode:
            return
        if self._current_idx > 0:
            self._save_current_answer()
            self._load_question(self._current_idx - 1)

    def action_global_note(self) -> None:
        """Enter global note input mode."""
        if self._input_mode:
            return
        self._input_mode = "global"
        global_input = self.query_one("#user-question-global-input", Input)
        if self._global_note:
            global_input.value = self._global_note
        global_input.remove_class("hidden")
        global_input.focus()

    def action_scroll_down(self) -> None:
        """Scroll the options list down."""
        sel_list = self.query_one("#user-question-options", SelectionList)
        sel_list.scroll_relative(y=5, animate=False)

    def action_scroll_up(self) -> None:
        """Scroll the options list up."""
        sel_list = self.query_one("#user-question-options", SelectionList)
        sel_list.scroll_relative(y=-5, animate=False)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_selection_list_selection_toggled(
        self,
        event: SelectionList.SelectionToggled,  # type: ignore[type-arg]
    ) -> None:
        """Handle selection toggle — enforce radio for single-select, show Other input."""
        sel_list = event.selection_list
        toggled_value = event.selection.value

        # If "Other..." was toggled on, show the input
        if toggled_value == _OTHER_VALUE and _OTHER_VALUE in sel_list.selected:
            self._input_mode = "other"
            other_input = self.query_one("#user-question-other-input", Input)
            if self._current_idx in self._other_text:
                other_input.value = self._other_text[self._current_idx]
            other_input.remove_class("hidden")
            other_input.focus()
        elif toggled_value == _OTHER_VALUE and _OTHER_VALUE not in sel_list.selected:
            # "Other" was deselected
            self.query_one("#user-question-other-input", Input).add_class("hidden")
            if self._input_mode == "other":
                self._input_mode = None

        # Enforce single-select (radio) behavior for non-multiSelect questions
        if not self._is_multi_select() and toggled_value in sel_list.selected:
            for val in list(sel_list.selected):
                if val != toggled_value:
                    sel_list.deselect(val)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission for Other and Global note inputs."""
        if event.input.id == "user-question-other-input":
            self._other_text[self._current_idx] = event.value.strip()
            self._input_mode = None
            event.input.add_class("hidden")
            self.query_one("#user-question-options", SelectionList).focus()
        elif event.input.id == "user-question-global-input":
            self._global_note = event.value.strip() or None
            self._input_mode = None
            event.input.add_class("hidden")
            self.query_one("#user-question-options", SelectionList).focus()

    def on_key(self, event: object) -> None:
        """Handle escape in input mode and Enter to advance/submit."""
        from textual import events

        if not isinstance(event, events.Key):
            super().on_key(event)  # type: ignore[arg-type]
            return

        # Escape in input mode exits the input
        if self._input_mode and event.key == "escape":
            if self._input_mode == "other":
                other_input = self.query_one("#user-question-other-input", Input)
                self._other_text[self._current_idx] = other_input.value.strip()
                other_input.add_class("hidden")
            elif self._input_mode == "global":
                global_input = self.query_one("#user-question-global-input", Input)
                self._global_note = global_input.value.strip() or None
                global_input.add_class("hidden")
            self._input_mode = None
            self.query_one("#user-question-options", SelectionList).focus()
            event.prevent_default()
            event.stop()
            return

        # Enter when not in input mode: advance or submit
        if event.key == "enter" and not self._input_mode:
            self._save_current_answer()
            if self._current_idx < len(self._questions) - 1:
                self._load_question(self._current_idx + 1)
            else:
                self.dismiss(self._build_result())
            event.prevent_default()
            event.stop()
            return

        super().on_key(event)  # type: ignore[arg-type]
