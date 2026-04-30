"""Rich renderables for TUI image previews."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from rich.console import ConsoleOptions, RenderResult
from rich.segment import Segment
from rich.text import Text

from .capability import GraphicsCapability
from .images import is_supported_image_path
from .kitty import (
    build_delete_sequence,
    build_place_sequence,
    build_png_upload_sequences,
    generate_image_id,
    placeholder_grid,
)

if TYPE_CHECKING:
    from rich.console import Console


@dataclass(frozen=True)
class TerminalControlRenderable:
    """Rich renderable that emits one raw terminal control sequence."""

    sequence: str

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        del console, options
        yield _terminal_control(self.sequence)


@dataclass(frozen=True)
class ImageFallbackRenderable:
    """Textual fallback shown when terminal image rendering is unavailable."""

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
        yield text


@dataclass(frozen=True)
class KittyImageRenderable:
    """Rich renderable that uploads a PNG and prints Kitty placeholder cells."""

    path: str
    image_id: int
    placement_id: int
    columns: int
    rows: int
    passthrough: str = "none"
    chunk_size: int = 4096

    @classmethod
    def from_path(
        cls,
        path: str,
        *,
        columns: int,
        rows: int,
        passthrough: str = "none",
    ) -> KittyImageRenderable:
        """Create a renderable with stable IDs for a local PNG path."""
        expanded = os.path.abspath(os.path.expanduser(path))
        stat = os.stat(expanded)
        key = f"{expanded}:{stat.st_mtime_ns}:{stat.st_size}"
        image_id = generate_image_id(key)
        placement_id = generate_image_id(f"placement:{key}")
        return cls(
            path=expanded,
            image_id=image_id,
            placement_id=placement_id,
            columns=columns,
            rows=rows,
            passthrough=passthrough,
        )

    def cleanup_sequence(self) -> str:
        """Return the Kitty sequence that frees this renderable's image ID."""
        return build_delete_sequence(
            self.image_id,
            tmux=self.passthrough == "tmux",
        )

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        del console, options
        expanded = os.path.expanduser(self.path)
        with open(expanded, "rb") as file:
            png_bytes = file.read()

        tmux = self.passthrough == "tmux"
        for sequence in build_png_upload_sequences(
            png_bytes,
            self.image_id,
            chunk_size=self.chunk_size,
            tmux=tmux,
        ):
            yield _terminal_control(sequence)

        yield _terminal_control(
            build_place_sequence(
                self.image_id,
                self.placement_id,
                columns=self.columns,
                rows=self.rows,
                tmux=tmux,
            )
        )

        style_sequence = _placeholder_sgr(self.image_id, self.placement_id)
        for row in placeholder_grid(self.columns, self.rows):
            yield _terminal_control(style_sequence)
            yield Segment(row)
            yield _terminal_control("\x1b[0m")
            yield Segment.line()


def image_preview(
    path: str,
    capability: GraphicsCapability,
    *,
    columns: int = 40,
    rows: int = 12,
) -> KittyImageRenderable | ImageFallbackRenderable:
    """Return a renderable for a local image path without raising on fallback."""
    expanded = os.path.abspath(os.path.expanduser(path))
    if not is_supported_image_path(expanded):
        return ImageFallbackRenderable(
            expanded, "file extension is not a supported image type"
        )
    if not os.path.exists(expanded):
        return ImageFallbackRenderable(expanded, "file does not exist")
    if not capability.supported or capability.protocol != "kitty":
        return ImageFallbackRenderable(expanded, capability.reason)
    if Path(expanded).suffix.lower() != ".png":
        return ImageFallbackRenderable(
            expanded,
            "Kitty preview foundation currently transmits PNG bytes only",
        )
    try:
        return KittyImageRenderable.from_path(
            expanded,
            columns=columns,
            rows=rows,
            passthrough=capability.passthrough,
        )
    except OSError as exc:
        return ImageFallbackRenderable(expanded, str(exc))


def _placeholder_sgr(image_id: int, placement_id: int) -> str:
    """Return SGR styling used by Kitty Unicode placeholders.

    Rich's public ``Style`` API in the pinned Textual stack does not expose
    underline-color, so emit the truecolor foreground and underline color as a
    narrow control sequence immediately before each placeholder row.
    """
    image_red = (image_id >> 16) & 0xFF
    image_green = (image_id >> 8) & 0xFF
    image_blue = image_id & 0xFF
    placement_red = (placement_id >> 16) & 0xFF
    placement_green = (placement_id >> 8) & 0xFF
    placement_blue = placement_id & 0xFF
    return (
        f"\x1b[38;2;{image_red};{image_green};{image_blue}m"
        f"\x1b[58;2;{placement_red};{placement_green};{placement_blue}m"
    )


def _terminal_control(sequence: str) -> Segment:
    """Return a Rich segment that preserves raw terminal control bytes."""
    return Segment(sequence, control=cast(Any, True))
