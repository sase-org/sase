"""Go-to-line prompt and last-jump mark for ``PagerScreen``."""

from __future__ import annotations

from typing import Any

from textual.events import Key
from textual.widgets import Static

from sase.pager._chrome import goto_command_line, section_accent
from sase.pager._layout import ComposedBody
from sase.pager._line_mark import LineMark, reading_scroll_y


class PagerGotoMixin:
    """Own the ``;`` / ``:`` prompt, its key handling, and the last-jump mark."""

    _body: ComposedBody | None
    _body_width: int | None
    _goto_active: bool
    _goto_digits: str
    _goto_mark: LineMark | None

    def _init_goto_state(self: Any) -> None:
        self._goto_active = False
        self._goto_digits = ""
        self._goto_mark = None

    def action_goto_line(self: Any) -> None:
        if self._goto_active:
            return
        if self._current_section_line_count() <= 0:
            self.notify("Nothing to jump to.", severity="warning")
            return
        self._goto_active = True
        self._goto_digits = ""
        command = self.query_one("#pager-goto-command", Static)
        command.remove_class("hidden")
        self._update_goto_command()

    def handle_goto_key(self: Any, event: Key) -> bool:
        """Consume every key while the prompt is open; else decline."""
        if not self._goto_active:
            return False
        if event.key == "escape":
            self._close_goto_prompt()
            return True
        if event.key == "enter":
            self._submit_goto()
            return True
        if event.key == "backspace":
            if not self._goto_digits:
                self._close_goto_prompt()
                return True
            self._goto_digits = self._goto_digits[:-1]
            self._update_goto_command()
            return True
        character = event.character if event.character is not None else event.key
        if character in "0123456789":
            self._goto_digits += character
            self._update_goto_command()
            return True
        return True

    def _submit_goto(self: Any) -> None:
        if not self._goto_digits:
            self._close_goto_prompt()
            return
        value = int(self._goto_digits)
        line_count = self._current_section_line_count()
        if value == 0 or value > line_count:
            self.notify(
                f"Line {value} is out of range (1-{line_count}).",
                severity="warning",
            )
            self._update_goto_command()
            return
        section_index = self._current_section_index()
        mark = LineMark(section_index, value, value)
        self._goto_mark = mark
        self._close_goto_prompt()
        self._body_width = None
        self._ensure_body()
        self._scroll_to_line_mark(mark)
        self._after_scroll()

    def _clear_goto_state(self: Any) -> None:
        self._goto_mark = None
        self._close_goto_prompt()

    def _close_goto_prompt(self: Any) -> None:
        self._goto_active = False
        self._goto_digits = ""
        command = self.query_one("#pager-goto-command", Static)
        command.update("")
        command.add_class("hidden")

    def _update_goto_command(self: Any) -> None:
        if not self._goto_active:
            return
        section = self._current_section_or_none()
        multi = len(self.document.sections) > 1
        self.query_one("#pager-goto-command", Static).update(
            goto_command_line(
                digits=self._goto_digits,
                line_count=self._current_section_line_count(),
                section_title=None if section is None or not multi else section.title,
                section_kind=None if section is None or not multi else section.kind,
                width=self._goto_command_width(),
            )
        )

    def _goto_command_width(self: Any) -> int:
        command = self.query_one("#pager-goto-command", Static)
        width = int(command.size.width) - 2
        if width <= 0:
            width = max(int(self._body_scroll().size.width) - 2, 1)
        return max(width, 1)

    def _current_section_line_count(self: Any) -> int:
        if not self.document.sections:
            return 0
        body = self._body
        if body is None:
            self._ensure_body()
            body = self._body
        if body is None:
            return 0
        index = self._current_section_index()
        counts = body.section_line_counts
        if not 0 <= index < len(counts):
            return 0
        return counts[index]

    def _goto_accent_for_mark(self: Any) -> str | None:
        mark = self._goto_mark
        if mark is None or not 0 <= mark.section_index < len(self.document.sections):
            return None
        return section_accent(self.document.sections[mark.section_index].kind)

    def _scroll_to_line_mark(self: Any, mark: LineMark) -> None:
        start_row = self._row_for_section_line(mark.section_index, mark.start_line)
        if start_row is None:
            return
        end_row = self._last_row_for_section_line(mark.section_index, mark.end_line)
        if end_row is None:
            end_row = start_row
        scroll = self._body_scroll()
        y = reading_scroll_y(
            start_row=start_row,
            end_row=end_row,
            viewport_height=max(int(scroll.size.height), 1),
            max_scroll_y=int(scroll.max_scroll_y),
        )
        scroll.scroll_to(y=y, animate=False, immediate=True)

    def _line_mark_for_landing(
        self: Any,
        *,
        line: int | None,
        end_line: int | None,
    ) -> LineMark | None:
        if line is None:
            return None
        body = self._body
        if body is None or not body.section_line_counts:
            return None
        line_count = body.section_line_counts[0]
        if line_count <= 0:
            return None
        start = line if line >= 1 else 1
        past_eof = start > line_count
        if past_eof:
            start = line_count
        end = start
        if end_line is not None and end_line >= start:
            end = min(end_line, line_count)
        if past_eof:
            title = self.document.title
            self.notify(
                f"{title} has {line_count} lines — showing line {line_count}.",
                severity="information",
            )
        return LineMark(0, start, end)


__all__ = ["PagerGotoMixin"]
