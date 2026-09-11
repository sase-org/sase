"""Status chip state for ``PromptInputBar``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.widgets._todo_highlight import (
    todo_annotation_count,
    todo_theme_colors,
)
from sase.ace.tui.widgets.prompt_stack import PromptStackState
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object


class PromptInputBarStatusMixin(_MixinBase):
    """TODO and active-pane Jinja chip helpers."""

    if TYPE_CHECKING:
        _stack: PromptStackState
        _todo_counts_by_item_id: dict[str, int]

        def _pane_id(self, item: object) -> str: ...
        def active_text_area(self) -> object: ...

    def _todo_chip_markup(self) -> str:
        """Return the running-gold whole-stack TODO count capsule."""
        count = sum(self._todo_counts_by_item_id.values())
        if count <= 0:
            return ""
        try:
            theme = self.app.current_theme
        except Exception:
            chip_foreground, chip_background, _note_foreground = todo_theme_colors(
                None,
                dark=True,
            )
        else:
            chip_foreground, chip_background, _note_foreground = todo_theme_colors(
                theme.foreground,
                dark=theme.dark,
            )
        return f"[bold {chip_foreground.hex} on {chip_background.hex}] TODO {count} [/]"

    def _sync_todo_counts_from_stack(self) -> None:
        """Refresh count state from the in-memory stack during construction/rebuild."""
        self._todo_counts_by_item_id = {
            item.item_id: todo_annotation_count(item.text)
            for item in self._stack.agent_items
        }

    def _sync_todo_counts_from_mounted_panes(self) -> None:
        """Aggregate each mounted pane's cached annotation count."""
        counts: dict[str, int] = {}
        for item in self._stack.agent_items:
            try:
                text_area = self.query_one(f"#{self._pane_id(item)}", PromptTextArea)
            except Exception:
                counts[item.item_id] = self._todo_counts_by_item_id.get(item.item_id, 0)
                continue
            counts[item.item_id] = text_area.todo_annotation_count
        self._todo_counts_by_item_id = counts

    def _update_todo_count_for_text_area(self, text_area: object) -> None:
        """Update only the edited pane's cached stack count."""
        if not isinstance(text_area, PromptTextArea):
            return
        item = next(
            (
                item
                for item in self._stack.agent_items
                if self._pane_id(item) == text_area.id
            ),
            None,
        )
        if item is not None:
            self._todo_counts_by_item_id[item.item_id] = text_area.todo_annotation_count

    def _active_jinja_chip_markup(self) -> str:
        """Return the active pane's Jinja2 status chip markup."""
        try:
            text_area = self.active_text_area()
        except Exception:
            return ""
        chip = getattr(text_area, "_jinja_chip_markup", None)
        if not callable(chip):
            return ""
        return str(chip())
