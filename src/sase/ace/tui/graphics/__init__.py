"""Image preview helpers for sase's TUI."""

from pathlib import Path

from rich.console import RenderableType

from .capability import ImageRenderContext, has_truecolor, image_render_context
from .cell import (
    CELL_IMAGE_BACKGROUND,
    MAX_CELL_IMAGE_FILE_BYTES,
    MAX_CELL_IMAGE_PIXELS,
    UPPER_HALF_BLOCK,
    CellImageRenderable,
    clear_cell_image_cache,
)
from .images import SUPPORTED_IMAGE_EXTENSIONS, is_supported_image_path
from .renderable import ImageFallbackRenderable, image_preview
from .sizing import image_preview_size_for_viewport
from .videos import SUPPORTED_VIDEO_EXTENSIONS, is_supported_video_path
from ._video_preview_types import (
    VIDEO_PREVIEW_FRAME_PX,
    VideoPreviewInfo,
)
from ._viewer_launch import (
    ArtifactViewerLaunchContext,
    artifact_file_tmux_pane_exists,
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
    ARTIFACT_VIEWER_VIDEO_CONFIG_ENV,
    VIDEO_PLAYBACK_BACKENDS,
    ArtifactVideoPlaybackConfig,
    artifact_image_area,
    artifact_text_viewer_command,
    artifact_video_player_command,
    kitten_icat_command,
    load_artifact_video_playback_config,
    load_merged_artifact_video_playback_config,
    page_index_after_key,
    parse_video_playback_config_env,
    print_text_prompt,
    run_artifact_page_loop,
    run_artifact_sequence_loop,
    run_artifact_text_viewer,
    serialize_video_playback_config,
    video_still_preview_required,
)
from ._viewer_render import (
    artifact_markdown_pdf_profile_for_image_area,
    artifact_file_view_mode,
    convert_pdf_to_png_pages,
    render_artifact_file_pages,
    validate_artifact_file_viewer_dependencies,
)
from ._viewer_types import (
    ArtifactFileImageArea,
    ArtifactRenderResult,
    ArtifactFileViewSpec,
    ArtifactFileViewerResult,
    ArtifactFileViewerWarning,
    ImageViewerResult,
)
from ._viewer_trace import mark_first_visual

__all__ = [
    "CELL_IMAGE_BACKGROUND",
    "ImageFallbackRenderable",
    "ImageRenderContext",
    "VIDEO_PLAYBACK_BACKENDS",
    "VIDEO_PREVIEW_FRAME_PX",
    "VideoPreviewInfo",
    "ArtifactFileImageArea",
    "ArtifactRenderResult",
    "ArtifactFileViewSpec",
    "ArtifactFileViewerResult",
    "ArtifactFileViewerWarning",
    "ArtifactViewerLaunchContext",
    "ArtifactVideoPlaybackConfig",
    "ImageViewerResult",
    "artifact_image_area",
    "artifact_markdown_pdf_profile_for_image_area",
    "artifact_text_viewer_command",
    "artifact_file_tmux_pane_exists",
    "artifact_video_player_command",
    "MAX_CELL_IMAGE_FILE_BYTES",
    "MAX_CELL_IMAGE_PIXELS",
    "SUPPORTED_IMAGE_EXTENSIONS",
    "SUPPORTED_VIDEO_EXTENSIONS",
    "UPPER_HALF_BLOCK",
    "CellImageRenderable",
    "artifact_file_view_mode",
    "close_artifact_file_tmux_pane",
    "clear_cell_image_cache",
    "convert_pdf_to_png_pages",
    "decorate_artifact_file_tmux_panes",
    "has_truecolor",
    "image_preview",
    "image_preview_size_for_viewport",
    "image_render_context",
    "is_supported_image_path",
    "is_supported_video_path",
    "ARTIFACT_VIEWER_VIDEO_CONFIG_ENV",
    "is_tmux_session",
    "kitten_icat_command",
    "load_artifact_video_playback_config",
    "load_merged_artifact_video_playback_config",
    "mark_first_visual",
    "page_index_after_key",
    "parse_video_playback_config_env",
    "serialize_video_playback_config",
    "print_text_prompt",
    "render_artifact_file_pages",
    "restore_artifact_file_tmux_pane_decoration",
    "run_artifact_sequence_loop",
    "run_artifact_page_loop",
    "run_artifact_text_viewer",
    "select_tmux_pane",
    "toggle_artifact_file_tmux_pane_zoom",
    "TmuxPaneDecorationResult",
    "TmuxPaneDecorationState",
    "validate_artifact_file_viewer_dependencies",
    "video_still_preview_required",
    "format_video_preview_position",
    "load_video_preview_info",
    "video_preview_frame",
    "video_preview_timestamp",
    "view_registered_artifact_file",
    "view_registered_artifact_files",
    "view_registered_artifact_file_in_tmux_pane",
    "view_registered_artifact_files_in_tmux_pane",
    "view_artifact_file",
    "view_artifact_files",
    "view_artifact_file_in_tmux_pane",
    "view_artifact_files_in_tmux_pane",
    "view_image_file",
]


def load_video_preview_info(
    path: str | Path,
    *,
    cache_dir: str | Path | None = None,
) -> VideoPreviewInfo:
    """Load video metadata through the lazy prompt-preview service."""
    from .video_preview import load_video_preview_info as load

    return load(path, cache_dir=cache_dir)


def video_preview_frame(
    path: str | Path,
    at_seconds: float,
    context: ImageRenderContext | None = None,
    *,
    columns: int,
    rows: int,
    cache_dir: str | Path | None = None,
) -> RenderableType:
    """Render one video frame through the lazy prompt-preview service."""
    from .video_preview import video_preview_frame as render

    return render(
        path,
        at_seconds,
        context,
        columns=columns,
        rows=rows,
        cache_dir=cache_dir,
    )


def video_preview_timestamp(decile: int, duration_seconds: float | None) -> float:
    """Return a video decile timestamp using the artifact viewer's seek math."""
    from .video_preview import video_preview_timestamp as timestamp

    return timestamp(decile, duration_seconds)


def format_video_preview_position(
    decile: int,
    duration_seconds: float | None,
) -> str:
    """Format the current decile using the artifact viewer's inspect status."""
    from .video_preview import format_video_preview_position as format_position

    return format_position(decile, duration_seconds)
