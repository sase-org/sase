"""Static file and diff display mixin for the file panel."""

import os
from dataclasses import dataclass
from datetime import datetime

from rich.console import Group, RenderableType
from rich.text import Text
from textual.worker import Worker

from sase.ace.tui.graphics import (
    ImageRenderContext,
    image_preview,
    image_render_context,
    image_preview_size_for_viewport,
    is_supported_image_path,
)

from ...util.lazy_syntax import lazy_renderable
from ._messages import _EXTENSION_TO_LEXER

# Sentinel used in ``_file_list`` to represent the auto-refreshing live-diff
# slot. Duplicated from ``__init__`` to avoid a circular import; the value
# must stay in sync.
_LIVE_DIFF_SENTINEL = "__live_diff__"


@dataclass
class StaticReadResult:
    """Result of an off-thread static file/diff read.

    ``request_id`` lets the UI thread drop superseded results when the user
    navigates between files faster than reads complete. ``path`` is the
    original path passed in (used for path-match stale checks against the
    current file list); ``expanded_path`` is the user-expanded form actually
    opened.
    """

    request_id: int
    mode: str  # "file" or "diff"
    path: str
    expanded_path: str
    status: str  # "ok" | "missing" | "empty" | "image"
    content: str | None = None
    lexer: str = "text"


