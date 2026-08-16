"""Content state and rendering helpers for the file panel."""

from datetime import datetime

from rich.console import Group, RenderableType
from rich.text import Text
from textual.containers import VerticalScroll

from sase.linked_repos import OpenedRepoKind

from ...util.lazy_syntax import (
    FILE_PANEL_MAX_RENDER_LINES,
    LazySyntaxRenderCache,
    lazy_renderable,
)
from ._messages import FileLineCountChanged
from ._scroll_anchor import (
    AnchorStore,
    capture_anchor,
    content_digest,
    resolve_anchor,
)

# Content modes rendered through ``_render_full_content`` with
# ``line_numbers=True``; the scroll anchor only walks up to a source-line
# start when the rendered body actually carries a numbered gutter.
_GUTTER_CONTENT_MODES = frozenset({"diff", "static", "static_diff", "linked_diff"})

# How far _capture_scroll_anchor/_apply_scroll_anchor look for row text,
# bounded so anchor search never scales with document size.
_ANCHOR_SEARCH_WINDOW = 512


class FilePanelContentMixin:
    """Mixin providing full-content rendering and scroll-anchor preservation."""

    _content_render_cache: LazySyntaxRenderCache
    _linked_repo_kind: OpenedRepoKind
    _scroll_anchors: AnchorStore
    _anchor_slot_key: tuple[object, str] | None
    _anchor_agent_identity: object | None
    _last_applied_scroll_row: int | None
    _anchor_restore_pending: bool
    _rendered_content_digest: str | None
    _rendered_gutter_present: bool

    def _reset_content_state(self) -> None:
        """Reset state associated with the currently displayed content."""
        self._total_line_count = 0
        self._visible_line_count = 0
        self._is_content_capped = False
        self._full_content: str | None = None
        self._full_content_lexer: str = "text"
        self._content_mode: str = "none"
        self._content_fetched_at: datetime | None = None
        self._static_header_path: str | None = None
        self._linked_repo_name: str | None = None
        self._linked_repo_kind = "linked"
        self._linked_workspace_dir: str | None = None
        self._linked_fetched_at: datetime | None = None

    def _count_lines(self, content: str) -> int:
        """Return the logical line count for *content*."""
        return content.count("\n") + (1 if not content.endswith("\n") else 0)

    def _post_line_count_changed(self) -> None:
        """Post the current rendered and total line counts."""
        self.post_message(  # type: ignore[attr-defined]
            FileLineCountChanged(
                visible_lines=self._visible_line_count,
                total_lines=self._total_line_count,
                capped=self._is_content_capped,
            )
        )

    def _timestamp_header(self, *, refreshing: bool = False) -> Text:
        """Build the small live-diff timestamp header."""
        fetched_at = self._content_fetched_at
        header = Text("# Last fetched: ", style="dim")
        if fetched_at is not None:
            header.append(fetched_at.strftime("%H:%M:%S"), style="#87D7FF")
        if refreshing:
            header.append(" (refreshing...)", style="dim italic")
        return header

    def _render_full_content(self, *, refreshing: bool = False) -> None:
        """Render the complete body, subject only to the pathological-size cap."""
        if self._full_content is None:
            return

        lexer = (
            "diff"
            if self._content_mode in ("diff", "static_diff", "linked_diff")
            else self._full_content_lexer
        )
        self._total_line_count = self._count_lines(self._full_content)
        self._visible_line_count = min(
            self._total_line_count,
            FILE_PANEL_MAX_RENDER_LINES,
        )
        self._is_content_capped = self._total_line_count > self._visible_line_count
        body = lazy_renderable(
            self._full_content,
            lexer,
            line_numbers=True,
            render_cache=self._content_render_cache,
            max_render_lines=FILE_PANEL_MAX_RENDER_LINES,
            truncation_hint="press E to open in editor",
        )

        if self._content_mode == "diff":
            self._update_body(
                Group(self._timestamp_header(refreshing=refreshing), Text(""), body)
            )
        elif self._content_mode in ("static", "static_diff"):
            header = Text(
                self._static_header_path or "",
                style="bold #D7AF5F underline",
            )
            self._update_body(Group(header, Text(""), body))
        elif self._content_mode == "linked_diff":
            banner = self._build_linked_banner()  # type: ignore[attr-defined]
            self._update_body(Group(banner, Text(""), body))
        else:
            self._update_body(body)

        self._post_line_count_changed()

    def _get_scroll_container(self) -> VerticalScroll | None:
        """Return the file panel's parent scroll container, when mounted."""
        try:
            return self.app.query_one("#agent-file-scroll", VerticalScroll)  # type: ignore[attr-defined]
        except Exception:
            return None

    def _update_body(self, renderable: RenderableType, *, anchor: bool = True) -> None:
        """Route a body render through scroll-anchor capture and restore.

        Every ``self.update(...)`` call in the file panel goes through here so
        async static reads (whose actual render lands well after the call
        that scheduled them) are covered automatically, and so a transient
        placeholder body never permanently destroys the reader's position.
        """
        if anchor:
            self._capture_scroll_anchor()
        self.update(renderable)  # type: ignore[attr-defined]
        self._rendered_content_digest = content_digest(self._full_content)
        self._rendered_gutter_present = self._content_mode in _GUTTER_CONTENT_MODES
        if anchor:
            self._schedule_scroll_anchor_restore()

    def _capture_scroll_anchor(self) -> None:
        """Capture the reader's position into the current page's anchor.

        Only recaptures when the container's live ``scroll_y`` differs from
        the value our own last restore applied — i.e. the reader actually
        scrolled. When they match (including the very first render of a
        page, where ``_last_applied_scroll_row`` is still None), the stored
        anchor is left untouched: a Textual clamp from a transient short
        body must not overwrite the anchor that survives it.
        """
        if self._anchor_slot_key is None or self._last_applied_scroll_row is None:
            return
        container = self._get_scroll_container()
        if container is None:
            return
        observed = int(container.scroll_y)
        if observed == self._last_applied_scroll_row:
            return
        self._store_current_anchor(observed)

    def _store_current_anchor(self, row: int) -> None:
        """Build and store a ScrollAnchor for *row* under the current key."""
        key = self._anchor_slot_key
        if key is None:
            return
        row_texts, window_start = self._anchor_row_texts_window(row)
        anchor = capture_anchor(
            row,
            row_texts,
            window_start,
            gutter_present=self._rendered_gutter_present,
            content_digest=self._rendered_content_digest,
        )
        self._scroll_anchors.set(key, anchor)

    def _schedule_scroll_anchor_restore(self) -> None:
        """Schedule a post-layout restore, coalescing back-to-back renders."""
        if self._anchor_restore_pending:
            return
        self._anchor_restore_pending = True
        self.call_after_refresh(self._apply_scroll_anchor)  # type: ignore[attr-defined]

    def _apply_scroll_anchor(self) -> None:
        """Resolve and apply the current page's anchor after layout settles."""
        self._anchor_restore_pending = False
        container = self._get_scroll_container()
        if container is None:
            return
        key = self._anchor_slot_key
        anchor = self._scroll_anchors.get(key) if key is not None else None
        if anchor is None:
            target_row = 0
        else:
            row_texts, window_start = self._anchor_row_texts_window(anchor.row)
            target_row = resolve_anchor(
                anchor,
                row_texts,
                window_start,
                gutter_present=self._rendered_gutter_present,
                content_digest=self._rendered_content_digest,
                search_window=_ANCHOR_SEARCH_WINDOW,
            )
        container.scroll_to(y=target_row, animate=False, immediate=True)
        self._last_applied_scroll_row = int(container.scroll_y)

    def _anchor_row_texts_window(
        self, center: int, *, radius: int = _ANCHOR_SEARCH_WINDOW
    ) -> tuple[list[str], int]:
        """Return rendered row texts and the absolute row they start at."""
        height = int(self.size.height)  # type: ignore[attr-defined]
        if height <= 0:
            return [], max(0, center)
        lo = max(0, center - radius)
        hi = min(height, center + radius + 1)
        if hi <= lo:
            return [], lo
        return [self.render_line(y).text for y in range(lo, hi)], lo  # type: ignore[attr-defined]

    def _current_anchor_key(self) -> tuple[object, str] | None:
        """Return the anchor-store key for the currently selected page."""
        slot = self._current_file_value()  # type: ignore[attr-defined]
        if slot is None:
            return None
        return (self._anchor_agent_identity, slot)

    def _note_slot_change(self, new_key: tuple[object, str] | None) -> None:
        """Capture the outgoing page's position, then switch to *new_key*.

        Resets ``_last_applied_scroll_row`` so the next restore treats this
        as a fresh page: a page never opened before starts at the top, and a
        page read before returns to its remembered anchor.
        """
        if self._anchor_slot_key == new_key:
            return
        if self._anchor_slot_key is not None:
            container = self._get_scroll_container()
            if container is not None:
                self._store_current_anchor(int(container.scroll_y))
        self._anchor_slot_key = new_key
        self._last_applied_scroll_row = None


def new_file_panel_render_cache() -> LazySyntaxRenderCache:
    """Return the small per-panel body cache used by file panels."""
    return LazySyntaxRenderCache(max_entries=2)
