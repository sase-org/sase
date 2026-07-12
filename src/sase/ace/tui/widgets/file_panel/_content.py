"""Content state and rendering helpers for the file panel."""

from datetime import datetime

from rich.console import Group
from rich.text import Text
from textual.containers import VerticalScroll

from ...util.lazy_syntax import (
    FILE_PANEL_MAX_RENDER_LINES,
    LazySyntaxRenderCache,
    lazy_renderable,
)
from ._messages import FileLineCountChanged


class FilePanelContentMixin:
    """Mixin providing full-content rendering and scroll preservation."""

    _content_render_cache: LazySyntaxRenderCache

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
        )

        if self._content_mode == "diff":
            self.update(  # type: ignore[attr-defined]
                Group(self._timestamp_header(refreshing=refreshing), Text(""), body)
            )
        elif self._content_mode in ("static", "static_diff"):
            header = Text(
                self._static_header_path or "",
                style="bold #D7AF5F underline",
            )
            self.update(Group(header, Text(""), body))  # type: ignore[attr-defined]
        elif self._content_mode == "linked_diff":
            banner = self._build_linked_banner()  # type: ignore[attr-defined]
            self.update(Group(banner, Text(""), body))  # type: ignore[attr-defined]
        else:
            self.update(body)  # type: ignore[attr-defined]

        self._post_line_count_changed()

    def _get_scroll_container(self) -> VerticalScroll | None:
        """Return the file panel's parent scroll container, when mounted."""
        try:
            return self.app.query_one("#agent-file-scroll", VerticalScroll)  # type: ignore[attr-defined]
        except Exception:
            return None

    def _save_scroll_position(self) -> float:
        """Return the current vertical scroll position."""
        container = self._get_scroll_container()
        return container.scroll_y if container is not None else 0.0

    def _restore_scroll_position(self, position: float) -> None:
        """Restore a previously saved vertical scroll position after layout."""
        container = self._get_scroll_container()
        if container is not None:
            self.call_after_refresh(  # type: ignore[attr-defined]
                lambda: container.scroll_to(y=position, animate=False)
            )


def new_file_panel_render_cache() -> LazySyntaxRenderCache:
    """Return the small per-panel body cache used by file panels."""
    return LazySyntaxRenderCache(max_entries=2)
