"""Tag input modal for adding change tags."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.saved_tag_names import delete_tag


class _TagNameInput(SingleLineVimTextArea):
    """Tag name vim editor with tag list navigation."""

    BINDINGS = [
        ("ctrl+n", "next_tag", "Next tag"),
        ("ctrl+p", "prev_tag", "Prev tag"),
        ("ctrl+d", "delete_tag", "Delete tag"),
    ]

    def action_next_tag(self) -> None:
        """Navigate to the next tag in the history list."""
        modal = self.screen
        assert isinstance(modal, TagInputModal)
        modal._navigate_tag_list(1)

    def action_prev_tag(self) -> None:
        """Navigate to the previous tag in the history list."""
        modal = self.screen
        assert isinstance(modal, TagInputModal)
        modal._navigate_tag_list(-1)

    def action_delete_tag(self) -> None:
        """Delete the currently highlighted tag from the history list."""
        modal = self.screen
        assert isinstance(modal, TagInputModal)
        modal._delete_highlighted_tag()


class _TagValueInput(SingleLineVimTextArea):
    """Tag value vim editor with placeholder fill."""

    BINDINGS = [
        ("ctrl+e", "end_or_fill_placeholder", "End/Fill"),
    ]

    def action_end_or_fill_placeholder(self) -> None:
        """Fill placeholder if input is empty, otherwise move cursor to end."""
        if not self.value and self.placeholder:
            self.value = str(self.placeholder)
            self.cursor_position = len(self.value)
        else:
            self.action_cursor_line_end()


class TagInputModal(ModalScreen[tuple[str, str] | None]):
    """Modal for entering a tag name and value.

    Returns (tag_name, tag_value) on success, or None if cancelled.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, saved_tags: dict[str, str]) -> None:
        """Initialize the tag input modal.

        Args:
            saved_tags: Previously used tags (name→value) for suggestions.
        """
        super().__init__()
        self._saved_tags = saved_tags
        self._saved_names = list(saved_tags.keys())

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container():
            yield Label("Add Tag to PR", id="modal-title")
            yield Label("Tag Name:", id="tag-name-label")
            if self._saved_names:
                yield OptionList(*self._saved_names, id="tag-name-history")
            yield _TagNameInput(
                placeholder="e.g. BUG",
                id="tag-name-input",
            )
            yield Label("Tag Value:", id="tag-value-label")
            yield _TagValueInput(
                placeholder="e.g. 12345",
                id="tag-value-input",
            )

    def on_mount(self) -> None:
        """Focus the tag name input on mount."""
        editor = self.query_one("#tag-name-input", _TagNameInput)
        editor.focus()
        editor._update_vim_mode_display()

    def _navigate_tag_list(self, direction: int) -> None:
        """Navigate the tag name history list.

        Args:
            direction: 1 for next (down), -1 for previous (up).
        """
        try:
            option_list = self.query_one("#tag-name-history", OptionList)
        except Exception:
            return

        if direction > 0:
            option_list.action_cursor_down()
        else:
            option_list.action_cursor_up()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Auto-fill tag name input when a history item is highlighted."""
        option = event.option
        tag_name = option.prompt
        if isinstance(tag_name, str):
            name_input = self.query_one("#tag-name-input", _TagNameInput)
            name_input.value = tag_name
            name_input.cursor_position = len(tag_name)

            # Set last-used value as placeholder on the value input
            last_value = self._saved_tags.get(tag_name, "")
            value_input = self.query_one("#tag-value-input", _TagValueInput)
            value_input.placeholder = last_value if last_value else "e.g. 12345"

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        """Handle Enter key in inputs."""
        if event.text_area.id == "tag-name-input":
            # Move focus to value input
            value_input = self.query_one("#tag-value-input", _TagValueInput)
            value_input.focus()
            value_input._update_vim_mode_display()
        elif event.text_area.id == "tag-value-input":
            # Validate and dismiss
            name = self.query_one("#tag-name-input", _TagNameInput).value.strip()
            value = self.query_one("#tag-value-input", _TagValueInput).value.strip()
            if not name:
                self.notify("Tag name cannot be empty", severity="error")
                self.query_one("#tag-name-input", _TagNameInput).focus()
                return
            if not value:
                self.notify("Tag value cannot be empty", severity="error")
                return
            self.dismiss((name.upper(), value))

    def _delete_highlighted_tag(self) -> None:
        """Delete the currently highlighted tag from history."""
        try:
            option_list = self.query_one("#tag-name-history", OptionList)
        except Exception:
            return

        highlighted = option_list.highlighted
        if highlighted is None:
            return

        tag_name = self._saved_names[highlighted]
        delete_tag(tag_name)

        del self._saved_tags[tag_name]
        del self._saved_names[highlighted]

        option_list.remove_option_at_index(highlighted)

        # Clear inputs if they showed the deleted tag
        name_input = self.query_one("#tag-name-input", _TagNameInput)
        if name_input.value == tag_name:
            name_input.value = ""
            value_input = self.query_one("#tag-value-input", _TagValueInput)
            value_input.placeholder = "e.g. 12345"

        self.notify(f"Deleted tag: {tag_name}")

    def action_cancel(self) -> None:
        """Cancel the modal."""
        self.dismiss(None)
