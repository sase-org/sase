"""Image preview helpers for the ACE TUI."""

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
from ._viewer_launch import (
    artifact_tmux_pane_exists,
    close_artifact_tmux_pane,
    is_tmux_session,
    view_agent_artifact,
    view_agent_artifact_in_tmux_pane,
    view_agent_artifacts,
    view_agent_artifacts_in_tmux_pane,
    view_artifact_file,
    view_artifact_file_in_tmux_pane,
    view_artifact_files,
    view_artifact_files_in_tmux_pane,
    view_image_file,
)
from ._viewer_loop import (
    artifact_image_area,
    kitten_icat_command,
    page_index_after_key,
    run_artifact_page_loop,
    run_artifact_sequence_loop,
)
from ._viewer_render import (
    artifact_markdown_pdf_profile_for_image_area,
    artifact_view_mode,
    convert_pdf_to_png_pages,
    render_artifact_pages,
    validate_artifact_viewer_dependencies,
)
from ._viewer_types import (
    ArtifactImageArea,
    ArtifactRenderResult,
    ArtifactViewSpec,
    ArtifactViewerResult,
    ArtifactViewerWarning,
    ImageViewerResult,
)

__all__ = [
    "CELL_IMAGE_BACKGROUND",
    "ImageFallbackRenderable",
    "ImageRenderContext",
    "ArtifactImageArea",
    "ArtifactRenderResult",
    "ArtifactViewSpec",
    "ArtifactViewerResult",
    "ArtifactViewerWarning",
    "ImageViewerResult",
    "artifact_image_area",
    "artifact_markdown_pdf_profile_for_image_area",
    "artifact_tmux_pane_exists",
    "MAX_CELL_IMAGE_FILE_BYTES",
    "MAX_CELL_IMAGE_PIXELS",
    "SUPPORTED_IMAGE_EXTENSIONS",
    "UPPER_HALF_BLOCK",
    "CellImageRenderable",
    "artifact_view_mode",
    "close_artifact_tmux_pane",
    "clear_cell_image_cache",
    "convert_pdf_to_png_pages",
    "has_truecolor",
    "image_preview",
    "image_preview_size_for_viewport",
    "image_render_context",
    "is_supported_image_path",
    "is_tmux_session",
    "kitten_icat_command",
    "page_index_after_key",
    "render_artifact_pages",
    "run_artifact_sequence_loop",
    "run_artifact_page_loop",
    "validate_artifact_viewer_dependencies",
    "view_agent_artifact",
    "view_agent_artifacts",
    "view_agent_artifact_in_tmux_pane",
    "view_agent_artifacts_in_tmux_pane",
    "view_artifact_file",
    "view_artifact_files",
    "view_artifact_file_in_tmux_pane",
    "view_artifact_files_in_tmux_pane",
    "view_image_file",
]
