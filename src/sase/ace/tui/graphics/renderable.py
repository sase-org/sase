"""Rich renderables for TUI image previews."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import ConsoleOptions, RenderResult
from rich.text import Text

from .capability import ImageRenderContext, image_render_context
from .cell import CellImageError, CellImageRenderable
from .images import is_supported_image_path

if TYPE_CHECKING:
    from rich.console import Console


@dataclass(frozen=True)
class ImageFallbackRenderable:
    """Textual fallback shown when image preview rendering is unavailable."""

    path: str
    reason: str

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        del console, options
        text = Text()
        text.append("Image preview unavailable\n", style="bold #D7AF5F")
        text.append(str(Path(self.path).expanduser()), style="#87D7FF underline")
        try:
            size = os.path.getsize(os.path.expanduser(self.path))
        except OSError:
            size = None
        if size is not None:
            text.append(f"\n{size:,} bytes", style="dim")
        text.append(f"\n{self.reason}", style="dim italic")
        text.append("\nOpen with e in notifications or %E in agent panels", style="dim")
        yield text


def image_preview(
    path: str,
    context: ImageRenderContext | None = None,
    *,
    columns: int = 40,
    rows: int = 12,
) -> CellImageRenderable | ImageFallbackRenderable:
    """Return a Pillow-backed renderable for a local image path without raising."""
    expanded = os.path.abspath(os.path.expanduser(path))
    if not is_supported_image_path(expanded):
        return ImageFallbackRenderable(
            expanded, "file extension is not a supported image type"
        )
    if not os.path.exists(expanded):
        return ImageFallbackRenderable(expanded, "file does not exist")

    render_context = context or image_render_context()
    try:
        return CellImageRenderable.from_path(
            expanded,
            columns=columns,
            rows=rows,
            truecolor=render_context.truecolor,
        )
    except OSError as exc:
        return ImageFallbackRenderable(expanded, str(exc))
    except CellImageError as exc:
        return ImageFallbackRenderable(expanded, f"image preview unavailable: {exc}")
