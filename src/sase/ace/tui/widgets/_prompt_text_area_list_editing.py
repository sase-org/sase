"""PromptTextArea prompt-list editing hooks.

The ``o`` / ``O`` / ``J`` host hooks :class:`VimTextArea` leaves as no-ops, the
replay normalizations that keep a dot-repeat from re-typing a marker the
destination already supplies, and the ``<ctrl+j>`` newline action -- everything
that makes prompt hyphen bullets and ordered lists restructure themselves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.widgets._prompt_bullet_editing import (
    is_prompt_bullet_content_column,
    is_prompt_bullet_marker_only,
    normalize_prompt_bullet_replay_text,
    prompt_bullet_row_has_bullet_above,
    prompt_bullet_sibling_prefix,
    strip_prompt_bullet_marker,
)
from sase.ace.tui.widgets._prompt_list_markers import (
    ListMarker,
    MarkerFamily,
    find_list_marker,
)
from sase.ace.tui.widgets._prompt_ordered_editing import (
    find_ordered_predecessor,
    normalize_prompt_ordered_replay_text,
    plan_ordered_insert_newline,
    plan_ordered_list_edit,
    plan_ordered_open_line,
    strip_prompt_ordered_marker,
)
from sase.ace.tui.widgets._prompt_text_area_bar import PromptTextAreaBarMixin

if TYPE_CHECKING:
    from sase.ace.tui.widgets._paired_text_editing import TextEdit


class PromptTextAreaListEditingMixin(PromptTextAreaBarMixin):
    """Hyphen bullet and ordered list continuation for the prompt pane."""

    if TYPE_CHECKING:

        def _apply_planned_text_edit(
            self,
            plan: TextEdit,
            *,
            remap_dot_capture: bool = False,
        ) -> None: ...
        def _replace_via_keyboard(
            self,
            insert: str,
            start: tuple[int, int],
            end: tuple[int, int],
        ) -> None: ...

    def _normal_open_below_insert_text(self, row: int) -> str:
        """Auto-continue a containing prompt hyphen bullet for ``o``."""
        prefix = prompt_bullet_sibling_prefix(self.document.lines, row)
        return f"\n{prefix}" if prefix is not None else "\n"

    def _normal_open_above_insert_text(self, row: int) -> str:
        """Auto-continue a containing prompt hyphen bullet for ``O``."""
        prefix = prompt_bullet_sibling_prefix(self.document.lines, row)
        return f"{prefix}\n" if prefix is not None else "\n"

    def _normal_open_line_plan(self, row: int, *, above: bool) -> TextEdit | None:
        """Open a correctly numbered ordered sibling for ``o`` / ``O``.

        Overrides :class:`VimTextArea`'s no-op hook. The planner renumbers the
        run the new item joins and returns the whole press as one edit; it
        declines whenever no ordered item owns *row*, leaving the hyphen bullet
        string hooks below to run exactly as before.
        """
        return plan_ordered_open_line(self.document.lines, row, above=above)

    def _normal_join_next_line_text(self, next_line: str) -> str:
        """Drop a pulled-up prompt list marker (hyphen or ordered) for ``J``."""
        return strip_prompt_ordered_marker(strip_prompt_bullet_marker(next_line))

    def _normal_join_marker_dropped(
        self,
        row: int,
        next_line: str,
        folded_next: str,
    ) -> ListMarker | None:
        """Return the ordered marker NORMAL-mode ``J`` just folded away.

        *row* is the join's fixed anchor row, so the dropped marker always sat
        one row below it -- exactly where :func:`find_ordered_predecessor`
        expects to start its search once the fold is complete.
        """
        return find_list_marker(next_line, MarkerFamily.ORDERED, row=row + 1)

    def _normal_join_renumber_plan(
        self,
        row: int,
        join_col: int,
        joined: str,
        dropped_marker: ListMarker | None,
    ) -> TextEdit | None:
        """Renumber the run a dropped ordered marker left behind for ``J``.

        Overrides :class:`VimTextArea`'s no-op hook. *joined* is the fold's
        already marker-stripped result for *row*; folding it into the still-live
        document's remaining lines reproduces the document exactly as the join
        will leave it, so the run can be renumbered against that final text in
        the same edit the fold itself produces. Declines when there is no
        *dropped_marker*, or it has no preceding sibling to anchor renumbering
        on, leaving the plain per-line join in charge.
        """
        if dropped_marker is None:
            return None
        lines = self.document.lines
        new_lines = [*lines[:row], joined, *lines[row + 2 :]]
        anchor = find_ordered_predecessor(new_lines, dropped_marker)
        if anchor is None:
            return None
        return plan_ordered_list_edit(
            self.text,
            new_lines,
            anchor_rows=(anchor.row,),
            cursor_row=row,
            cursor_col=join_col,
        )

    def _normalize_normal_open_replay_text(self, insert_text: str) -> str:
        """Drop a replayed marker the destination's list structure supplies.

        Both families are checked: only the one matching the structural line
        the replay just landed on can strip anything, so the two normalizations
        compose without interfering.
        """
        line = self.document.get_line(self.cursor_location[0])
        return normalize_prompt_bullet_replay_text(
            line,
            normalize_prompt_ordered_replay_text(line, insert_text),
        )

    def _normalize_normal_open_below_replay_text(self, insert_text: str) -> str:
        """Avoid replaying a typed marker after structural prompt list text."""
        return self._normalize_normal_open_replay_text(insert_text)

    def _normalize_normal_open_above_replay_text(self, insert_text: str) -> str:
        """Avoid replaying a typed marker after structural prompt list text."""
        return self._normalize_normal_open_replay_text(insert_text)

    def action_insert_newline(self) -> None:
        """Insert a newline, continuing or exiting a prompt list item.

        Ordered items go first, through the planner that renumbers the run the
        press restructured and reaches the document as one edit (one undo
        checkpoint). The planner declines whenever no ordered item is involved,
        leaving the hyphen bullet branches below to run exactly as before.
        """
        row = self.cursor_location[0]
        start, end = self.selection
        ordered_plan = plan_ordered_insert_newline(self.document.lines, start, end)
        if ordered_plan is not None:
            self._apply_planned_text_edit(ordered_plan)
            return

        line = self.document.get_line(row)
        if start == end and is_prompt_bullet_marker_only(line):
            if prompt_bullet_row_has_bullet_above(self.document.lines, row):
                self._replace_via_keyboard("\n", (row, 0), (row, len(line)))
            else:
                # A lone marker grows one sibling first; the exit lands on the
                # next press, once that sibling has a bullet above it. Anchor
                # at the line end so a cursor inside the marker cannot produce
                # ``\n- - ``.
                line_end = (row, len(line))
                self._replace_via_keyboard(f"\n{line}", line_end, line_end)
            return

        if (
            start == end
            and is_prompt_bullet_content_column(line, start[1])
            and prompt_bullet_row_has_bullet_above(self.document.lines, row)
        ):
            self._replace_via_keyboard("\n", (row, 0), start)
            return

        prefix = prompt_bullet_sibling_prefix(self.document.lines, row)
        insert = f"\n{prefix}" if prefix is not None else "\n"
        self._replace_via_keyboard(insert, start, end)
