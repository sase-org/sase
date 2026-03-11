"""Trim state management mixin for the file panel."""

from datetime import datetime

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text
from textual.containers import VerticalScroll

from ._messages import FileTrimChanged


class FilePanelTrimMixin:
    """Mixin providing trim state management for AgentFilePanel."""

    def _compute_trim_size(self) -> int:
        """Compute the number of lines to show based on container height.

        Returns:
            The trim size (>= 10), or 0 if the container is hidden /
            not yet laid out and the caller should defer trimming.
        """
        container = self._get_scroll_container()
        if container is None:
            return 0
        # A hidden container has no meaningful height — signal the caller
        # to render full content now and re-trim after layout.
        if container.has_class("hidden"):
            return 0
        try:
            height = container.scrollable_content_region.height
        except Exception:
            return 0
        if height <= 4:
            return 0
        return height - 4

    def _reset_trim_state(self) -> None:
        """Reset all trim-related fields to defaults."""
        self._total_line_count = 0
        self._visible_line_count = 0
        self._base_trim_size = 0
        self._is_trimmed = False
        self._full_content: str | None = None
        self._full_content_lexer: str = "text"
        self._content_mode: str = "none"
        self._static_header_path: str | None = None

    def _count_lines(self, content: str) -> int:
        """Count the number of lines in content.

        Args:
            content: The text content.

        Returns:
            The line count.
        """
        return content.count("\n") + (1 if not content.endswith("\n") else 0)

    def _post_trim_changed(self) -> None:
        """Post a FileTrimChanged message with current trim state."""
        self.post_message(  # type: ignore[attr-defined]
            FileTrimChanged(
                visible_lines=self._visible_line_count,
                total_lines=self._total_line_count,
                is_trimmed=self._is_trimmed,
            )
        )

    def _update_timestamp_header(
        self, fetch_time: datetime, *, refreshing: bool = False
    ) -> None:
        """Update the timestamp line in _full_content without resetting trim state."""
        if self._full_content is None or self._content_mode != "diff":
            return
        newline_idx = self._full_content.index("\n")
        suffix = " (refreshing...)" if refreshing else ""
        new_header = f"# Last fetched: {fetch_time.strftime('%H:%M:%S')}{suffix}"
        self._full_content = new_header + self._full_content[newline_idx:]

    def _apply_deferred_trim(self) -> None:
        """Recompute trim size after layout and apply trimming if needed.

        Called via ``call_after_refresh`` when the initial render could
        not determine the container height (e.g. container was hidden).
        """
        if self._full_content is None or self._is_trimmed:
            return
        trim_size = self._compute_trim_size()
        if trim_size <= 0:
            return  # Still not available
        self._base_trim_size = trim_size
        if self._total_line_count > trim_size:
            self._visible_line_count = trim_size
            self._is_trimmed = True
            self._render_trimmed_content()
            self.call_after_refresh(self._check_trim_overflow)  # type: ignore[attr-defined]

    def _render_trimmed_content(self) -> None:
        """Re-render full_content with current trim state."""
        if self._full_content is None:
            return

        visible = self._visible_line_count
        lexer = (
            "diff"
            if self._content_mode in ("diff", "static_diff")
            else self._full_content_lexer
        )
        syntax = Syntax(
            self._full_content,
            lexer,
            theme="monokai",
            line_numbers=True,
            word_wrap=True,
            line_range=(1, visible),
        )
        remaining = self._total_line_count - visible
        indicator = Text(
            f"\n  \u25be {remaining} more lines below",
            style="dim italic #87D7FF",
        )
        if self._content_mode in ("static", "static_diff"):
            header = Text(
                self._static_header_path or "", style="bold #D7AF5F underline"
            )
            self.update(Group(header, Text(""), syntax, indicator))  # type: ignore[attr-defined]
        else:
            self.update(Group(syntax, indicator))  # type: ignore[attr-defined]

        self._is_trimmed = True
        self._post_trim_changed()

    def _check_trim_overflow(self) -> None:
        """Reduce visible lines if trimmed content overflows the scroll container.

        Word-wrapped lines can cause the rendered content to exceed the
        available viewport height even after trimming.  This detects
        overflow post-layout and reduces the visible line count to
        eliminate the scrollbar.
        """
        if not self._is_trimmed or self._full_content is None:
            return
        container = self._get_scroll_container()
        if container is None:
            return
        try:
            viewport_h = container.scrollable_content_region.height
            content_h = container.virtual_size.height
        except Exception:
            return
        if content_h <= viewport_h:
            return
        overflow = content_h - viewport_h
        new_visible = max(1, self._visible_line_count - overflow)
        if new_visible >= self._visible_line_count:
            return
        self._visible_line_count = new_visible
        self._render_trimmed_content()
        # Re-check in case the reduction wasn't sufficient.
        self.call_after_refresh(self._check_trim_overflow)  # type: ignore[attr-defined]

    @property
    def is_trimmed(self) -> bool:
        """Whether the content is currently trimmed."""
        return self._is_trimmed

    def expand_by_page(self) -> None:
        """Expand visible lines by one page (base_trim_size)."""
        if not self._full_content or not self._is_trimmed:
            return
        if self._base_trim_size <= 0:
            self._base_trim_size = self._compute_trim_size()
            if self._base_trim_size <= 0:
                return
        self._visible_line_count = min(
            self._visible_line_count + self._base_trim_size,
            self._total_line_count,
        )
        if self._visible_line_count >= self._total_line_count:
            self._visible_line_count = self._total_line_count
            self._is_trimmed = False
            self._render_full_content()
        else:
            self._render_trimmed_content()

    def collapse_by_page(self) -> None:
        """Collapse visible lines by one page (base_trim_size)."""
        if not self._full_content:
            return
        if self._base_trim_size <= 0:
            self._base_trim_size = self._compute_trim_size()
            if self._base_trim_size <= 0:
                return
        scroll_pos = self._save_scroll_position()
        self._visible_line_count = max(
            self._visible_line_count - self._base_trim_size,
            self._base_trim_size,
        )
        if self._visible_line_count < self._total_line_count:
            self._is_trimmed = True
            self._render_trimmed_content()
        else:
            self._is_trimmed = False
            self._render_full_content()
        self._restore_scroll_position(scroll_pos)

    def reset_trim(self) -> None:
        """Reset trim to the default page size for current viewport."""
        if not self._full_content:
            return
        self._base_trim_size = self._compute_trim_size()
        if self._base_trim_size <= 0:
            return
        self._visible_line_count = min(self._base_trim_size, self._total_line_count)
        if self._visible_line_count < self._total_line_count:
            self._is_trimmed = True
            self._render_trimmed_content()
            self.call_after_refresh(self._check_trim_overflow)  # type: ignore[attr-defined]
        else:
            self._is_trimmed = False
            self._render_full_content()

    def show_all_lines(self) -> None:
        """Show all lines (remove trimming)."""
        if not self._full_content:
            return
        self._visible_line_count = self._total_line_count
        self._is_trimmed = False
        self._render_full_content()

    def _render_full_content(self) -> None:
        """Re-render full_content without trimming."""
        if self._full_content is None:
            return

        lexer = (
            "diff"
            if self._content_mode in ("diff", "static_diff")
            else self._full_content_lexer
        )
        syntax = Syntax(
            self._full_content,
            lexer,
            theme="monokai",
            line_numbers=True,
            word_wrap=True,
        )
        if self._content_mode in ("static", "static_diff"):
            header = Text(
                self._static_header_path or "", style="bold #D7AF5F underline"
            )
            self.update(Group(header, Text(""), syntax))  # type: ignore[attr-defined]
        else:
            self.update(syntax)  # type: ignore[attr-defined]

        self._post_trim_changed()

    def _get_scroll_container(self) -> VerticalScroll | None:
        """Get the parent scroll container for this file panel.

        Returns:
            The VerticalScroll container, or None if not found.
        """
        try:
            return self.app.query_one("#agent-file-scroll", VerticalScroll)  # type: ignore[attr-defined]
        except Exception:
            return None

    def _save_scroll_position(self) -> float:
        """Save the current scroll position.

        Returns:
            The current scroll Y position, or 0 if unavailable.
        """
        container = self._get_scroll_container()
        if container is not None:
            return container.scroll_y
        return 0.0

    def _restore_scroll_position(self, position: float) -> None:
        """Restore a previously saved scroll position.

        Args:
            position: The scroll Y position to restore.
        """
        container = self._get_scroll_container()
        if container is not None:
            self.call_after_refresh(  # type: ignore[attr-defined]
                lambda: container.scroll_to(y=position, animate=False)
            )
