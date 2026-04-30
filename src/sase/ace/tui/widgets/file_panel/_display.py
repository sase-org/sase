"""Static file and diff display mixin for the file panel."""

import os
from datetime import datetime

from rich.console import Group
from rich.text import Text

from sase.ace.tui.graphics import (
    GraphicsCapability,
    KittyImageRenderable,
    TerminalControlRenderable,
    image_preview,
    image_preview_size_for_viewport,
    is_supported_image_path,
)

from ...util.lazy_syntax import lazy_renderable
from ._messages import _EXTENSION_TO_LEXER


class FilePanelDisplayMixin:
    """Mixin providing static file/diff display for AgentFilePanel."""

    _full_content: str | None
    _static_header_path: str | None
    _current_image_renderable: KittyImageRenderable | None

    def _display_file_with_timestamp(
        self,
        diff_output: str | None,
        fetch_time: datetime,
        *,
        post_visibility_message: bool = True,
        is_stale: bool = False,
    ) -> None:
        """Display file output with fetch timestamp.

        Args:
            diff_output: The diff output or None if no changes.
            fetch_time: When the file was fetched.
            post_visibility_message: Whether to post visibility change message.
                Set to False when displaying cached data to avoid flicker.
            is_stale: Whether the content is stale (showing while refreshing).
        """
        # Track last displayed content for change detection
        self._last_file_content = diff_output

        # Post visibility message to parent (only for fresh fetches to avoid flicker)
        if post_visibility_message:
            self._post_file_visibility(has_file=diff_output is not None)  # type: ignore[attr-defined]
        cleanup = self._consume_image_cleanup_segments()

        # Build refresh indicator if stale and background refreshing
        refresh_indicator = ""
        if is_stale and self._is_background_refreshing:  # type: ignore[attr-defined]
            refresh_indicator = " (refreshing...)"

        if diff_output:
            # For simplicity, prepend timestamp to the diff output
            diff_with_header = (
                f"# Last fetched: {fetch_time.strftime('%H:%M:%S')}"
                f"{refresh_indicator}\n\n{diff_output}"
            )

            # Store content for future re-render
            self._full_content = diff_with_header
            self._full_content_lexer = "diff"
            self._content_mode = "diff"

            # Compute trimming
            total = self._count_lines(diff_with_header)  # type: ignore[attr-defined]
            trim_size = self._compute_trim_size()  # type: ignore[attr-defined]
            self._total_line_count = total
            self._base_trim_size = trim_size

            if trim_size > 0 and total > trim_size:
                self._visible_line_count = trim_size
                self._is_trimmed = True
                syntax = lazy_renderable(
                    diff_with_header,
                    "diff",
                    line_numbers=True,
                    line_range=(1, trim_size),
                )
                remaining = total - trim_size
                indicator = Text(
                    f"\n  \u25be {remaining} more lines below",
                    style="dim italic #87D7FF",
                )
                group = (
                    Group(*cleanup, syntax, indicator)
                    if cleanup
                    else Group(syntax, indicator)
                )
                self.update(group)  # type: ignore[attr-defined]
                # Word-wrapped lines may overflow — schedule post-layout fix
                self.call_after_refresh(self._check_trim_overflow)  # type: ignore[attr-defined]
            else:
                self._visible_line_count = total
                self._is_trimmed = False
                syntax = lazy_renderable(
                    diff_with_header,
                    "diff",
                    line_numbers=True,
                )
                self.update(Group(*cleanup, syntax) if cleanup else syntax)  # type: ignore[attr-defined]
                # Container was hidden/not laid out — trim after layout
                if trim_size == 0:
                    self.call_after_refresh(self._apply_deferred_trim)  # type: ignore[attr-defined]

            self._post_trim_changed()  # type: ignore[attr-defined]
        else:
            text = Text()
            text.append("Last fetched: ", style="dim")
            text.append(fetch_time.strftime("%H:%M:%S"), style="#87D7FF")
            if refresh_indicator:
                text.append(refresh_indicator, style="dim italic")
            text.append("\n\n")
            text.append("No changes detected.\n", style="dim italic")
            self.update(Group(*cleanup, text) if cleanup else text)  # type: ignore[attr-defined]
            self._post_trim_changed()  # type: ignore[attr-defined]

        self._has_displayed_content = True

    def display_static_diff(self, diff_path: str) -> None:
        """Display a static diff from a file (no auto-refresh).

        Args:
            diff_path: Path to the diff file (may use ~ for home).
        """
        expanded_path = os.path.expanduser(diff_path)
        cleanup = self._consume_image_cleanup_segments()
        try:
            with open(expanded_path, encoding="utf-8") as f:
                diff_content = f.read()
        except Exception:
            text = Text("Could not read diff file.\n", style="dim italic")
            self.update(Group(*cleanup, text) if cleanup else text)  # type: ignore[attr-defined]
            self._post_file_visibility(has_file=False)  # type: ignore[attr-defined]
            return

        if not diff_content.strip():
            text = Text("Diff file is empty.\n", style="dim italic")
            self.update(Group(*cleanup, text) if cleanup else text)  # type: ignore[attr-defined]
            self._post_file_visibility(has_file=False)  # type: ignore[attr-defined]
            return

        # Display diff with file path header
        diff_with_header = f"# Static diff (from saved file)\n\n{diff_content}"

        # Store content for future re-render
        self._full_content = diff_with_header
        self._full_content_lexer = "diff"
        self._content_mode = "static_diff"
        self._static_header_path = expanded_path

        # Compute trimming
        total = self._count_lines(diff_with_header)  # type: ignore[attr-defined]
        trim_size = self._compute_trim_size()  # type: ignore[attr-defined]
        self._total_line_count = total
        self._base_trim_size = trim_size

        header = Text(expanded_path, style="bold #D7AF5F underline")

        if trim_size > 0 and total > trim_size:
            self._visible_line_count = trim_size
            self._is_trimmed = True
            syntax = lazy_renderable(
                diff_with_header,
                "diff",
                line_numbers=True,
                line_range=(1, trim_size),
            )
            remaining = total - trim_size
            indicator = Text(
                f"\n  \u25be {remaining} more lines below",
                style="dim italic #87D7FF",
            )
            self.update(Group(*cleanup, header, Text(""), syntax, indicator))  # type: ignore[attr-defined]
            # Word-wrapped lines may overflow — schedule post-layout fix
            self.call_after_refresh(self._check_trim_overflow)  # type: ignore[attr-defined]
        else:
            self._visible_line_count = total
            self._is_trimmed = False
            syntax = lazy_renderable(
                diff_with_header,
                "diff",
                line_numbers=True,
            )
            self.update(Group(*cleanup, header, Text(""), syntax))  # type: ignore[attr-defined]
            # Container was hidden/not laid out — trim after layout
            if trim_size == 0:
                self.call_after_refresh(self._apply_deferred_trim)  # type: ignore[attr-defined]

        self._has_displayed_content = True
        self._post_file_visibility(has_file=True)  # type: ignore[attr-defined]
        self._post_trim_changed()  # type: ignore[attr-defined]

    def display_static_file(self, file_path: str) -> None:
        """Display a static file with syntax highlighting (no auto-refresh).

        Auto-detects the lexer from the file extension.

        Args:
            file_path: Path to the file (may use ~ for home).
        """
        expanded_path = os.path.expanduser(file_path)
        if is_supported_image_path(expanded_path):
            self._display_static_image(expanded_path)
            return

        cleanup = self._consume_image_cleanup_segments()
        try:
            with open(expanded_path, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            text = Text("Could not read file.\n", style="dim italic")
            self.update(Group(*cleanup, text) if cleanup else text)  # type: ignore[attr-defined]
            self._post_file_visibility(has_file=False)  # type: ignore[attr-defined]
            return

        if not content.strip():
            text = Text("File is empty.\n", style="dim italic")
            self.update(Group(*cleanup, text) if cleanup else text)  # type: ignore[attr-defined]
            self._post_file_visibility(has_file=False)  # type: ignore[attr-defined]
            return

        # Detect lexer from file extension
        _, ext = os.path.splitext(expanded_path)
        lexer = _EXTENSION_TO_LEXER.get(ext.lower(), "text")

        # Store content for future re-render
        self._full_content = content
        self._full_content_lexer = lexer
        self._content_mode = "static"
        self._static_header_path = expanded_path

        # Compute trimming
        total = self._count_lines(content)  # type: ignore[attr-defined]
        trim_size = self._compute_trim_size()  # type: ignore[attr-defined]
        self._total_line_count = total
        self._base_trim_size = trim_size

        header = Text(expanded_path, style="bold #D7AF5F underline")

        if trim_size > 0 and total > trim_size:
            self._visible_line_count = trim_size
            self._is_trimmed = True
            syntax = lazy_renderable(
                content,
                lexer,
                line_numbers=True,
                line_range=(1, trim_size),
            )
            remaining = total - trim_size
            indicator = Text(
                f"\n  \u25be {remaining} more lines below",
                style="dim italic #87D7FF",
            )
            self.update(Group(*cleanup, header, Text(""), syntax, indicator))  # type: ignore[attr-defined]
            # Word-wrapped lines may overflow — schedule post-layout fix
            self.call_after_refresh(self._check_trim_overflow)  # type: ignore[attr-defined]
        else:
            self._visible_line_count = total
            self._is_trimmed = False
            syntax = lazy_renderable(
                content,
                lexer,
                line_numbers=True,
            )
            self.update(Group(*cleanup, header, Text(""), syntax))  # type: ignore[attr-defined]
            # Container was hidden/not laid out — trim after layout
            if trim_size == 0:
                self.call_after_refresh(self._apply_deferred_trim)  # type: ignore[attr-defined]

        self._has_displayed_content = True
        self._post_file_visibility(has_file=True)  # type: ignore[attr-defined]
        self._post_trim_changed()  # type: ignore[attr-defined]

    def _display_static_image(self, expanded_path: str) -> None:
        """Display a static raster image through the terminal graphics layer."""
        cleanup = self._consume_image_cleanup_segments()
        capability = self._graphics_capability()
        columns, rows = self._image_preview_size()
        renderable = image_preview(
            expanded_path,
            capability,
            columns=columns,
            rows=rows,
        )

        self._current_image_renderable = (
            renderable if isinstance(renderable, KittyImageRenderable) else None
        )
        self._full_content = None
        self._full_content_lexer = "text"  # type: ignore[attr-defined]
        self._content_mode = "image"  # type: ignore[attr-defined]
        self._static_header_path = expanded_path
        self._total_line_count = rows + 2  # type: ignore[attr-defined]
        self._visible_line_count = rows + 2  # type: ignore[attr-defined]
        self._base_trim_size = 0  # type: ignore[attr-defined]
        self._is_trimmed = False  # type: ignore[attr-defined]

        header = Text(expanded_path, style="bold #D7AF5F underline")
        self.update(Group(*cleanup, header, Text(""), renderable))  # type: ignore[attr-defined]
        self._has_displayed_content = True  # type: ignore[attr-defined]
        self._post_file_visibility(has_file=os.path.exists(expanded_path))  # type: ignore[attr-defined]
        self._post_trim_changed()  # type: ignore[attr-defined]

    def _graphics_capability(self) -> GraphicsCapability:
        """Return the app-level graphics capability, or an unavailable fallback."""
        try:
            capability = getattr(self.app, "graphics_capability", None)  # type: ignore[attr-defined]
        except Exception:
            capability = None
        if isinstance(capability, GraphicsCapability):
            return capability
        return GraphicsCapability.unavailable("terminal graphics were not probed")

    def _image_preview_size(self) -> tuple[int, int]:
        """Choose a placeholder size from the visible file-scroll viewport."""
        scroll = self._get_scroll_container()  # type: ignore[attr-defined]
        return image_preview_size_for_viewport(
            scroll_widget=scroll,
            content_widget=self,
            reserved_rows=2,
        )

    def _consume_image_cleanup_segments(self) -> list[TerminalControlRenderable]:
        """Return terminal cleanup controls for the active Kitty image, if any."""
        current = getattr(self, "_current_image_renderable", None)
        self._current_image_renderable = None
        if isinstance(current, KittyImageRenderable):
            return [TerminalControlRenderable(current.cleanup_sequence())]
        return []

    def _show_loading(self) -> None:
        """Display loading indicator only if panel was previously visible."""
        if not self._has_displayed_content:
            return
        text = Text()
        text.append("Loading file...\n", style="bold #87D7FF")
        text.append("Please wait while fetching changes.", style="dim")
        self.update(text)  # type: ignore[attr-defined]

    def show_empty(self) -> None:
        """Show empty state."""
        self._reset_trim_state()  # type: ignore[attr-defined]
        self._has_displayed_content = False
        text = Text("No agent selected", style="dim italic")
        self.update(text)  # type: ignore[attr-defined]