def _read_static_file(request_id: int, path: str, mode: str) -> StaticReadResult:
    """Worker-thread entry point that reads a static file or diff from disk."""
    expanded_path = os.path.expanduser(path)
    if mode == "file" and is_supported_image_path(expanded_path):
        return StaticReadResult(
            request_id=request_id,
            mode=mode,
            path=path,
            expanded_path=expanded_path,
            status="image",
        )
    try:
        with open(expanded_path, encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return StaticReadResult(
            request_id=request_id,
            mode=mode,
            path=path,
            expanded_path=expanded_path,
            status="missing",
        )
    if not content.strip():
        return StaticReadResult(
            request_id=request_id,
            mode=mode,
            path=path,
            expanded_path=expanded_path,
            status="empty",
        )
    if mode == "file":
        _, ext = os.path.splitext(expanded_path)
        lexer = _EXTENSION_TO_LEXER.get(ext.lower(), "text")
    else:
        lexer = "diff"
    return StaticReadResult(
        request_id=request_id,
        mode=mode,
        path=path,
        expanded_path=expanded_path,
        status="ok",
        content=content,
        lexer=lexer,
    )


class FilePanelDisplayMixin:
    """Mixin providing static file/diff display for AgentFilePanel."""

    _full_content: str | None
    _static_header_path: str | None
    _static_request_id: int
    _static_worker: "Worker[StaticReadResult] | None"

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
                    f"\n  ▾ {remaining} more lines below",
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
        """Schedule an off-thread read of a static diff file.

        The actual render happens via ``_render_static_diff_result`` after the
        worker completes. Stale results from earlier selections are dropped
        in ``_handle_static_read_result``.
        """
        self._schedule_static_read(diff_path, mode="diff")

    def display_static_file(self, file_path: str) -> None:
        """Schedule an off-thread read of a static file.

        Image files are detected synchronously (cheap path check) and
        rendered immediately on the UI thread, since ``_display_static_image``
        does not perform a blocking text read. All other files are read in
        a thread worker; rendering happens via ``_render_static_file_result``
        after the worker completes.
        """
        expanded_path = os.path.expanduser(file_path)
        if is_supported_image_path(expanded_path):
            # Cancel any in-flight static text read so its result cannot
            # overwrite the image we're about to display.
            self._cancel_static_worker()
            self._static_request_id += 1
            self._display_static_image(expanded_path)
            return
        self._schedule_static_read(file_path, mode="file")

    def _schedule_static_read(self, path: str, *, mode: str) -> None:
        """Cancel any in-flight static read and schedule a new thread worker."""
        self._cancel_static_worker()
        self._static_request_id += 1
        request_id = self._static_request_id

        def task() -> StaticReadResult:
            return _read_static_file(request_id, path, mode)

        worker = self.run_worker(task, thread=True)  # type: ignore[attr-defined]
        self._static_worker = worker

    def _cancel_static_worker(self) -> None:
        """Cancel the in-flight static-read worker, if any."""
        worker = self._static_worker
        if worker is not None and getattr(worker, "is_running", False):
            worker.cancel()
        self._static_worker = None

    def _handle_static_read_result(self, result: StaticReadResult) -> None:
        """Dispatch a worker result to the appropriate UI render helper.

        Drops stale results from superseded reads or from reads whose target
        file is no longer the user's current selection.
        """
        if result.request_id != self._static_request_id:
            return
        # Path-match guard: if the file panel has a populated list, only
        # render when the result still matches the current selection.
        file_list = getattr(self, "_file_list", None)
        if file_list:
            current = file_list[self._current_file_index]  # type: ignore[attr-defined]
            if current == _LIVE_DIFF_SENTINEL or current != result.path:
                return
        if result.status == "image":
            # Edge case: the file's extension-based image detection diverged
            # between the schedule path and the worker. Re-route to the image
            # display now that we're back on the UI thread.
            self._display_static_image(result.expanded_path)
            return
        if result.mode == "file":
            self._render_static_file_result(result)
        else:
            self._render_static_diff_result(result)

    def _render_static_file_result(self, result: StaticReadResult) -> None:
        """UI-thread render for a non-image static-file read result."""
        cleanup = self._consume_image_cleanup_segments()
        if result.status == "missing":
            text = Text("Could not read file.\n", style="dim italic")
            self.update(Group(*cleanup, text) if cleanup else text)  # type: ignore[attr-defined]
            self._post_file_visibility(has_file=False)  # type: ignore[attr-defined]
            return
        if result.status == "empty":
            text = Text("File is empty.\n", style="dim italic")
            self.update(Group(*cleanup, text) if cleanup else text)  # type: ignore[attr-defined]
            self._post_file_visibility(has_file=False)  # type: ignore[attr-defined]
            return

        content = result.content or ""
        expanded_path = result.expanded_path
        lexer = result.lexer

        self._full_content = content
        self._full_content_lexer = lexer
        self._content_mode = "static"
        self._static_header_path = expanded_path

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
                f"\n  ▾ {remaining} more lines below",
                style="dim italic #87D7FF",
            )
            self.update(Group(*cleanup, header, Text(""), syntax, indicator))  # type: ignore[attr-defined]
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
            if trim_size == 0:
                self.call_after_refresh(self._apply_deferred_trim)  # type: ignore[attr-defined]

        self._has_displayed_content = True
        self._post_file_visibility(has_file=True)  # type: ignore[attr-defined]
        self._post_trim_changed()  # type: ignore[attr-defined]

    def _render_static_diff_result(self, result: StaticReadResult) -> None:
        """UI-thread render for a static-diff read result."""
        cleanup = self._consume_image_cleanup_segments()
        if result.status == "missing":
            text = Text("Could not read diff file.\n", style="dim italic")
            self.update(Group(*cleanup, text) if cleanup else text)  # type: ignore[attr-defined]
            self._post_file_visibility(has_file=False)  # type: ignore[attr-defined]
            return
        if result.status == "empty":
            text = Text("Diff file is empty.\n", style="dim italic")
            self.update(Group(*cleanup, text) if cleanup else text)  # type: ignore[attr-defined]
            self._post_file_visibility(has_file=False)  # type: ignore[attr-defined]
            return

        diff_content = result.content or ""
        expanded_path = result.expanded_path

        diff_with_header = f"# Static diff (from saved file)\n\n{diff_content}"

        self._full_content = diff_with_header
        self._full_content_lexer = "diff"
        self._content_mode = "static_diff"
        self._static_header_path = expanded_path

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
                f"\n  ▾ {remaining} more lines below",
                style="dim italic #87D7FF",
            )
            self.update(Group(*cleanup, header, Text(""), syntax, indicator))  # type: ignore[attr-defined]
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
            if trim_size == 0:
                self.call_after_refresh(self._apply_deferred_trim)  # type: ignore[attr-defined]

        self._has_displayed_content = True
        self._post_file_visibility(has_file=True)  # type: ignore[attr-defined]
        self._post_trim_changed()  # type: ignore[attr-defined]

    def _display_static_image(self, expanded_path: str) -> None:
        """Display a static raster image through the preview layer."""
        cleanup = self._consume_image_cleanup_segments()
        context = self._image_render_context()
        columns, rows = self._image_preview_size()
        renderable = image_preview(
            expanded_path,
            context,
            columns=columns,
            rows=rows,
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

    def _image_render_context(self) -> ImageRenderContext:
        """Return the image preview rendering context."""
        return image_render_context()

    def _image_preview_size(self) -> tuple[int, int]:
        """Choose a preview size from the visible file-scroll viewport."""
        scroll = self._get_scroll_container()  # type: ignore[attr-defined]
        return image_preview_size_for_viewport(
            scroll_widget=scroll,
            content_widget=self,
            reserved_rows=2,
        )

    def _consume_image_cleanup_segments(self) -> list[RenderableType]:
        """Compatibility no-op for surfaces that used image cleanup state."""
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
        # Drop any pending static read so its result can't paint over us.
        self._cancel_static_worker()
        self._static_request_id += 1
        text = Text("No agent selected", style="dim italic")
        self.update(text)  # type: ignore[attr-defined]
