"""User question modal for the ace TUI.

Displays questions from Claude Code's AskUserQuestion tool in a two-pane
layout: left pane shows short question summaries, right pane shows the
full question text with selectable options.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widgets import Input, OptionList, SelectionList, Static
from textual.widgets._option_list import OptionDoesNotExist
from textual.widgets._toggle_button import ToggleButton
from textual.widgets.option_list import Option

from .base import CopyModeForwardingMixin


class _WrappingSelectionList(SelectionList[str]):
    """SelectionList that wraps long option text instead of truncating.

    Textual's built-in SelectionList uses ``text-wrap: nowrap`` and
    ``text-overflow: ellipsis``, so long labels get truncated with "...".
    This subclass enables wrapping and fixes ``render_line`` to properly
    handle multi-line options (checkbox on first line only, continuation
    lines indented to align with text).
    """

    DEFAULT_CSS = """
    _WrappingSelectionList {
        text-wrap: wrap;
        text-overflow: clip;
    }
    """

    def render_line(self, y: int) -> Strip:
        """Render a line, adding the checkbox only on the first line."""
        # Get the correctly rendered content line from OptionList.
        line = OptionList.render_line(self, y)

        # Use OptionList's line cache to find which option this line
        # belongs to and whether it's the first line of that option.
        _, scroll_y = self.scroll_offset
        line_number = scroll_y + y
        try:
            option_index, line_offset = self._lines[line_number]
            selection = self.get_option_at_index(option_index)
        except (IndexError, OptionDoesNotExist):
            return line

        # Determine checkbox style.
        component_style = "selection-list--button"
        if selection.value in self._selected:
            component_style += "-selected"
        if self.highlighted == option_index:
            component_style += "-highlighted"

        underlying_style = next(iter(line)).style or self.rich_style
        assert underlying_style is not None
        button_style = self.get_component_rich_style(component_style)
        side_style = Style.from_color(button_style.bgcolor, underlying_style.bgcolor)
        side_style += Style(meta={"option": option_index})
        button_style += Style(meta={"option": option_index})

        gutter_width = self._get_left_gutter_width()

        if line_offset == 0:
            # First line of option: show the checkbox.
            return Strip(
                [
                    Segment(ToggleButton.BUTTON_LEFT, style=side_style),
                    Segment(ToggleButton.BUTTON_INNER, style=button_style),
                    Segment(ToggleButton.BUTTON_RIGHT, style=side_style),
                    Segment(" ", style=underlying_style),
                    *line,
                ]
            )
        else:
            # Continuation line: indent to align with text after checkbox.
            return Strip(
                [
                    Segment(
                        " " * gutter_width,
                        style=underlying_style + Style(meta={"option": option_index}),
                    ),
                    *line,
                ]
            )


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
    """Modal for answering Claude Code's AskUserQuestion prompts.

    Two-pane layout: left pane lists questions, right pane shows the full
    question text with selectable answer options.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("j", "next_option", "Next option"),
        ("k", "prev_option", "Prev option"),
        ("n", "next_question", "Next"),
        ("p", "prev_question", "Previous"),
        ("g", "global_note", "Global note"),
        ("S", "submit_all", "Submit"),
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
        """Compose the two-pane modal layout."""
        if not self._questions:
            return

        with Container(id="user-question-container"):
            yield Static(
                "[bold cyan]User Questions[/bold cyan]",
                id="user-question-title",
            )
            with Horizontal(id="user-question-panels"):
                # Left pane: question list
                with Vertical(id="user-question-left"):
                    yield Static(
                        "[dim bold]Questions[/dim bold]",
                        id="user-question-list-label",
                    )
                    yield OptionList(
                        *self._build_question_list_options(),
                        id="user-question-list",
                    )
                # Right pane: full question + options
                with Vertical(id="user-question-right"):
                    yield Static(
                        self._build_question_header(0),
                        id="user-question-header",
                    )
                    with VerticalScroll(id="user-question-text-scroll"):
                        yield Static(
                            self._questions[0].get("question", ""),
                            id="user-question-text",
                        )
                    yield _WrappingSelectionList(
                        *self._build_selections(self._questions[0]),
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

    def _build_question_list_options(self) -> list[Option]:
        """Build OptionList items for the left-pane question list."""
        options: list[Option] = []
        for idx, q in enumerate(self._questions):
            text = self._make_question_label(idx, q)
            options.append(Option(text, id=str(idx)))
        return options

    def _make_question_label(self, idx: int, q: dict) -> Text:
        """Create a styled one-line label for a question in the left pane."""
        text = Text()
        # Answer status indicator
        if idx in self._answers and self._answers[idx].selected:
            text.append(" \u2713 ", style="bold green")
        else:
            text.append(" \u2022 ", style="dim")
        # Question number
        text.append(f"Q{idx + 1} ", style="bold cyan")
        # Use header if available, otherwise truncate question text
        header = q.get("header", "")
        if header:
            text.append(header)
        else:
            question_text = q.get("question", "")
            # Truncate to fit in the left pane
            if len(question_text) > 40:
                text.append(question_text[:37] + "...")
            else:
                text.append(question_text)
        return text

    def _build_question_header(self, idx: int) -> str:
        """Build the header text for the right pane."""
        q = self._questions[idx]
        total = len(self._questions)
        header = q.get("header", "")
        header_display = f"  [dim]({header})[/dim]" if header else ""
        return f"[bold cyan]Question {idx + 1}/{total}[/bold cyan]{header_display}"

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
            display = f"{label} \u2014 {desc}" if desc else label
            items.append((display, label))
        items.append(("Other...", _OTHER_VALUE))
        return items

    def _build_footer_hints(self) -> str:
        """Build the keybinding hints for the footer."""
        total = len(self._questions)
        parts = ["[green]Space[/green]=Toggle", "[cyan]j[/cyan]/[cyan]k[/cyan]=Up/Down"]
        if total > 1:
            parts.append("[cyan]n[/cyan]/[cyan]p[/cyan]=Next/Prev")
        parts.append("[bold green]S[/bold green]=Submit all")
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

    def _refresh_question_list(self) -> None:
        """Refresh the left-pane question list to update answer indicators."""
        question_list = self.query_one("#user-question-list", OptionList)
        question_list.clear_options()
        for option in self._build_question_list_options():
            question_list.add_option(option)
        # Re-highlight current question
        if 0 <= self._current_idx < len(self._questions):
            question_list.highlighted = self._current_idx

    def _load_question(self, idx: int) -> None:
        """Load a question by index, rebuilding the right pane UI."""
        if idx < 0 or idx >= len(self._questions):
            return

        self._current_idx = idx
        q = self._questions[idx]

        # Update header
        header = self.query_one("#user-question-header", Static)
        header.update(self._build_question_header(idx))

        # Update full question text
        text = self.query_one("#user-question-text", Static)
        text.update(q.get("question", ""))

        # Scroll question text to top
        text_scroll = self.query_one("#user-question-text-scroll", VerticalScroll)
        text_scroll.scroll_home(animate=False)

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

        # Update left pane highlight
        question_list = self.query_one("#user-question-list", OptionList)
        question_list.highlighted = idx

        # Refresh left pane labels (answer indicators)
        self._refresh_question_list()

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

    def action_next_option(self) -> None:
        """Move cursor to the next option in the selection list."""
        if self._input_mode:
            return
        self.query_one("#user-question-options", SelectionList).action_cursor_down()

    def action_prev_option(self) -> None:
        """Move cursor to the previous option in the selection list."""
        if self._input_mode:
            return
        self.query_one("#user-question-options", SelectionList).action_cursor_up()

    def action_submit_all(self) -> None:
        """Submit all answers at once."""
        if self._input_mode:
            return
        self._save_current_answer()
        self.dismiss(self._build_result())

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

    def on_option_list_option_selected(
        self,
        event: OptionList.OptionSelected,
    ) -> None:
        """Handle clicking/entering a question in the left pane list."""
        if event.option_list.id != "user-question-list":
            return
        if event.option and event.option.id is not None:
            idx = int(str(event.option.id))
            if idx != self._current_idx:
                self._save_current_answer()
                self._load_question(idx)

    def on_option_list_option_highlighted(
        self,
        event: OptionList.OptionHighlighted,
    ) -> None:
        """Handle highlighting a question in the left pane list."""
        if event.option_list.id != "user-question-list":
            return
        if event.option and event.option.id is not None:
            idx = int(str(event.option.id))
            if idx != self._current_idx:
                self._save_current_answer()
                self._load_question(idx)

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
            # Only handle Enter when SelectionList has focus (not OptionList)
            focused = self.app.focused
            if isinstance(focused, OptionList):
                # Let the OptionList handle it (question list selection)
                return
            self._save_current_answer()
            if self._current_idx < len(self._questions) - 1:
                self._load_question(self._current_idx + 1)
            else:
                self.dismiss(self._build_result())
            event.prevent_default()
            event.stop()
            return

        super().on_key(event)  # type: ignore[arg-type]
