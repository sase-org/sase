"""Archive list widget: an OptionList of banners, runs, and page tails.

Highlight moves from the app's key actions are programmatic and silent
(``watch_highlighted`` echo guard); only user-initiated highlights (arrow
keys, mouse) post :class:`CursorMoved`. ``Enter`` or a click posts
:class:`ItemActivated`. The widget holds no Archive state of its own.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import tzinfo

from textual.binding import Binding
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import DuplicateID, Option

from ...models.agent_archive_list import ArchiveListItem
from ...util.trace import trace_event
from ._rows import ArchiveRenderContext, format_archive_item, outcome_cell_width

_FALLBACK_WIDTH = 56
_OPTION_PADDING = 2  # ArchiveList > .option-list--option { padding: 0 1; }


class ArchiveList(OptionList, inherit_bindings=False):
    """Selectable Archive list. Banners and tails are nav items, not agents."""

    # Drop OptionList's enter -> select binding so the app-level Enter action
    # (and mouse clicks, which still select) own activation.
    BINDINGS = [
        Binding("down", "cursor_down", "Down", show=False),
        Binding("end", "last", "Last", show=False),
        Binding("home", "first", "First", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("up", "cursor_up", "Up", show=False),
    ]

    class CursorMoved(Message):
        """The user moved the highlight onto ``key``."""

        def __init__(self, key: str) -> None:
            self.key = key
            super().__init__()

    class ItemActivated(Message):
        """The user pressed Enter on, or clicked, ``key``."""

        def __init__(self, key: str) -> None:
            self.key = key
            super().__init__()

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._programmatic_update = False
        self._items: tuple[ArchiveListItem, ...] = ()
        self._keys: list[str] = []
        self._index_by_key: dict[str, int] = {}
        self._tz: tzinfo | None = None
        self._grouping = "day"
        self._rendered_width = 0
        self._pending_cursor_key: str | None = None
        self._restored_keys: frozenset[str] = frozenset()
        self._marked_keys: frozenset[str] = frozenset()

    @property
    def item_keys(self) -> tuple[str, ...]:
        """Item keys in rendered order (introspection for tests and chrome)."""
        return tuple(self._keys)

    def _content_width(self) -> int:
        """Cells available to one row's text.

        ``scrollable_content_region`` already excludes border, padding, and
        the scrollbar gutter; each option then pads one cell on both sides.
        """
        width = self.scrollable_content_region.width - _OPTION_PADDING
        return width if width > 0 else _FALLBACK_WIDTH

    def _laid_out_content_width(self) -> int:
        """Return the row width only after the list has real layout space."""
        return self.scrollable_content_region.width - _OPTION_PADDING

    def _render_options(self) -> list[Option]:
        width = self._content_width()
        self._rendered_width = width
        ctx = ArchiveRenderContext(
            tz=self._tz,
            grouping=self._grouping,
            width=width,
            outcome_width=outcome_cell_width(self._items),
            restored_keys=self._restored_keys,
            marked_keys=self._marked_keys,
        )
        options: list[Option] = []
        for item in self._items:
            text = format_archive_item(item, ctx)
            text.no_wrap = True
            options.append(Option(text, id=item.key, disabled=not item.selectable))
        return options

    def apply_items(
        self,
        items: Sequence[ArchiveListItem],
        cursor_key: str | None,
        *,
        tz: tzinfo | None,
        grouping: str,
        restored_keys: Collection[str] = (),
        marked_keys: Collection[str] = (),
    ) -> None:
        """Swap in ``items`` keeping scroll, then silently park on ``cursor_key``."""
        self._items = tuple(items)
        self._keys = [item.key for item in self._items]
        self._index_by_key = {key: index for index, key in enumerate(self._keys)}
        self._tz = tz
        self._grouping = grouping
        self._restored_keys = frozenset(restored_keys)
        self._marked_keys = frozenset(marked_keys)
        self._pending_cursor_key = cursor_key
        if self._laid_out_content_width() <= 0:
            return
        self._install_options(self._render_options())
        self.set_cursor(cursor_key)

    def _install_options(self, options: list[Option]) -> None:
        """Replace every option in one step, preserving highlight and scroll.

        ``set_options`` resets both, and Textual has no insert; mirrors the
        bookkeeping ``add_options`` does (as ``AgentList.install_options``).
        """
        ids = [option.id for option in options if option.id is not None]
        if len(ids) != len(set(ids)):
            raise DuplicateID("Options contain duplicated IDs")
        self._programmatic_update = True
        try:
            self._options[:] = options
            self._option_to_index = {option: idx for idx, option in enumerate(options)}
            self._id_to_option = {
                option.id: option for option in options if option.id is not None
            }
            self._mouse_hovering_over = None
            self._clear_caches()
            if self.is_mounted:
                self.refresh(layout=self.styles.auto_dimensions)
                self._update_lines()
        finally:
            self._programmatic_update = False

    def set_cursor(self, key: str | None) -> None:
        """Highlight ``key`` silently, keeping its row visible."""
        self._pending_cursor_key = key
        index = self._index_by_key.get(key) if key is not None else None
        self._programmatic_update = True
        try:
            if index is None:
                self.highlighted = None
            else:
                self.highlighted = index
                self.scroll_to_highlight()
        finally:
            self._programmatic_update = False

    def reveal_cursor(self) -> None:
        """Scroll the cursor row into view once the next layout pass has run.

        Called when the hidden column is shown: rows applied while hidden had
        no size to scroll against, and Textual sends no ``Resize`` for the
        children of a container that only toggled ``display``.
        """

        def reveal() -> None:
            if (
                self._items
                and self._laid_out_content_width() > 0
                and self._content_width() != self._rendered_width
            ):
                self._install_options(self._render_options())
                self.set_cursor(self._pending_cursor_key)
            if self.highlighted is not None:
                self.scroll_to_highlight()

        self.call_after_refresh(reveal)

    def watch_highlighted(self, highlighted: int | None) -> None:
        """Swallow ``OptionHighlighted`` echoes of programmatic highlights.

        The parent watcher posts the message from inside this synchronous
        call, so the guard flag is still set when it must be; a flag checked
        in the handler would already be cleared when the queued echo lands.
        """
        if self._programmatic_update:
            trace_event("widget.archive_list.watch_highlighted.suppressed")
            return
        super().watch_highlighted(highlighted)

    def on_resize(self) -> None:
        """Re-fit rows to the new width and keep the cursor row visible.

        Rows built while the column was hidden or unsized used a fallback
        width and could not scroll to the cursor; the first real layout fixes
        both (drop MODEL/RUNTIME, re-truncate names, scroll to highlight).
        """
        if (
            self._items
            and self._laid_out_content_width() > 0
            and self._content_width() != self._rendered_width
        ):
            self._install_options(self._render_options())
            self.set_cursor(self._pending_cursor_key)
        if self.highlighted is not None:
            self.scroll_to_highlight()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        event.stop()
        index = event.option_index
        if index is None or self._programmatic_update:
            return
        if 0 <= index < len(self._keys):
            self.post_message(self.CursorMoved(self._keys[index]))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        index = event.option_index
        if index is not None and 0 <= index < len(self._keys):
            self.post_message(self.ItemActivated(self._keys[index]))


__all__ = ["ArchiveList"]
