"""Custom TextArea with multiline support and vim/readline keybindings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.segment import Segment
from rich.style import Style
from textual.events import Key
from textual.strip import Strip
from textual.widgets import TextArea

from sase.ace.tui.widgets._vim_motions import (
    find_next_word_end,
    find_next_word_start,
    find_next_WORD_end,
    find_next_WORD_start,
    find_prev_word_start,
    find_prev_WORD_start,
)

if TYPE_CHECKING:
    from ..app import AceApp
    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


def _prompt_bar_class() -> type[PromptInputBar]:
    """Lazy import to avoid circular dependency with prompt_input_bar."""
    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

    return PromptInputBar


class PromptTextArea(TextArea):
    """Custom TextArea with multiline support and readline-style keybindings.

    Enter submits the prompt. Ctrl+J inserts a newline.
    Line numbers appear automatically when there's more than one line.
    """

    # Shared state: last cancelled prompt text (also accessed by PromptInputBar)
    _last_cancelled_prompt: str = ""

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
        bar = self._find_prompt_bar()
        if bar:
            bar._handle_text_submission(self.text)

    def action_insert_newline(self) -> None:
        """Insert a newline at the cursor position."""
        start, end = self.selection
        self._replace_via_keyboard("\n", start, end)

    def _get_wrap_width(self) -> int:
        """Get the width at which to auto-wrap text.

        Always accounts for the gutter since line numbers appear when
        line_count > 1 (which will be the case after wrapping).
        """
        text_width = self.size.width
        if text_width <= 0:
            return 0
        # Reserve space for the gutter that will appear after wrapping
        gutter_width = len(str(max(self.document.line_count, 2))) + 2
        return max(text_width - gutter_width, 1)

    def _auto_wrap_line(self) -> None:
        """Insert a newline when the cursor's line exceeds available width."""
        wrap_width = self._get_wrap_width()
        if wrap_width <= 0:
            return

        row, col = self.cursor_location
        line = self.document.get_line(row)

        if len(line) <= wrap_width:
            return

        # Insert newline at the wrap boundary
        self._replace_via_keyboard("\n", (row, wrap_width), (row, wrap_width))

        # _replace_via_keyboard places cursor at (row+1, 0); adjust it
        # so it stays at the same position relative to the text.
        if col >= wrap_width:
            self.cursor_location = (row + 1, col - wrap_width)
        else:
            self.cursor_location = (row, col)

    def action_open_editor(self) -> None:
        """Request to open external editor."""
        PromptInputBar = _prompt_bar_class()
        bar = self._find_prompt_bar()
        if bar:
            row, col = self.cursor_location
            bar.post_message(PromptInputBar.EditorRequested(self.text, row, col))

    def action_open_workflow_editor(self) -> None:
        """Request to open workflow YAML editor."""
        PromptInputBar = _prompt_bar_class()
        bar = self._find_prompt_bar()
        if bar:
            bar.post_message(PromptInputBar.WorkflowEditorRequested())

    def action_cursor_line_end(self, select: bool = False) -> None:
        """Move to end of line, or fill last cancelled prompt if empty."""
        if not self.text and PromptTextArea._last_cancelled_prompt:
            self.text = PromptTextArea._last_cancelled_prompt
            doc = self.document
            last_line = doc.line_count - 1
            last_col = len(doc.get_line(last_line))
            self.cursor_location = (last_line, last_col)
        else:
            super().action_cursor_line_end(select)

    def _enter_normal_mode(self) -> None:
        """Switch to vim NORMAL mode with relative line numbers."""
        self._vim_mode = "normal"
        self._pending_operator = ""
        self._pending_operator_count = 1
        self.read_only = True
        self.show_line_numbers = True
        self.highlight_cursor_line = True
        bar = self._find_prompt_bar()
        if bar:
            bar.border_title = "Prompt [NORMAL]"
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
            bar.border_title = "Prompt"
            cancelled = PromptTextArea._last_cancelled_prompt
            if cancelled:
                hint = cancelled[:40] + "…" if len(cancelled) > 40 else cancelled
                bar.border_subtitle = f"[^E] {hint}"
            else:
                bar.border_subtitle = "[Esc] cancel"

    def _update_count_display(self) -> None:
        """Update border subtitle to show the pending count/operator."""
        bar = self._find_prompt_bar()
        if bar:
            indicator = ""
            if self._pending_operator:
                if self._pending_operator_count > 1:
                    indicator += str(self._pending_operator_count)
                indicator += self._pending_operator
            if self._count_prefix:
                indicator += self._count_prefix
            if indicator:
                bar.border_subtitle = f"[Esc] cancel  [i] insert  {indicator}"
            else:
                bar.border_subtitle = "[Esc] cancel  [i] insert"

    def _clear_count_prefix(self) -> None:
        """Clear count prefix and update display if needed."""
        if self._count_prefix:
            self._count_prefix = ""
            self._update_count_display()

    def _consume_pending_operator(self, count: int) -> tuple[str, int] | None:
        """Consume pending operator state if present.

        Returns ``(operator, effective_count)`` where *effective_count* is the
        product of the operator's stored count and the given motion *count*, or
        ``None`` when no operator is pending.
        """
        if not self._pending_operator:
            return None
        op = self._pending_operator
        op_count = self._pending_operator_count
        self._pending_operator = ""
        self._pending_operator_count = 1
        self._update_count_display()
        return (op, op_count * count)

    def _execute_charwise_operator(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        op: str,
    ) -> None:
        """Execute a charwise ``d``/``c`` operator over *start*..*end*."""
        if start > end:
            start, end = end, start
        if start == end:
            if op == "c":
                self._enter_insert_mode()
            return
        was_readonly = self.read_only
        self.read_only = False
        self.delete(start, end)
        if op == "c":
            self._enter_insert_mode()
        else:
            self.read_only = was_readonly
        self.cursor_location = start

    def _execute_linewise_operator(
        self,
        first_row: int,
        last_row: int,
        op: str,
    ) -> None:
        """Execute a linewise ``d``/``c`` operator on rows *first_row* .. *last_row*."""
        doc = self.document
        first_row = max(0, first_row)
        last_row = min(last_row, doc.line_count - 1)

        was_readonly = self.read_only
        self.read_only = False

        if op == "c":
            # Change: clear line contents but keep one empty line.
            last_line = doc.get_line(last_row)
            self.delete((first_row, 0), (last_row, len(last_line)))
            self._enter_insert_mode()
            self.cursor_location = (first_row, 0)
        else:
            # Delete: remove lines entirely.
            if first_row == 0 and last_row >= doc.line_count - 1:
                last_line = doc.get_line(last_row)
                self.delete((0, 0), (last_row, len(last_line)))
                self.cursor_location = (0, 0)
            elif last_row >= doc.line_count - 1:
                prev_line = doc.get_line(first_row - 1)
                last_line = doc.get_line(last_row)
                self.delete(
                    (first_row - 1, len(prev_line)),
                    (last_row, len(last_line)),
                )
                self.cursor_location = (first_row - 1, 0)
            else:
                self.delete((first_row, 0), (last_row + 1, 0))
                self.cursor_location = (first_row, 0)
            self.read_only = was_readonly

    def _handle_normal_mode_key(self, event: Key) -> bool:
        """Handle a key event in NORMAL mode. Returns True if handled."""
        key = event.character or event.key

        # Handle pending key sequences (gg) ----------------------------------
        if self._pending_keys:
            pending = self._pending_keys
            self._pending_keys = ""
            pending_count = self._pending_count
            self._pending_count = None
            self._clear_count_prefix()
            if pending == "g" and key == "g":
                if pending_count is not None:
                    target = max(
                        0, min(pending_count - 1, self.document.line_count - 1)
                    )
                else:
                    target = 0
                if self._pending_operator:
                    op = self._pending_operator
                    self._pending_operator = ""
                    self._pending_operator_count = 1
                    cur_row = self.cursor_location[0]
                    first = min(cur_row, target)
                    last = max(cur_row, target)
                    self._execute_linewise_operator(first, last, op)
                    self._update_count_display()
                else:
                    self.cursor_location = (target, 0)
            return True

        # Escape --------------------------------------------------------------
        if event.key == "escape":
            if self._pending_operator:
                self._pending_operator = ""
                self._pending_operator_count = 1
                self._clear_count_prefix()
                self._update_count_display()
                return True
            self._clear_count_prefix()
            bar = self._find_prompt_bar()
            if bar:
                bar.action_cancel()
            return True

        # Count prefix accumulation: 1-9 starts, 0 appends to existing
        if key in "123456789" or (key == "0" and self._count_prefix):
            self._count_prefix += key
            self._update_count_display()
            return True

        # Consume count prefix
        has_count = bool(self._count_prefix)
        count = int(self._count_prefix) if self._count_prefix else 1
        self._clear_count_prefix()

        # Operator doubling (dd, cc) -----------------------------------------
        if self._pending_operator and key == self._pending_operator:
            op = self._pending_operator
            op_count = self._pending_operator_count
            self._pending_operator = ""
            self._pending_operator_count = 1
            total = op_count * count
            cur_row = self.cursor_location[0]
            last_row = min(cur_row + total - 1, self.document.line_count - 1)
            self._execute_linewise_operator(cur_row, last_row, op)
            self._update_count_display()
            return True

        # Start operator-pending mode (d, c) ---------------------------------
        if key in ("d", "c") and not self._pending_operator:
            self._pending_operator = key
            self._pending_operator_count = count
            self._update_count_display()
            return True

        # --- Motions (with optional operator application) --------------------

        # Basic character movement
        if key == "h":
            op_info = self._consume_pending_operator(count)
            if op_info:
                op, eff = op_info
                row, col = self.cursor_location
                target_col = max(0, col - eff)
                self._execute_charwise_operator((row, target_col), (row, col), op)
            else:
                for _ in range(count):
                    self.action_cursor_left()
            return True
        if key == "j":
            op_info = self._consume_pending_operator(count)
            if op_info:
                op, eff = op_info
                cur_row = self.cursor_location[0]
                target = min(cur_row + eff, self.document.line_count - 1)
                self._execute_linewise_operator(cur_row, target, op)
            else:
                for _ in range(count):
                    self.action_cursor_down()
            return True
        if key == "k":
            op_info = self._consume_pending_operator(count)
            if op_info:
                op, eff = op_info
                cur_row = self.cursor_location[0]
                target = max(cur_row - eff, 0)
                self._execute_linewise_operator(target, cur_row, op)
            else:
                for _ in range(count):
                    self.action_cursor_up()
            return True
        if key == "l":
            op_info = self._consume_pending_operator(count)
            if op_info:
                op, eff = op_info
                row, col = self.cursor_location
                line = self.document.get_line(row)
                target_col = min(len(line), col + eff)
                self._execute_charwise_operator((row, col), (row, target_col), op)
            else:
                for _ in range(count):
                    self.action_cursor_right()
            return True

        # Word motions
        doc = self.document
        if key == "w":
            op_info = self._consume_pending_operator(count)
            eff = op_info[1] if op_info else count
            r, c = self.cursor_location
            for _ in range(eff):
                r, c = find_next_word_start(doc, r, c)
            if op_info:
                self._execute_charwise_operator(
                    self.cursor_location, (r, c), op_info[0]
                )
            else:
                self.cursor_location = (r, c)
            return True
        if key == "W":
            op_info = self._consume_pending_operator(count)
            eff = op_info[1] if op_info else count
            r, c = self.cursor_location
            for _ in range(eff):
                r, c = find_next_WORD_start(doc, r, c)
            if op_info:
                self._execute_charwise_operator(
                    self.cursor_location, (r, c), op_info[0]
                )
            else:
                self.cursor_location = (r, c)
            return True
        if key == "b":
            op_info = self._consume_pending_operator(count)
            eff = op_info[1] if op_info else count
            r, c = self.cursor_location
            for _ in range(eff):
                r, c = find_prev_word_start(doc, r, c)
            if op_info:
                self._execute_charwise_operator(
                    (r, c), self.cursor_location, op_info[0]
                )
            else:
                self.cursor_location = (r, c)
            return True
        if key == "B":
            op_info = self._consume_pending_operator(count)
            eff = op_info[1] if op_info else count
            r, c = self.cursor_location
            for _ in range(eff):
                r, c = find_prev_WORD_start(doc, r, c)
            if op_info:
                self._execute_charwise_operator(
                    (r, c), self.cursor_location, op_info[0]
                )
            else:
                self.cursor_location = (r, c)
            return True
        if key == "e":
            op_info = self._consume_pending_operator(count)
            eff = op_info[1] if op_info else count
            r, c = self.cursor_location
            for _ in range(eff):
                r, c = find_next_word_end(doc, r, c)
            if op_info:
                # Inclusive: extend end past the last character
                self._execute_charwise_operator(
                    self.cursor_location, (r, c + 1), op_info[0]
                )
            else:
                self.cursor_location = (r, c)
            return True
        if key == "E":
            op_info = self._consume_pending_operator(count)
            eff = op_info[1] if op_info else count
            r, c = self.cursor_location
            for _ in range(eff):
                r, c = find_next_WORD_end(doc, r, c)
            if op_info:
                # Inclusive: extend end past the last character
                self._execute_charwise_operator(
                    self.cursor_location, (r, c + 1), op_info[0]
                )
            else:
                self.cursor_location = (r, c)
            return True

        # Line position motions
        if key == "0":
            op_info = self._consume_pending_operator(count)
            if op_info:
                row, col = self.cursor_location
                self._execute_charwise_operator((row, 0), (row, col), op_info[0])
            else:
                row = self.cursor_location[0]
                self.cursor_location = (row, 0)
            return True
        if key == "$":
            op_info = self._consume_pending_operator(count)
            if op_info:
                row, col = self.cursor_location
                line = doc.get_line(row)
                self._execute_charwise_operator(
                    (row, col), (row, len(line)), op_info[0]
                )
            else:
                row = self.cursor_location[0]
                line = doc.get_line(row)
                self.cursor_location = (row, len(line))
            return True
        if key == "^":
            op_info = self._consume_pending_operator(count)
            row = self.cursor_location[0]
            line = doc.get_line(row)
            nws = 0
            while nws < len(line) and line[nws].isspace():
                nws += 1
            if op_info:
                col = self.cursor_location[1]
                self._execute_charwise_operator(
                    (row, min(col, nws)), (row, max(col, nws)), op_info[0]
                )
            else:
                self.cursor_location = (row, nws)
            return True

        # Document motions
        if key == "g":
            self._pending_keys = "g"
            self._pending_count = count if has_count else None
            # Keep pending operator for gg resolution
            return True
        if key == "G":
            op_info = self._consume_pending_operator(1)
            if op_info:
                op = op_info[0]
                if has_count:
                    target = max(0, min(count - 1, self.document.line_count - 1))
                else:
                    target = self.document.line_count - 1
                cur_row = self.cursor_location[0]
                first = min(cur_row, target)
                last = max(cur_row, target)
                self._execute_linewise_operator(first, last, op)
            else:
                if has_count:
                    target = max(0, min(count - 1, self.document.line_count - 1))
                    self.cursor_location = (target, 0)
                else:
                    last_row = self.document.line_count - 1
                    self.cursor_location = (last_row, 0)
            return True

        # Cancel pending operator on unrecognized motion key
        if self._pending_operator:
            self._pending_operator = ""
            self._pending_operator_count = 1
            self._update_count_display()
            return True

        # Mode switching
        if key == "i":
            self._enter_insert_mode()
            return True
        if key == "a":
            row, col = self.cursor_location
            line = self.document.get_line(row)
            self._enter_insert_mode()
            if col < len(line):
                self.cursor_location = (row, col + 1)
            return True
        if key == "A":
            row = self.cursor_location[0]
            line = self.document.get_line(row)
            self._enter_insert_mode()
            self.cursor_location = (row, len(line))
            return True
        if key == "I":
            row = self.cursor_location[0]
            line = self.document.get_line(row)
            col = 0
            while col < len(line) and line[col].isspace():
                col += 1
            self._enter_insert_mode()
            self.cursor_location = (row, col)
            return True
        if key == "o":
            row = self.cursor_location[0]
            line = self.document.get_line(row)
            self._enter_insert_mode()
            self.cursor_location = (row, len(line))
            start, end = self.selection
            self._replace_via_keyboard("\n", start, end)
            return True
        if key == "O":
            row = self.cursor_location[0]
            self._enter_insert_mode()
            self.cursor_location = (row, 0)
            start, end = self.selection
            self._replace_via_keyboard("\n", start, end)
            self.cursor_location = (row, 0)
            return True

        # Unhandled key - let it through for arrow keys, etc.
        return False

    def render_line(self, y: int) -> Strip:
        """Bypass cache in NORMAL mode so relative line numbers stay current."""
        if self._vim_mode == "normal" and self.show_line_numbers:
            return self._render_line(y)
        if self._vim_mode != "normal" and self.show_line_numbers:
            return self._render_insert_line(y)
        return super().render_line(y)

    def _render_insert_line(self, y: int) -> Strip:
        """Color absolute line numbers in INSERT mode with cyan (#3AA99F)."""
        strip = super().render_line(y)
        if not self.show_line_numbers:
            return strip

        _scroll_x, scroll_y = self.scroll_offset
        y_offset = y + scroll_y

        if y_offset >= self.wrapped_document.height:
            return strip

        try:
            line_info = self.wrapped_document._offset_to_line_info[y_offset]
        except IndexError:
            return strip

        if line_info is None:
            return strip

        _line_index, section_offset = line_info
        if section_offset != 0:
            return strip

        gutter_style = (self._theme.gutter_style or Style.null()) + Style(
            color="#3AA99F"
        )
        segments = list(strip._segments)
        if segments:
            segments[0] = Segment(segments[0].text, gutter_style)
            return Strip(segments, strip.cell_length)

        return strip

    def _render_line(self, y: int) -> Strip:
        """Show relative line numbers in NORMAL mode."""
        strip = super()._render_line(y)
        if self._vim_mode != "normal" or not self.show_line_numbers:
            return strip

        _scroll_x, scroll_y = self.scroll_offset
        y_offset = y + scroll_y

        if y_offset >= self.wrapped_document.height:
            return strip

        try:
            line_info = self.wrapped_document._offset_to_line_info[y_offset]
        except IndexError:
            return strip

        if line_info is None:
            return strip

        line_index, section_offset = line_info
        if section_offset != 0:
            return strip

        cursor_row = self.cursor_location[0]
        if line_index == cursor_row:
            gutter_content = str(line_index + 1)
        else:
            gutter_content = str(abs(line_index - cursor_row))

        gutter_width = self.gutter_width
        gutter_width_no_margin = gutter_width - 2

        theme = self._theme
        if line_index == cursor_row:
            base = (
                (theme.cursor_line_gutter_style or Style.null())
                if self.highlight_cursor_line
                else Style.null()
            )
            gutter_style = base + Style(color="#D0A215", bold=True)
        elif line_index < cursor_row:
            gutter_style = (theme.gutter_style or Style.null()) + Style(color="#4385BE")
        else:
            gutter_style = (theme.gutter_style or Style.null()) + Style(color="#8B7EC8")

        new_gutter = Segment(
            f"{gutter_content:>{gutter_width_no_margin}}  ", gutter_style
        )
        segments = list(strip._segments)
        if segments:
            segments[0] = new_gutter
            return Strip(segments, strip.cell_length)

        return strip

    async def _on_key(self, event: Key) -> None:
        """Intercept keys before TextArea's default handler inserts characters."""
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.action_submit_prompt()
            return

        if self._vim_mode == "normal":
            if self._handle_normal_mode_key(event):
                event.stop()
                event.prevent_default()
            return

        # INSERT mode: Escape enters NORMAL mode
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self._enter_normal_mode()
            return

        # Detect '##' trigger before the second '#' is inserted
        if event.character == "#":
            PromptInputBar = _prompt_bar_class()
            row, col = self.cursor_location
            if col > 0:
                line = self.document.get_line(row)
                if line[col - 1] == "#":
                    bar = self._find_prompt_bar()
                    if bar:
                        bar.post_message(PromptInputBar.SnippetRequested())
                        event.stop()
                        event.prevent_default()
                        return
        await super()._on_key(event)

        # Auto-wrap: insert newline when line exceeds available width
        if (
            self._vim_mode == "insert"
            and event.character
            and event.character.isprintable()
        ):
            self._auto_wrap_line()
