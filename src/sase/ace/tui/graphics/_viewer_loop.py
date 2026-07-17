"""Compatibility facade for terminal artifact viewer loops."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ._viewer_loop_media import (
    artifact_text_viewer_command,
    artifact_video_player_command,
    display_text_artifact,
    display_video_artifact,
    load_artifact_video_playback_config,
    text_viewer_command_needs_quit_key,
    video_vo_uses_kitty_placement,
)
from ._viewer_loop_pages import run_artifact_page_loop, run_artifact_text_viewer
from ._viewer_loop_sequence import run_artifact_sequence_loop as sequence_loop
from ._viewer_loop_terminal import (
    _ARTIFACT_VIEWER_HEADER_ROWS,
    _ARTIFACT_VIEWER_RESERVED_COLUMNS,
    _ARTIFACT_VIEWER_RESERVED_ROWS,
    _FOOTER_COLOR,
    _FOOTER_RESET,
    _MIN_IMAGE_COLUMNS,
    _MIN_IMAGE_ROWS,
    _PAGE_LOOP_RESERVED_ROWS,
    _RETURN_TO_ACE_KEY,
    artifact_header_panel,
    artifact_image_area,
    clear_terminal,
    format_artifact_header_path,
    kitten_icat_command,
    move_cursor_below_image,
    page_index_after_key,
    page_loop_available_keys,
    print_artifact_header,
    print_artifact_warning,
    print_page_prompt,
    print_text_prompt,
    read_single_key,
    run_command as default_run_command,
    select_tmux_pane,
    tmux_zoom_available,
    toggle_tmux_zoom,
)
from ._viewer_loop_types import (
    ArtifactVideoPlaybackConfig,
    PageLoopResult,
    TextDisplayResult,
    VideoDisplayResult,
)
from ._viewer_render import render_artifact_file_pages
from ._viewer_types import (
    ArtifactFileImageArea,
    ArtifactFileViewerResult,
    ArtifactFileViewSpec,
)

_PageLoopResult = PageLoopResult
_TextDisplayResult = TextDisplayResult
_VideoDisplayResult = VideoDisplayResult
_clear_terminal = clear_terminal
_display_text_artifact = display_text_artifact
_display_video_artifact = display_video_artifact
_move_cursor_below_image = move_cursor_below_image
_print_artifact_header = print_artifact_header
_print_artifact_warning = print_artifact_warning
_read_single_key = read_single_key
_run_command = default_run_command
_select_tmux_pane = select_tmux_pane
_text_viewer_command_needs_quit_key = text_viewer_command_needs_quit_key
_tmux_zoom_available = tmux_zoom_available
_toggle_tmux_zoom = toggle_tmux_zoom
_video_vo_uses_kitty_placement = video_vo_uses_kitty_placement


def run_artifact_sequence_loop(
    artifacts: Sequence[ArtifactFileViewSpec],
    *,
    cache_root: str | Path,
    read_key: Callable[[], str] | None = None,
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]]
    | None = None,
    image_area: ArtifactFileImageArea | None = None,
    return_pane_id: str | None = None,
    select_pane: Callable[[str], ArtifactFileViewerResult] | None = None,
    tmux_zoom_available: bool | None = None,
    toggle_zoom: Callable[[], ArtifactFileViewerResult] | None = None,
    video_config: ArtifactVideoPlaybackConfig | None = None,
) -> _PageLoopResult:
    """Display an artifact sequence with page and document navigation."""

    return sequence_loop(
        artifacts,
        cache_root=cache_root,
        read_key=read_key,
        run_command=run_command,
        image_area=image_area,
        return_pane_id=return_pane_id,
        select_pane=select_pane,
        tmux_zoom_available=tmux_zoom_available,
        toggle_zoom=toggle_zoom,
        video_config=video_config,
        render_pages=render_artifact_file_pages,
    )


__all__ = [
    "ArtifactVideoPlaybackConfig",
    "_ARTIFACT_VIEWER_HEADER_ROWS",
    "_ARTIFACT_VIEWER_RESERVED_COLUMNS",
    "_ARTIFACT_VIEWER_RESERVED_ROWS",
    "_FOOTER_COLOR",
    "_FOOTER_RESET",
    "_MIN_IMAGE_COLUMNS",
    "_MIN_IMAGE_ROWS",
    "_PAGE_LOOP_RESERVED_ROWS",
    "_PageLoopResult",
    "_RETURN_TO_ACE_KEY",
    "_TextDisplayResult",
    "_VideoDisplayResult",
    "_clear_terminal",
    "_display_text_artifact",
    "_display_video_artifact",
    "_move_cursor_below_image",
    "_print_artifact_header",
    "_print_artifact_warning",
    "_read_single_key",
    "_run_command",
    "_select_tmux_pane",
    "_text_viewer_command_needs_quit_key",
    "_tmux_zoom_available",
    "_toggle_tmux_zoom",
    "_video_vo_uses_kitty_placement",
    "artifact_header_panel",
    "artifact_image_area",
    "artifact_text_viewer_command",
    "artifact_video_player_command",
    "format_artifact_header_path",
    "kitten_icat_command",
    "load_artifact_video_playback_config",
    "page_index_after_key",
    "page_loop_available_keys",
    "print_page_prompt",
    "print_text_prompt",
    "render_artifact_file_pages",
    "run_artifact_page_loop",
    "run_artifact_sequence_loop",
    "run_artifact_text_viewer",
]
