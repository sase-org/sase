"""Option-list windowing and cursor movement for the Node Finder modal.

Moves the ``[base, end)`` materialization window out of
:class:`~sase.ace.tui.modals.node_finder_modal.NodeFinderModal` without
changing its behavior: broad results still keep every row in the view
while only the window around the highlight becomes widgets.
"""

from __future__ import annotations

from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ..models.node_finder import NodeFinderView, next_jumpable_index
from .node_finder_rendering import (
    empty_match_label,
    hint_column_width,
    last_child_indices,
    render_row_prompt,
    show_status_column,
)

#: Maximum rows materialized in the ``OptionList``. Broad results keep
#: every row in the view (hints, cursor, and jump targets span the whole
#: list) while only this window around the highlight becomes widgets, so
#: a 2,000-row rebuild stays inside the refilter budget. Cursor motion
#: re-centers the window when it steps outside.
_OPTION_WINDOW_SIZE = 64


class NodeFinderOptionsMixin:
    """Windowed option rebuild and cursor motion for the Node Finder."""

    _view: NodeFinderView
    _search_mode: bool
    _pending: str
    _layout_class: str
    _window_base: int
    _window_end: int
    _highlighting: bool
    _last_options_key: tuple[object, ...] | None

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "node-finder-list":
            return
        if event.option_index is None:
            self._set_flash("No matching node")  # type: ignore[attr-defined]
            return
        self._jump_index(  # type: ignore[attr-defined]
            event.option_index + self._window_base
        )

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if self._highlighting or event.option_list.id != "node-finder-list":
            return
        self._paint_preview()  # type: ignore[attr-defined]

    def _highlighted_view_index(self) -> int | None:
        """Return the highlighted view row, translating the option offset."""
        highlighted = self._list().highlighted  # type: ignore[attr-defined]
        if highlighted is None:
            return None
        return self._window_base + highlighted

    def _move_cursor(self, direction: int) -> None:
        if not self._view.rows:
            return
        current = self._highlighted_view_index()
        if current is None or not (0 <= current < len(self._view.rows)):
            current = self._view.best_index if self._view.best_index is not None else 0
        nxt = next_jumpable_index(self._view, current, direction)
        self._set_highlighted(nxt)
        self._paint_preview()  # type: ignore[attr-defined]

    def _window_for(self, highlight: int | None) -> tuple[int, int]:
        """Return the ``[base, end)`` view range materialized as options.

        The window centers on the highlight when the view overflows it;
        small views materialize whole. Every view row stays reachable:
        hints span the full view and cursor motion re-centers the window.
        """
        total = len(self._view.rows)
        if total <= _OPTION_WINDOW_SIZE:
            return (0, total)
        target = highlight
        if target is None or not (0 <= target < total):
            target = self._view.best_index if self._view.best_index is not None else 0
        start = min(
            max(0, target - _OPTION_WINDOW_SIZE // 2), total - _OPTION_WINDOW_SIZE
        )
        return (start, start + _OPTION_WINDOW_SIZE)

    def _rebuild_options(self, *, highlight: int | None) -> None:
        view = self._view
        resolved: int | None
        if highlight is not None and 0 <= highlight < len(view.rows):
            resolved = highlight
        else:
            resolved = view.best_index
        if view.rows:
            base, end = self._window_for(resolved)
        else:
            base, end = 0, 0
        # Skip when the list already shows exactly what this rebuild would
        # produce: the same view object with the same render parameters,
        # window, and highlight. Repeated refilters of one query memoize to
        # the same view, so the clear/add churn and the window's row renders
        # are skipped without changing any pixel. The live highlight check
        # matters: cursor motion sets it directly without rebuilding, so a
        # refilter that resolves elsewhere must still rebuild to reset it.
        # ``resolved`` always lands inside ``(base, end)`` by construction,
        # so the ``_set_highlighted`` below never re-centers (and never
        # re-enters this method) from here.
        key: tuple[object, ...] = (
            id(view),
            self._search_mode,
            self._pending,
            self._layout_class,
            base,
            end,
            resolved,
        )
        if (
            key == self._last_options_key
            and self._window_base == base
            and self._window_end == end
            and (resolved is None or self._highlighted_view_index() == resolved)
        ):
            return
        option_list = self._list()  # type: ignore[attr-defined]
        hint_width = hint_column_width(view)
        status = show_status_column(self._layout_class)
        # One sibling-closure pass shared by every row's tree guides; computing
        # it per row would make a rebuild O(rows^2). Guides span the full
        # view even though only the window becomes widgets.
        guide_ends = last_child_indices(view.rows)
        options: list[Option] = []
        if not view.rows:
            options.append(
                Option(
                    empty_match_label(view.query),
                    id="__empty__",
                    disabled=True,
                )
            )
            self._window_base = 0
            self._window_end = 0
        else:
            self._window_base = base
            self._window_end = end
            for index in range(base, end):
                row = view.rows[index]
                disabled = (
                    not row.jumpable or index in view.context or row.identity is None
                )
                options.append(
                    Option(
                        render_row_prompt(
                            view,
                            index,
                            search_mode=self._search_mode,
                            pending=self._pending,
                            show_status=status,
                            hint_width=hint_width,
                            last_child=guide_ends,
                        ),
                        id=f"nf-{index}",
                        disabled=disabled,
                    )
                )
        # A fresh list holds no options, so clearing it would only post
        # another refresh cycle for no visible change.
        if option_list.option_count:
            option_list.clear_options()
        option_list.add_options(options)
        if resolved is not None and self._window_base <= resolved < self._window_end:
            self._set_highlighted(resolved)
        self._last_options_key = key

    def _refresh_hint_gutters(self) -> None:
        if not self.is_mounted:  # type: ignore[attr-defined]
            return
        self._rebuild_options(highlight=self._highlighted_view_index())

    def _set_highlighted(self, index: int) -> None:
        if not (self._window_base <= index < self._window_end):
            # Outside the materialized window: re-center first so every
            # cursor step stays reachable.
            self._rebuild_options(highlight=index)
            return
        option_list = self._list()  # type: ignore[attr-defined]
        self._highlighting = True
        try:
            option_list.highlighted = index - self._window_base
        finally:
            self._highlighting = False


__all__ = ["NodeFinderOptionsMixin"]
