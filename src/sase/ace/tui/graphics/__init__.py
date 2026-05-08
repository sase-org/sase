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
from .viewer import (
    ArtifactRenderResult,
    ArtifactViewerResult,
    ArtifactViewerWarning,
    ImageViewerResult,
    artifact_view_mode,
    convert_pdf_to_png_pages,
    page_index_after_key,
    render_artifact_pages,
    run_artifact_page_loop,
    validate_artifact_viewer_dependencies,
    view_agent_artifact,
    view_artifact_file,
    view_image_file,
)

__all__ = [
    "CELL_IMAGE_BACKGROUND",
    "ImageFallbackRenderable",
    "ImageRenderContext",
    "ArtifactRenderResult",
    "ArtifactViewerResult",
    "ArtifactViewerWarning",
    "ImageViewerResult",
    "MAX_CELL_IMAGE_FILE_BYTES",
    "MAX_CELL_IMAGE_PIXELS",
    "SUPPORTED_IMAGE_EXTENSIONS",
    "UPPER_HALF_BLOCK",
    "CellImageRenderable",
    "artifact_view_mode",
    "clear_cell_image_cache",
    "convert_pdf_to_png_pages",
    "has_truecolor",
    "image_preview",
    "image_preview_size_for_viewport",
    "image_render_context",
    "is_supported_image_path",
    "page_index_after_key",
    "render_artifact_pages",
    "run_artifact_page_loop",
    "validate_artifact_viewer_dependencies",
    "view_agent_artifact",
    "view_artifact_file",
    "view_image_file",
]
