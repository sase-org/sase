"""Portable Rich cell renderable for raster image previews."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, cast

from rich.color import Color
from rich.console import ConsoleOptions, RenderResult
from rich.segment import Segment
from rich.style import Style
from rich.text import Text

if TYPE_CHECKING:
    from rich.console import Console


MAX_CELL_IMAGE_FILE_BYTES = 25 * 1024 * 1024
MAX_CELL_IMAGE_PIXELS = 40_000_000
CELL_IMAGE_BACKGROUND = (18, 18, 18)
UPPER_HALF_BLOCK = "\u2580"

RGB = tuple[int, int, int]
SegmentLine = tuple[Segment, ...]


class CellImageError(Exception):
    """Raised when a portable cell preview cannot be rendered."""


@dataclass(frozen=True)
class CellImageRenderable:
    """Rich renderable that paints an image with colored half-block cells."""

    path: str
    columns: int
    rows: int
    truecolor: bool
    background: RGB = CELL_IMAGE_BACKGROUND

    @classmethod
    def from_path(
        cls,
        path: str,
        *,
        columns: int,
        rows: int,
        truecolor: bool,
        background: RGB = CELL_IMAGE_BACKGROUND,
    ) -> CellImageRenderable:
        """Create a cell renderable and validate that the image can decode."""
        expanded = os.path.abspath(os.path.expanduser(path))
        columns = max(1, int(columns))
        rows = max(1, int(rows))
        stat = os.stat(expanded)
        if stat.st_size > MAX_CELL_IMAGE_FILE_BYTES:
            limit = MAX_CELL_IMAGE_FILE_BYTES // (1024 * 1024)
            raise CellImageError(f"image file is larger than {limit} MiB")

        _cell_image_lines(
            expanded,
            stat.st_mtime_ns,
            stat.st_size,
            columns,
            rows,
            truecolor,
            background,
        )
        return cls(
            path=expanded,
            columns=columns,
            rows=rows,
            truecolor=truecolor,
            background=background,
        )

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        del console, options
        try:
            stat = os.stat(self.path)
            lines = _cell_image_lines(
                self.path,
                stat.st_mtime_ns,
                stat.st_size,
                self.columns,
                self.rows,
                self.truecolor,
                self.background,
            )
        except OSError as exc:
            yield _fallback_text(str(exc))
            return
        except CellImageError as exc:
            yield _fallback_text(str(exc))
            return

        for line in lines:
            yield from line
            yield Segment.line()


@lru_cache(maxsize=64)
def _cell_image_lines(
    path: str,
    mtime_ns: int,
    file_size: int,
    columns: int,
    rows: int,
    truecolor: bool,
    background: RGB,
) -> tuple[SegmentLine, ...]:
    del mtime_ns, file_size
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as exc:
        raise CellImageError("Pillow is not installed") from exc

    try:
        with Image.open(path) as source:
            source.seek(0)
            width, height = source.size
            if width <= 0 or height <= 0:
                raise CellImageError("image has invalid dimensions")
            if width * height > MAX_CELL_IMAGE_PIXELS:
                limit = f"{MAX_CELL_IMAGE_PIXELS:,}"
                raise CellImageError(f"image is larger than {limit} pixels")

            rgba = source.convert("RGBA")
    except CellImageError:
        raise
    except UnidentifiedImageError as exc:
        raise CellImageError("image could not be decoded") from exc
    except OSError as exc:
        raise CellImageError(f"image could not be decoded: {exc}") from exc

    pixel_width = max(1, columns)
    pixel_height = max(1, rows * 2)
    canvas = Image.new("RGBA", (pixel_width, pixel_height), (*background, 255))
    resized = ImageOps.contain(
        rgba,
        (pixel_width, pixel_height),
        method=Image.Resampling.LANCZOS,
    )
    left = (pixel_width - resized.width) // 2
    top = (pixel_height - resized.height) // 2
    canvas.alpha_composite(resized, (left, top))
    rgb = canvas.convert("RGB")

    lines: list[SegmentLine] = []
    for y in range(0, pixel_height, 2):
        segments: list[Segment] = []
        for x in range(pixel_width):
            upper = cast(RGB, rgb.getpixel((x, y)))
            lower = cast(RGB, rgb.getpixel((x, min(y + 1, pixel_height - 1))))
            segments.append(
                Segment(
                    UPPER_HALF_BLOCK,
                    Style(
                        color=_rich_color(upper, truecolor),
                        bgcolor=_rich_color(lower, truecolor),
                    ),
                )
            )
        lines.append(tuple(segments))
    return tuple(lines)


def _rich_color(rgb: RGB, truecolor: bool) -> Color:
    red, green, blue = rgb
    if truecolor:
        return Color.from_rgb(red, green, blue)
    return Color.from_ansi(_rgb_to_ansi_256(red, green, blue))


def _rgb_to_ansi_256(red: int, green: int, blue: int) -> int:
    if red == green == blue:
        if red < 8:
            return 16
        if red > 248:
            return 231
        return 232 + round((red - 8) / 247 * 24)

    def cube(value: int) -> int:
        return round(value / 255 * 5)

    return 16 + (36 * cube(red)) + (6 * cube(green)) + cube(blue)


def _fallback_text(reason: str) -> Text:
    return Text(
        f"Portable image preview unavailable: {reason}",
        style="dim italic #D7AF5F",
    )


def clear_cell_image_cache() -> None:
    """Clear cached cell image previews."""
    _cell_image_lines.cache_clear()
