"""Artifact-aware terminal viewer helpers for TUI surfaces."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from sase.attachments.markdown_pdf import render_markdown_pdf

from . import _viewer_loop, _viewer_render
from ._viewer_launch import (
    artifact_file_tmux_pane_exists,
    artifact_file_viewer_module_command,
    close_artifact_file_tmux_pane,
    decorate_artifact_file_tmux_panes,
    is_tmux_session,
    restore_artifact_file_tmux_pane_decoration,
    select_tmux_pane,
    TmuxPaneDecorationResult,
    TmuxPaneDecorationState,
    toggle_artifact_file_tmux_pane_zoom,
    view_registered_artifact_file,
    view_registered_artifact_file_in_tmux_pane,
    view_registered_artifact_files,
    view_registered_artifact_files_in_tmux_pane,
    view_artifact_file,
    view_artifact_file_in_tmux_pane,
    view_artifact_files,
    view_artifact_files_in_tmux_pane,
    view_image_file,
)
from ._viewer_loop import (
    ArtifactVideoPlaybackConfig,
    artifact_image_area,
    artifact_header_panel,
    artifact_text_viewer_command,
    artifact_video_player_command,
    format_artifact_header_path,
    kitten_icat_command,
    load_artifact_video_playback_config,
    page_index_after_key,
    page_loop_available_keys,
    print_page_prompt,
    print_text_prompt,
    run_artifact_page_loop,
    run_artifact_text_viewer,
)
from ._viewer_render import (
    artifact_markdown_pdf_profile_for_image_area,
    artifact_file_view_mode,
    convert_pdf_to_png_pages,
    validate_artifact_file_viewer_dependencies,
)
from ._viewer_types import (
    ArtifactFileImageArea,
    ArtifactRenderResult,
    ArtifactFileViewerResult,
    ArtifactFileViewerWarning,
    ArtifactViewMode,
    ArtifactFileViewSpec,
    ImageViewerResult,
)
from .videos import SUPPORTED_VIDEO_EXTENSIONS, is_supported_video_path

_artifact_header_panel = artifact_header_panel
_artifact_file_viewer_module_command = artifact_file_viewer_module_command
_format_artifact_header_path = format_artifact_header_path
_print_page_prompt = print_page_prompt


def render_artifact_file_pages(
    path: str | Path,
    *,
    kind: str | None = None,
    cache_dir: str | Path | None = None,
    image_area: ArtifactFileImageArea | None = None,
) -> ArtifactRenderResult:
    """Render *path* into one or more image pages for terminal display."""

    original = _viewer_render.render_markdown_pdf
    _viewer_render.render_markdown_pdf = render_markdown_pdf
    try:
        return _viewer_render.render_artifact_file_pages(
            path,
            kind=kind,
            cache_dir=cache_dir,
            image_area=image_area,
        )
    finally:
        _viewer_render.render_markdown_pdf = original


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
) -> _viewer_loop._PageLoopResult:
    """Display an artifact sequence with page and document navigation."""

    original = _viewer_loop.render_artifact_file_pages
    _viewer_loop.render_artifact_file_pages = render_artifact_file_pages
    try:
        return _viewer_loop.run_artifact_sequence_loop(
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
        )
    finally:
        _viewer_loop.render_artifact_file_pages = original


def _parse_viewer_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m sase.ace.tui.graphics.viewer",
        description="Open a SASE artifact in the terminal artifact viewer.",
    )
    parser.add_argument("path", nargs="+", help="Artifact file path to view")
    parser.add_argument(
        "-k",
        "--kind",
        action="append",
        default=None,
        help="Artifact kind used to choose the viewer mode",
    )
    args = parser.parse_args(argv)
    if args.kind is not None and len(args.kind) != len(args.path):
        parser.error("--kind must be supplied once per artifact path")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """Run the artifact viewer module entry point."""

    args = _parse_viewer_args(argv)
    kinds = args.kind or [None] * len(args.path)
    result = view_artifact_files(
        tuple(
            ArtifactFileViewSpec(path, kind or None)
            for path, kind in zip(args.path, kinds, strict=True)
        )
    )
    if result.ok:
        return 0
    if result.warning is not None:
        print(result.warning, file=sys.stderr)
    return 1


__all__ = [
    "ArtifactFileImageArea",
    "ArtifactRenderResult",
    "ArtifactViewMode",
    "ArtifactFileViewSpec",
    "ArtifactFileViewerResult",
    "ArtifactFileViewerWarning",
    "ArtifactVideoPlaybackConfig",
    "ImageViewerResult",
    "SUPPORTED_VIDEO_EXTENSIONS",
    "artifact_image_area",
    "artifact_markdown_pdf_profile_for_image_area",
    "artifact_text_viewer_command",
    "artifact_video_player_command",
    "artifact_file_tmux_pane_exists",
    "artifact_file_view_mode",
    "close_artifact_file_tmux_pane",
    "convert_pdf_to_png_pages",
    "is_tmux_session",
    "is_supported_video_path",
    "kitten_icat_command",
    "load_artifact_video_playback_config",
    "main",
    "page_index_after_key",
    "page_loop_available_keys",
    "print_text_prompt",
    "render_artifact_file_pages",
    "run_artifact_page_loop",
    "run_artifact_sequence_loop",
    "run_artifact_text_viewer",
    "select_tmux_pane",
    "toggle_artifact_file_tmux_pane_zoom",
    "validate_artifact_file_viewer_dependencies",
    "view_registered_artifact_file",
    "view_registered_artifact_file_in_tmux_pane",
    "view_registered_artifact_files",
    "view_registered_artifact_files_in_tmux_pane",
    "view_artifact_file",
    "view_artifact_file_in_tmux_pane",
    "view_artifact_files",
    "view_artifact_files_in_tmux_pane",
    "view_image_file",
]


if __name__ == "__main__":
    raise SystemExit(main())
