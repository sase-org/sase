"""PromptTextArea cursor and delete action overrides.

Each inherited ``TextArea`` motion / deletion action is wrapped so the prompt
assist surfaces (completion menu, xprompt arg hint) follow the cursor, and the
two delete actions first give the paired-delimiter planners a chance to remove
both halves of an empty auto-pair.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.widgets._jinja_pair_editing import (
    plan_jinja_delete_left,
    plan_jinja_delete_right,
)
from sase.ace.tui.widgets._paired_text_editing import (
    plan_pair_delete_left,
    plan_pair_delete_right,
)
from sase.ace.tui.widgets._prompt_text_area_list_editing import (
    PromptTextAreaListEditingMixin,
)


class PromptTextAreaEditActionsMixin(PromptTextAreaListEditingMixin):
    """Cursor / delete actions that keep the prompt assist surfaces in sync."""

    if TYPE_CHECKING:

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
        def _refresh_file_completion_from_cursor(self) -> None: ...
        def _refresh_xprompt_arg_hint_from_cursor(self) -> None: ...

    def _refresh_completion_after_cursor_move(self) -> None:
        """Refresh prompt assist surfaces after TextArea cursor actions."""
        self._refresh_file_completion_from_cursor()
        self._refresh_xprompt_arg_hint_from_cursor()

    def action_cursor_left(self, select: bool = False) -> None:
        super().action_cursor_left(select)
        self._refresh_completion_after_cursor_move()

    def action_cursor_right(self, select: bool = False) -> None:
        super().action_cursor_right(select)
        self._refresh_completion_after_cursor_move()

    def action_cursor_up(self, select: bool = False) -> None:
        super().action_cursor_up(select)
        self._refresh_completion_after_cursor_move()

    def action_cursor_down(self, select: bool = False) -> None:
        super().action_cursor_down(select)
        self._refresh_completion_after_cursor_move()

    def action_cursor_line_start(self, select: bool = False) -> None:
        super().action_cursor_line_start(select)
        self._refresh_completion_after_cursor_move()

    def action_cursor_line_end(self, select: bool = False) -> None:
        super().action_cursor_line_end(select)
        self._refresh_completion_after_cursor_move()

    def action_cursor_word_left(self, select: bool = False) -> None:
        super().action_cursor_word_left(select)
        self._refresh_completion_after_cursor_move()

    def action_cursor_word_right(self, select: bool = False) -> None:
        super().action_cursor_word_right(select)
        self._refresh_completion_after_cursor_move()

    def action_cursor_page_up(self) -> None:
        super().action_cursor_page_up()
        self._refresh_completion_after_cursor_move()

    def action_cursor_page_down(self) -> None:
        super().action_cursor_page_down()
        self._refresh_completion_after_cursor_move()

    def _refresh_completion_after_text_delete(self) -> None:
        """Refresh prompt assist surfaces after TextArea delete actions."""
        self._refresh_file_completion_from_cursor()
        self._refresh_xprompt_arg_hint_from_cursor()

    def action_delete_left(self) -> None:
        """Delete left, paired-deleting an empty auto-pair, then refresh menus."""
        if self._try_paired_delete(forward=False):
            return
        super().action_delete_left()
        self._refresh_completion_after_text_delete()

    def action_delete_right(self) -> None:
        """Delete right, paired-deleting an empty auto-pair, then refresh menus."""
        if self._try_paired_delete(forward=True):
            return
        super().action_delete_right()
        self._refresh_completion_after_text_delete()

    def _try_paired_delete(self, *, forward: bool) -> bool:
        """Delete both sides of an empty auto-pair when its opener is removed.

        First tries the Jinja-variable planners so deleting a ``{{ ... }}``
        delimiter brace removes its mirror ``}}`` brace and deleting a boundary
        padding space removes the other boundary space (collapsing ``{{  }}`` to
        ``{{}}``). Falling back to the generic planners, backspacing the opener
        of ``(|)``, ``[|]``, ``{|}``, ``'|'`` (and the other supported
        quote/bracket pairs) or forward-deleting it in ``|()`` removes the
        matching closer too. Returns False (so the default single-character
        delete runs) when there is a selection or the cursor is not adjacent to a
        paired delimiter.
        """
        start, end = self.selection
        if start != end:
            return False
        text = self.text
        offset = self._absolute_offset(self.cursor_location)
        plan = (
            plan_jinja_delete_right(text, offset)
            if forward
            else plan_jinja_delete_left(text, offset)
        )
        if plan is None:
            plan = (
                plan_pair_delete_right(text, offset)
                if forward
                else plan_pair_delete_left(text, offset)
            )
        if plan is None:
            return False
        self._replace_via_keyboard(
            plan.text,
            self._location_from_absolute(plan.start),
            self._location_from_absolute(plan.end),
        )
        self.cursor_location = self._location_from_absolute(plan.cursor)
        self._refresh_completion_after_text_delete()
        return True

    def action_delete_word_left(self) -> None:
        """Delete word-left, then refresh any active completion menu."""
        super().action_delete_word_left()
        self._refresh_completion_after_text_delete()

    def action_delete_word_right(self) -> None:
        """Delete word-right, then refresh any active completion menu."""
        super().action_delete_word_right()
        self._refresh_completion_after_text_delete()
