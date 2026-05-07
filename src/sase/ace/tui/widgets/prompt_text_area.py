"""Custom TextArea with multiline support and vim/readline keybindings."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import TextArea

from sase.ace.tui.widgets._file_completion import FileCompletionMixin
from sase.ace.tui.widgets._line_rendering import LineRenderingMixin
from sase.ace.tui.widgets._snippets import SnippetExpansionMixin
from sase.ace.tui.widgets._text_formatting import TextFormattingMixin
from sase.ace.tui.widgets._vim_normal import VimNormalModeMixin
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.xprompt_arg_assist import (
    ActiveXPromptArgHint,
    named_args_skeleton,
)

if TYPE_CHECKING:
    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

    from ..app import AceApp


def _prompt_bar_class() -> type[PromptInputBar]:
    """Lazy import to avoid circular dependency with prompt_input_bar."""
    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

    return PromptInputBar


class PromptTextArea(
    VimNormalModeMixin,
    FileCompletionMixin,
    SnippetExpansionMixin,
    TextFormattingMixin,
    LineRenderingMixin,
    TextArea,
):
    """Custom TextArea with multiline support and readline-style keybindings.

    Enter submits the prompt. Ctrl+J inserts a newline.
    Line numbers appear automatically when there's more than one line.
    """

    BINDINGS = [
        ("enter", "submit_prompt", "Submit"),
        ("ctrl+j", "insert_newline", "New line"),
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("ctrl+g", "open_editor", "Edit in editor"),
        ("ctrl+y", "open_workflow_editor", "Workflow YAML"),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._vim_mode: str = "insert"
        self._pending_keys: str = ""
        self._count_prefix: str = ""
        self._pending_count: int | None = None
        self._pending_operator: str = ""
        self._pending_operator_count: int = 1
        self._mutation_key_buffer: list[str] = []
        self._last_mutation_keys: list[str] = []
        self._replaying_dot: bool = False
        self._last_char_search: tuple[str, str] | None = None
        self._formatting: bool = False
        self._prettier_format_task: asyncio.Task[None] | None = None
        self._prettier_format_requested_generation: int = 0
        self._prettier_format_completed_generation: int = 0
        self._snippet_tabstops: list[int] = []
        self._snippet_end_from_doc_end: int = 0
        self._file_completion_candidates: list[CompletionCandidate] = []
        self._file_completion_index: int = 0
        self._file_completion_active: bool = False
        self._completion_kind: str = "file"
        self._active_xprompt_arg_hint: ActiveXPromptArgHint | None = None
        self._vcs_mru_index: int | None = None

    @property
    def _ace_app(self) -> AceApp:
        """Get the app as AceApp type."""
        from ..app import AceApp

        assert isinstance(self.app, AceApp)
        return self.app

    def _find_prompt_bar(self) -> Any:
        """Walk up the widget tree to find the parent PromptInputBar."""
        PromptInputBar = _prompt_bar_class()
        parent = self.parent
        while parent is not None:
            if isinstance(parent, PromptInputBar):
                return parent
            parent = parent.parent
        return None

    def action_submit_prompt(self) -> None:
        """Submit the prompt text."""
        self._snippet_tabstops = []
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._vcs_mru_index = None
        bar = self._find_prompt_bar()
        if bar:
            bar._handle_text_submission(self.text)

    def action_insert_newline(self) -> None:
        """Insert a newline at the cursor position."""
        start, end = self.selection
        self._replace_via_keyboard("\n", start, end)

    def action_cursor_line_end(self, select: bool = False) -> None:
        """Move to end of line, or end of next line if already there."""
        row, col = self.cursor_location
        line_end = len(self.document.get_line(row))
        if col >= line_end and row < self.document.line_count - 1:
            next_end = len(self.document.get_line(row + 1))
            self.move_cursor((row + 1, next_end), select=select)
        else:
            super().action_cursor_line_end(select=select)

    def action_cursor_line_start(self, select: bool = False) -> None:
        """Move to start of line, or start of previous line if already there."""
        row, col = self.cursor_location
        if col == 0 and row > 0:
            self.move_cursor((row - 1, 0), select=select)
        else:
            super().action_cursor_line_start(select=select)

    def action_open_editor(self) -> None:
        """Request to open external editor."""
        PromptInputBar = _prompt_bar_class()
        bar = self._find_prompt_bar()
        if bar:
            self._clear_xprompt_arg_hint()
            row, col = self.cursor_location
            bar.post_message(PromptInputBar.EditorRequested(self.text, row, col))

    def action_open_workflow_editor(self) -> None:
        """Request to open workflow YAML editor."""
        bar = self._find_prompt_bar()
        if bar and bar._mode == "feedback":
            return
        PromptInputBar = _prompt_bar_class()
        if bar:
            self._clear_xprompt_arg_hint()
            bar.post_message(PromptInputBar.WorkflowEditorRequested())

    def _enter_normal_mode(self) -> None:
        """Switch to vim NORMAL mode with relative line numbers."""
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._vcs_mru_index = None
        self._vim_mode = "normal"
        self._pending_operator = ""
        self._pending_operator_count = 1
        self._snippet_tabstops = []
        self.read_only = True
        self.show_line_numbers = self.document.line_count > 1
        self.highlight_cursor_line = True
        bar = self._find_prompt_bar()
        if bar:
            bar.border_title = f"{bar._base_title} [NORMAL]"
            bar.border_subtitle = "[Esc] cancel  [i] insert"

    def _enter_insert_mode(self) -> None:
        """Switch to vim INSERT mode."""
        self._vim_mode = "insert"
        self._pending_operator = ""
        self._pending_operator_count = 1
        self.read_only = False
        self.show_line_numbers = self.document.line_count > 1
        self.highlight_cursor_line = False
        bar = self._find_prompt_bar()
        if bar:
            bar.border_title = bar._base_title
            bar.border_subtitle = "[Esc] cancel"

    async def _on_key(self, event: Key) -> None:
        """Intercept keys before TextArea's default handler inserts characters."""
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            if self._file_completion_active:
                self._accept_file_completion()
            else:
                self._clear_xprompt_arg_hint()
                self.action_submit_prompt()
            return

        if event.key == "ctrl+c":
            event.stop()
            event.prevent_default()
            self._clear_file_completion()
            self._clear_xprompt_arg_hint()
            bar = self._find_prompt_bar()
            if bar:
                bar.action_cancel()
            return

        if self._vim_mode == "normal":
            if self._handle_normal_mode_key(event):
                event.stop()
                event.prevent_default()
            return

        # INSERT mode: Escape enters NORMAL mode
        if event.key == "escape":
            if self._file_completion_active:
                event.stop()
                event.prevent_default()
                self._clear_file_completion()
                self._clear_xprompt_arg_hint()
                return
            event.stop()
            event.prevent_default()
            self._enter_normal_mode()
            return

        if self._active_xprompt_arg_hint is not None and event.character in (":", "("):
            if self._can_apply_xprompt_arg_action():
                event.stop()
                event.prevent_default()
                if event.character == ":":
                    self._apply_xprompt_colon_arg_hint()
                else:
                    self._apply_xprompt_named_arg_hint()
                return
            self._clear_xprompt_arg_hint()

        # Active file completion navigation / acceptance.
        if self._file_completion_active:
            if event.key in ("ctrl+n", "down"):
                event.stop()
                event.prevent_default()
                self._move_file_completion(1)
                return
            if event.key in ("ctrl+p", "up"):
                event.stop()
                event.prevent_default()
                self._move_file_completion(-1)
                return
            if event.key == "ctrl+l":
                event.stop()
                event.prevent_default()
                self._accept_file_completion()
                return
            if event.key == "ctrl+d" and self._completion_kind == "file_history":
                event.stop()
                event.prevent_default()
                self._delete_selected_file_completion()
                return

        # VCS MRU cycling: ctrl+n/ctrl+p when prompt is empty or VCS-only
        if not self._file_completion_active and event.key in ("ctrl+n", "ctrl+p"):
            from sase.xprompt._parsing import extract_vcs_workflow_tag

            text = self.text
            stripped = text.strip()
            is_vcs_only = not stripped
            current_prefix: str | None = None

            if stripped:
                # Append space for pattern matching (VCS pattern requires trailing \s)
                tag = extract_vcs_workflow_tag(stripped + " ")
                if tag is not None and stripped == tag.strip():
                    is_vcs_only = True
                    current_prefix = stripped

            if is_vcs_only:
                from sase.history.vcs_xprompt_mru import load_vcs_xprompt_mru

                mru = load_vcs_xprompt_mru()
                if mru:
                    direction = -1 if event.key == "ctrl+n" else 1
                    if self._vcs_mru_index is not None:
                        new_index = (self._vcs_mru_index + direction) % len(mru)
                    elif current_prefix is not None and current_prefix in mru:
                        base = mru.index(current_prefix)
                        new_index = (base + direction) % len(mru)
                    else:
                        new_index = 0 if direction == 1 else len(mru) - 1

                    self._vcs_mru_index = new_index
                    new_text = mru[new_index] + " "
                    self.text = new_text
                    self.move_cursor((0, len(new_text)))
                    event.stop()
                    event.prevent_default()
                    return

        # Ctrl+T in INSERT mode: trigger file path completion
        if event.key == "ctrl+t":
            event.stop()
            event.prevent_default()
            self._try_file_completion_tab()
            return

        # Tab in INSERT mode: expand snippet or advance tabstop (never insert literal tab)
        if event.key == "tab":
            event.stop()
            event.prevent_default()
            if self._try_expand_snippet():
                return
            self._try_advance_tabstop()
            return

        # Detect '#@' trigger before the '@' is inserted (skip in feedback mode)
        if event.character == "@":
            bar = self._find_prompt_bar()
            if bar and bar._mode != "feedback":
                row, col = self.cursor_location
                if col > 0:
                    line = self.document.get_line(row)
                    if line[col - 1] == "#":
                        PromptInputBar = _prompt_bar_class()
                        bar.post_message(PromptInputBar.SnippetRequested())
                        event.stop()
                        event.prevent_default()
                        return
        await super()._on_key(event)

        # Reset VCS MRU cycling on any non-cycling keypress
        if self._vcs_mru_index is not None:
            self._vcs_mru_index = None

        self._refresh_file_completion_from_cursor()
        self._refresh_xprompt_arg_hint_from_cursor()

        # Auto-wrap: reflow with prettier when line exceeds available width.
        # Skip wrapping on space so the user's trailing space is never consumed
        # by the line break — wrapping will fire on the next non-space character
        # when the space has become an interior word separator.
        if (
            self._vim_mode == "insert"
            and event.character
            and event.character.isprintable()
            and event.character != " "
        ):
            self._schedule_prettier_format()

    def _on_resize(self) -> None:
        """Scroll cursor into view after the parent resizes."""
        super()._on_resize()
        self.call_after_refresh(self.scroll_cursor_visible)

    def on_blur(self) -> None:
        """Schedule a deferred refocus when the text area loses focus."""
        self.call_later(self._refocus_if_needed)

    def on_unmount(self) -> None:
        """Cancel any pending async formatter task when widget is removed."""
        self._cancel_pending_prettier_format()

    def _absolute_offset(self, location: tuple[int, int]) -> int:
        """Convert a document location to an absolute character offset."""
        row, col = location
        return sum(len(self.document.get_line(r)) + 1 for r in range(row)) + col

    def _location_from_absolute(self, offset: int) -> tuple[int, int]:
        """Convert an absolute character offset to a document location."""
        remaining = max(0, offset)
        for row in range(self.document.line_count):
            line_len = len(self.document.get_line(row))
            if remaining <= line_len:
                return row, remaining
            remaining -= line_len + 1
        last_row = self.document.line_count - 1
        return last_row, len(self.document.get_line(last_row))

    def _show_xprompt_arg_hint(self, hint: ActiveXPromptArgHint) -> None:
        """Render the active xprompt argument hint through the prompt bar."""
        bar = self._find_prompt_bar()
        if bar:
            bar.show_xprompt_arg_hint(hint)

    def _clear_xprompt_arg_hint(self) -> None:
        """Clear active xprompt argument hint state and hide its panel."""
        if self._active_xprompt_arg_hint is None:
            return
        self._active_xprompt_arg_hint = None
        bar = self._find_prompt_bar()
        if bar and not self._file_completion_active:
            bar.hide_file_completions()

    def _active_xprompt_hint_is_current(self) -> bool:
        hint = self._active_xprompt_arg_hint
        if hint is None:
            return False
        return (
            self.text[hint.reference_start : hint.reference_end] == hint.reference_text
        )

    def _refresh_xprompt_arg_hint_from_cursor(self) -> None:
        """Dismiss post-accept hints when edits move outside the reference."""
        hint = self._active_xprompt_arg_hint
        if hint is None:
            return
        if not self._active_xprompt_hint_is_current():
            self._clear_xprompt_arg_hint()
            return
        cursor_offset = self._absolute_offset(self.cursor_location)
        if cursor_offset != hint.reference_end:
            self._clear_xprompt_arg_hint()

    def _can_apply_xprompt_arg_action(self) -> bool:
        """Return True when an active hint can consume syntax action keys."""
        hint = self._active_xprompt_arg_hint
        if hint is None or not self._active_xprompt_hint_is_current():
            return False
        return self._absolute_offset(self.cursor_location) == hint.reference_end

    def _apply_xprompt_colon_arg_hint(self) -> bool:
        """Rewrite the accepted reference with colon-argument syntax."""
        hint = self._active_xprompt_arg_hint
        if hint is None or not self._active_xprompt_hint_is_current():
            self._clear_xprompt_arg_hint()
            return False
        if self._absolute_offset(self.cursor_location) != hint.reference_end:
            self._clear_xprompt_arg_hint()
            return False

        start = self._location_from_absolute(hint.reference_start)
        end = self._location_from_absolute(hint.reference_end)
        replacement = f"{hint.entry.insertion}:"
        self._replace_via_keyboard(replacement, start, end)
        new_end = hint.reference_start + len(replacement)
        self.cursor_location = self._location_from_absolute(new_end)
        next_hint = ActiveXPromptArgHint(
            entry=hint.entry,
            reference_start=hint.reference_start,
            reference_end=new_end,
            reference_text=replacement,
            trigger_mode="colon",
            active_input_index=hint.active_input_index,
        )
        self._active_xprompt_arg_hint = next_hint
        self._show_xprompt_arg_hint(next_hint)
        return True

    def _apply_xprompt_named_arg_hint(self) -> bool:
        """Rewrite the accepted reference with a named-argument snippet."""
        hint = self._active_xprompt_arg_hint
        if hint is None or not self._active_xprompt_hint_is_current():
            self._clear_xprompt_arg_hint()
            return False
        if self._absolute_offset(self.cursor_location) != hint.reference_end:
            self._clear_xprompt_arg_hint()
            return False

        start = self._location_from_absolute(hint.reference_start)
        end = self._location_from_absolute(hint.reference_end)
        self._clear_xprompt_arg_hint()
        return self._expand_snippet_template_at_range(
            named_args_skeleton(hint.entry),
            start,
            end,
        )

    def _refocus_if_needed(self) -> None:
        """Refocus this text area unless a modal is active."""
        if self.is_mounted and not isinstance(self.app.screen, ModalScreen):
            self.focus()
