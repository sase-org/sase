"""Terminal graphics helpers for the ace TUI."""

from .capability import (
    GraphicsCapability,
    detect_graphics_capability,
    has_truecolor,
)
from .images import (
    INLINE_IMAGE_EXTENSIONS,
    SUPPORTED_IMAGE_EXTENSIONS,
    is_inline_image_path,
    is_supported_image_path,
)
from .kitty import (
    KITTY_PLACEHOLDER,
    build_delete_sequence,
    build_place_sequence,
    build_png_upload_sequences,
    generate_image_id,
    placeholder_grid,
    tmux_passthrough_wrap,
)
from .renderable import (
    ImageFallbackRenderable,
    KittyImageRenderable,
    TerminalControlRenderable,
    image_preview,
)
from .sizing import image_preview_size_for_viewport

__all__ = [
    "GraphicsCapability",
    "INLINE_IMAGE_EXTENSIONS",
    "ImageFallbackRenderable",
    "KITTY_PLACEHOLDER",
    "KittyImageRenderable",
    "SUPPORTED_IMAGE_EXTENSIONS",
    "TerminalControlRenderable",
    "build_delete_sequence",
    "build_place_sequence",
    "build_png_upload_sequences",
    "detect_graphics_capability",
    "generate_image_id",
    "has_truecolor",
    "image_preview",
    "image_preview_size_for_viewport",
    "is_inline_image_path",
    "is_supported_image_path",
    "placeholder_grid",
    "tmux_passthrough_wrap",
]
