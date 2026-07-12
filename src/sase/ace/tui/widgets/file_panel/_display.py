"""Static file and diff display mixin for the file panel."""

import os
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
    is_supported_video_path,
)

from ..prompt_panel._agent_context_common import (
    COLOR_WORKSPACE_GLYPH,
    COLOR_WORKSPACE_NAME,
    COLOR_WORKSPACE_PATH,
    WORKSPACE_GLYPH,
)
from ._messages import (
    _LIVE_DIFF_SENTINEL,
    is_commit_slot,
    is_linked_slot,
)
from ._static_read import (
    StaticReadResult,
    normalized_static_path as _normalized_static_path,
    read_static_file as _read_static_file,
)


class FilePanelDisplayMixin:
    """Mixin providing static file/diff display for AgentFilePanel."""

    _full_content: str | None
    _static_header_path: str | None
    _linked_repo_name: str | None
    _linked_workspace_dir: str | None
    _linked_fetched_at: datetime | None
    _content_fetched_at: datetime | None
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
        self._consume_image_cleanup_segments()

        # Build refresh indicator if stale and background refreshing
        refresh_indicator = ""
        if is_stale and self._is_background_refreshing:  # type: ignore[attr-defined]
            refresh_indicator = " (refreshing...)"

        if diff_output:
            # Keep the timestamp separate so unchanged refreshes reuse the
            # cached body renderable instead of re-lexing the diff.
            self._full_content = diff_output
            self._full_content_lexer = "diff"
            self._content_mode = "diff"
            self._content_fetched_at = fetch_time
            self._render_full_content(refreshing=bool(refresh_indicator))  # type: ignore[attr-defined]
        else:
            self._reset_content_state()  # type: ignore[attr-defined]
            text = Text()
            text.append("Last fetched: ", style="dim")
            text.append(fetch_time.strftime("%H:%M:%S"), style="#87D7FF")
            if refresh_indicator:
                text.append(refresh_indicator, style="dim italic")
            text.append("\n\n")
            text.append("No changes detected.\n", style="dim italic")
            self.update(text)  # type: ignore[attr-defined]
            self._post_line_count_changed()  # type: ignore[attr-defined]

        self._has_displayed_content = True

    def _build_linked_banner(
        self,
        repo_name: str | None = None,
        workspace_dir: str | None = None,
        fetched_at: datetime | None = None,
    ) -> Text:
        """Build the banner shown above linked-repository diffs."""
        repo = repo_name or self._linked_repo_name or "linked repo"
        workspace = workspace_dir or self._linked_workspace_dir
        fetched = fetched_at if fetched_at is not None else self._linked_fetched_at

        banner = Text()
        banner.append(WORKSPACE_GLYPH, style=COLOR_WORKSPACE_GLYPH)
        banner.append(f" {repo}", style=COLOR_WORKSPACE_NAME)
        banner.append(" · linked repo", style="dim")
        if workspace or fetched:
            banner.append("\n")
            if workspace:
                banner.append(workspace, style=COLOR_WORKSPACE_PATH)
            if fetched:
                if workspace:
                    banner.append(" · ", style="dim")
                banner.append(
                    f"fetched {fetched.strftime('%H:%M:%S')}",
                    style="dim #87D7FF",
                )
        return banner

    def display_linked_diff(
        self,
        repo_name: str,
        workspace_dir: str,
        diff_text: str,
        fetched_at: datetime | None,
    ) -> None:
        """Display a cached linked-repository diff page."""
        fetch_time = fetched_at or datetime.now()
        self._last_file_content = diff_text
        self._linked_repo_name = repo_name
        self._linked_workspace_dir = workspace_dir
        self._linked_fetched_at = fetch_time
        self._static_header_path = None
        self._post_file_visibility(has_file=True)  # type: ignore[attr-defined]
        self._consume_image_cleanup_segments()
        self._full_content = diff_text
        self._full_content_lexer = "diff"
        self._content_mode = "linked_diff"
        self._content_fetched_at = fetch_time
        self._render_full_content()  # type: ignore[attr-defined]
        self._has_displayed_content = True

    def display_linked_diff_unavailable(self, repo_name: str) -> None:
        """Display a temporary placeholder for a linked page whose cache vanished."""
        cleanup = self._consume_image_cleanup_segments()
        self._reset_content_state()  # type: ignore[attr-defined]
        self._last_file_content = None
        self._linked_repo_name = repo_name
        banner = self._build_linked_banner(repo_name=repo_name)
        body = Text(
            "No linked-repo changes are currently cached.\n", style="dim italic"
        )
        self.update(Group(*cleanup, banner, Text(""), body))  # type: ignore[attr-defined]
        self._has_displayed_content = True
        self._post_file_visibility(has_file=True)  # type: ignore[attr-defined]
        self._post_line_count_changed()  # type: ignore[attr-defined]

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
        if is_supported_video_path(expanded_path):
            self._cancel_static_worker()
            self._static_request_id += 1
            self._display_static_video(expanded_path)
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
            if current == _LIVE_DIFF_SENTINEL or is_linked_slot(current):
                return
            expected_path = current
            if is_commit_slot(current):
                resolver = getattr(self, "_commit_diff_path_for_slot", None)
                expected_path = resolver(current) if callable(resolver) else None
            if _normalized_static_path(expected_path) != _normalized_static_path(
                result.path
            ):
                return
        if result.status == "image":
            # Edge case: the file's extension-based image detection diverged
            # between the schedule path and the worker. Re-route to the image
            # display now that we're back on the UI thread.
            self._display_static_image(result.expanded_path)
            return
        if result.status == "video":
            self._display_static_video(result.expanded_path)
            return
        if result.mode == "file":
            self._render_static_file_result(result)
        else:
            self._render_static_diff_result(result)

    def _render_static_file_result(self, result: StaticReadResult) -> None:
        """UI-thread render for a non-image static-file read result."""
        cleanup = self._consume_image_cleanup_segments()
        if result.status == "missing":
            self._reset_content_state()  # type: ignore[attr-defined]
            text = Text("Could not read file.\n", style="dim italic")
            self.update(Group(*cleanup, text) if cleanup else text)  # type: ignore[attr-defined]
            self._post_file_visibility(has_file=False)  # type: ignore[attr-defined]
            self._post_line_count_changed()  # type: ignore[attr-defined]
            return
        if result.status == "empty":
            self._reset_content_state()  # type: ignore[attr-defined]
            text = Text("File is empty.\n", style="dim italic")
            self.update(Group(*cleanup, text) if cleanup else text)  # type: ignore[attr-defined]
            self._post_file_visibility(has_file=False)  # type: ignore[attr-defined]
            self._post_line_count_changed()  # type: ignore[attr-defined]
            return

        content = result.content or ""
        expanded_path = result.expanded_path
        lexer = result.lexer

        self._full_content = content
        self._full_content_lexer = lexer
        self._content_mode = "static"
        self._static_header_path = expanded_path

        self._render_full_content()  # type: ignore[attr-defined]

        self._has_displayed_content = True
        self._post_file_visibility(has_file=True)  # type: ignore[attr-defined]

    def _render_static_diff_result(self, result: StaticReadResult) -> None:
        """UI-thread render for a static-diff read result."""
        cleanup = self._consume_image_cleanup_segments()
        if result.status == "missing":
            self._reset_content_state()  # type: ignore[attr-defined]
            text = Text("Could not read diff file.\n", style="dim italic")
            self.update(Group(*cleanup, text) if cleanup else text)  # type: ignore[attr-defined]
            self._post_file_visibility(has_file=False)  # type: ignore[attr-defined]
            self._post_line_count_changed()  # type: ignore[attr-defined]
            return
        if result.status == "empty":
            self._reset_content_state()  # type: ignore[attr-defined]
            text = Text("Diff file is empty.\n", style="dim italic")
            self.update(Group(*cleanup, text) if cleanup else text)  # type: ignore[attr-defined]
            self._post_file_visibility(has_file=False)  # type: ignore[attr-defined]
            self._post_line_count_changed()  # type: ignore[attr-defined]
            return

        diff_content = result.content or ""
        expanded_path = result.expanded_path

        diff_with_header = f"# Static diff (from saved file)\n\n{diff_content}"

        self._full_content = diff_with_header
        self._full_content_lexer = "diff"
        self._content_mode = "static_diff"
        self._static_header_path = expanded_path

        self._render_full_content()  # type: ignore[attr-defined]

        self._has_displayed_content = True
        self._post_file_visibility(has_file=True)  # type: ignore[attr-defined]

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
        self._is_content_capped = False  # type: ignore[attr-defined]

        header = Text(expanded_path, style="bold #D7AF5F underline")
        self.update(Group(*cleanup, header, Text(""), renderable))  # type: ignore[attr-defined]
        self._has_displayed_content = True  # type: ignore[attr-defined]
        self._post_file_visibility(has_file=os.path.exists(expanded_path))  # type: ignore[attr-defined]
        self._post_line_count_changed()  # type: ignore[attr-defined]

    def _display_static_video(self, expanded_path: str) -> None:
        """Display a static video placeholder instead of reading binary text."""
        cleanup = self._consume_image_cleanup_segments()

        self._full_content = None
        self._full_content_lexer = "text"  # type: ignore[attr-defined]
        self._content_mode = "video"  # type: ignore[attr-defined]
        self._static_header_path = expanded_path
        self._total_line_count = 6  # type: ignore[attr-defined]
        self._visible_line_count = 6  # type: ignore[attr-defined]
        self._is_content_capped = False  # type: ignore[attr-defined]

        header = Text(expanded_path, style="bold #D7AF5F underline")
        placeholder = _video_file_placeholder(expanded_path)
        self.update(Group(*cleanup, header, Text(""), placeholder))  # type: ignore[attr-defined]
        self._has_displayed_content = True  # type: ignore[attr-defined]
        self._post_file_visibility(has_file=True)  # type: ignore[attr-defined]
        self._post_line_count_changed()  # type: ignore[attr-defined]

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


def _video_file_placeholder(expanded_path: str) -> Text:
    name = os.path.basename(expanded_path) or expanded_path
    text = Text()
    text.append("▶ video", style="bold #D7AF5F")
    text.append("\n")
    text.append(name, style="bold #87D7FF")
    text.append("\n")
    text.append(expanded_path, style="dim")
    text.append("\n\n")
    text.append("use the view key to play", style="dim italic")
    return text
