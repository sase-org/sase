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
from .viewer import ImageViewerResult, view_image_file

__all__ = [
    "CELL_IMAGE_BACKGROUND",
    "ImageFallbackRenderable",
    "ImageRenderContext",
    "ImageViewerResult",
    "MAX_CELL_IMAGE_FILE_BYTES",
    "MAX_CELL_IMAGE_PIXELS",
    "SUPPORTED_IMAGE_EXTENSIONS",
    "UPPER_HALF_BLOCK",
    "CellImageRenderable",
    "clear_cell_image_cache",
    "has_truecolor",
    "image_preview",
    "image_preview_size_for_viewport",
    "image_render_context",
    "is_supported_image_path",
    "view_image_file",
]
