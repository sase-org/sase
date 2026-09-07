"""Go-to-line prompt and last-jump mark for ``PagerScreen``."""

from __future__ import annotations

from typing import Any

from textual.events import Key
from textual.widgets import Static

from sase.pager._chrome import goto_command_line, section_accent
from sase.pager._layout import ComposedBody


class PagerGotoMixin:
    """Own the ``;`` / ``:`` prompt, its key handling, and the last-jump mark."""

    _body: ComposedBody | None
    _body_width: int | None
    _goto_active: bool
    _goto_digits: str
    _goto_mark: tuple[int, int] | None

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
        row = self._row_for_section_line(section_index, value)
        self._goto_mark = (section_index, value)
        self._close_goto_prompt()
        self._body_width = None
        self._ensure_body()
        if row is not None:
            self._body_scroll().scroll_to(y=row, animate=False, immediate=True)
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
        if mark is None or not 0 <= mark[0] < len(self.document.sections):
            return None
        return section_accent(self.document.sections[mark[0]].kind)


__all__ = ["PagerGotoMixin"]
