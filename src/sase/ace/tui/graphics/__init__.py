"""Terminal graphics helpers for the ace TUI."""

from .capability import (
    GraphicsCapability,
    detect_graphics_capability,
    has_truecolor,
)
from .images import SUPPORTED_IMAGE_EXTENSIONS, is_supported_image_path
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

__all__ = [
    "GraphicsCapability",
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
    "is_supported_image_path",
    "placeholder_grid",
    "tmux_passthrough_wrap",
]
