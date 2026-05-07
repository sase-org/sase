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
FULL_BLOCK = "\u2588"
CELL_IMAGE_SHARPNESS = 1.15

RGB = tuple[int, int, int]
SegmentLine = tuple[Segment, ...]


class CellImageError(Exception):
    """Raised when a portable cell preview cannot be rendered."""


@dataclass(frozen=True)
class _BlockMask:
    glyph: str
    foreground_mask: int


# 2x2 subpixel bit order: upper-left, upper-right, lower-left, lower-right.
_UPPER_LEFT = 0b0001
_UPPER_RIGHT = 0b0010
_LOWER_LEFT = 0b0100
_LOWER_RIGHT = 0b1000
_ALL_SUBPIXELS = _UPPER_LEFT | _UPPER_RIGHT | _LOWER_LEFT | _LOWER_RIGHT

_BLOCK_MASKS: tuple[_BlockMask, ...] = (
    _BlockMask(FULL_BLOCK, _ALL_SUBPIXELS),
    _BlockMask(" ", 0),
    _BlockMask(UPPER_HALF_BLOCK, _UPPER_LEFT | _UPPER_RIGHT),
    _BlockMask("\u2584", _LOWER_LEFT | _LOWER_RIGHT),
    _BlockMask("\u258c", _UPPER_LEFT | _LOWER_LEFT),
    _BlockMask("\u2590", _UPPER_RIGHT | _LOWER_RIGHT),
    _BlockMask("\u2598", _UPPER_LEFT),
    _BlockMask("\u259d", _UPPER_RIGHT),
    _BlockMask("\u2596", _LOWER_LEFT),
    _BlockMask("\u2597", _LOWER_RIGHT),
    _BlockMask("\u259a", _UPPER_LEFT | _LOWER_RIGHT),
    _BlockMask("\u259e", _UPPER_RIGHT | _LOWER_LEFT),
    _BlockMask("\u259b", _UPPER_LEFT | _UPPER_RIGHT | _LOWER_LEFT),
    _BlockMask("\u259c", _UPPER_LEFT | _UPPER_RIGHT | _LOWER_RIGHT),
    _BlockMask("\u2599", _UPPER_LEFT | _LOWER_LEFT | _LOWER_RIGHT),
    _BlockMask("\u259f", _UPPER_RIGHT | _LOWER_LEFT | _LOWER_RIGHT),
)


@dataclass(frozen=True)
class CellImageRenderable:
    """Rich renderable that paints an image with adaptive colored block cells."""

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
        from PIL import Image, ImageEnhance, ImageOps, UnidentifiedImageError
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

            oriented = ImageOps.exif_transpose(source)
            rgba = oriented.convert("RGBA")
    except CellImageError:
        raise
    except UnidentifiedImageError as exc:
        raise CellImageError("image could not be decoded") from exc
    except OSError as exc:
        raise CellImageError(f"image could not be decoded: {exc}") from exc

    pixel_width = max(1, columns * 2)
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
    rgb = ImageEnhance.Sharpness(canvas.convert("RGB")).enhance(CELL_IMAGE_SHARPNESS)

    lines: list[SegmentLine] = []
    for y in range(0, pixel_height, 2):
        segments: list[Segment] = []
        for x in range(0, pixel_width, 2):
            upper_left = cast(RGB, rgb.getpixel((x, y)))
            upper_right = cast(RGB, rgb.getpixel((min(x + 1, pixel_width - 1), y)))
            lower_left = cast(RGB, rgb.getpixel((x, min(y + 1, pixel_height - 1))))
            lower_right = cast(
                RGB,
                rgb.getpixel(
                    (
                        min(x + 1, pixel_width - 1),
                        min(y + 1, pixel_height - 1),
                    )
                ),
            )
            segments.append(
                _segment_for_cell(
                    (upper_left, upper_right, lower_left, lower_right),
                    truecolor,
                    background,
                )
            )
        lines.append(tuple(segments))
    return tuple(lines)


def _segment_for_cell(
    subpixels: tuple[RGB, RGB, RGB, RGB],
    truecolor: bool,
    background: RGB,
) -> Segment:
    best_mask = _BLOCK_MASKS[0]
    best_foreground = _average_color(subpixels, best_mask.foreground_mask, background)
    best_background = _average_color(
        subpixels,
        _ALL_SUBPIXELS ^ best_mask.foreground_mask,
        background,
    )
    best_error = _mask_error(
        subpixels,
        best_mask.foreground_mask,
        best_foreground,
        best_background,
    )

    for block_mask in _BLOCK_MASKS[1:]:
        foreground = _average_color(subpixels, block_mask.foreground_mask, background)
        mask_background = _average_color(
            subpixels,
            _ALL_SUBPIXELS ^ block_mask.foreground_mask,
            background,
        )
        error = _mask_error(
            subpixels,
            block_mask.foreground_mask,
            foreground,
            mask_background,
        )
        if error < best_error:
            best_mask = block_mask
            best_foreground = foreground
            best_background = mask_background
            best_error = error

    return Segment(
        best_mask.glyph,
        Style(
            color=_rich_color(best_foreground, truecolor),
            bgcolor=_rich_color(best_background, truecolor),
        ),
    )


def _average_color(
    subpixels: tuple[RGB, RGB, RGB, RGB],
    mask: int,
    fallback: RGB,
) -> RGB:
    selected = [rgb for index, rgb in enumerate(subpixels) if mask & (1 << index)]
    if not selected:
        return fallback
    return (
        round(sum(rgb[0] for rgb in selected) / len(selected)),
        round(sum(rgb[1] for rgb in selected) / len(selected)),
        round(sum(rgb[2] for rgb in selected) / len(selected)),
    )


def _mask_error(
    subpixels: tuple[RGB, RGB, RGB, RGB],
    mask: int,
    foreground: RGB,
    background: RGB,
) -> int:
    error = 0
    for index, rgb in enumerate(subpixels):
        target = foreground if mask & (1 << index) else background
        error += _color_error(rgb, target)
    return error


def _color_error(first: RGB, second: RGB) -> int:
    return (
        (first[0] - second[0]) ** 2
        + (first[1] - second[1]) ** 2
        + (first[2] - second[2]) ** 2
    )


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
        f"Image preview unavailable: {reason}",
        style="dim italic #D7AF5F",
    )


def clear_cell_image_cache() -> None:
    """Clear cached cell image previews."""
    _cell_image_lines.cache_clear()
