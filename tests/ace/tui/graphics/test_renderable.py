from __future__ import annotations

import os
from pathlib import Path

import pytest
from rich.console import Console
from rich.segment import Segment

from sase.ace.tui.graphics import (
    CellImageRenderable,
    ImageFallbackRenderable,
    ImageRenderContext,
    UPPER_HALF_BLOCK,
    clear_cell_image_cache,
    image_preview,
)


def _render_context(*, truecolor: bool = True) -> ImageRenderContext:
    return ImageRenderContext(truecolor=truecolor, reason="test")


def _write_image(
    path: Path,
    *,
    size: tuple[int, int] = (4, 4),
    color: tuple[int, int, int, int] = (255, 0, 0, 255),
    image_format: str | None = None,
) -> None:
    from PIL import Image

    image = Image.new("RGBA", size, color)
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        image = image.convert("RGB")
    image.save(path, format=image_format)


def _write_pixels(
    path: Path,
    pixels: list[list[tuple[int, int, int, int]]],
) -> None:
    from PIL import Image

    height = len(pixels)
    width = len(pixels[0])
    image = Image.new("RGBA", (width, height))
    for y, row in enumerate(pixels):
        for x, color in enumerate(row):
            image.putpixel((x, y), color)
    image.save(path)


def _render_segments(renderable: object) -> list[Segment]:
    console = Console(record=True, force_terminal=True, width=120)
    return list(console.render(renderable))


def _cell_segments(renderable: object) -> list[Segment]:
    return [segment for segment in _render_segments(renderable) if segment.text != "\n"]


def _line_segments(segments: list[Segment]) -> list[list[Segment]]:
    lines: list[list[Segment]] = [[]]
    for segment in segments:
        if segment.text == "\n":
            lines.append([])
        else:
            lines[-1].append(segment)
    if lines and not lines[-1]:
        lines.pop()
    return lines


def test_image_preview_uses_cell_renderable(
    tmp_path: Path,
) -> None:
    image = tmp_path / "sample.png"
    _write_image(image)

    renderable = image_preview(
        str(image),
        _render_context(),
    )

    assert isinstance(renderable, CellImageRenderable)


def test_image_preview_returns_cell_renderable_for_png(tmp_path: Path) -> None:
    image = tmp_path / "sample.png"
    _write_image(image)

    renderable = image_preview(
        str(image),
        _render_context(),
        columns=2,
        rows=1,
    )

    assert isinstance(renderable, CellImageRenderable)
    assert renderable.columns == 2
    assert renderable.rows == 1


def test_png_jpeg_webp_and_gif_use_cell_renderable(tmp_path: Path) -> None:
    paths = [
        tmp_path / "sample.png",
        tmp_path / "sample.jpg",
        tmp_path / "sample.webp",
        tmp_path / "sample.gif",
    ]
    for path in paths:
        _write_image(path)

    renderables = [image_preview(str(path), _render_context()) for path in paths]

    assert all(
        isinstance(renderable, CellImageRenderable) for renderable in renderables
    )


def test_missing_unsupported_and_decode_failing_images_fall_back(
    tmp_path: Path,
) -> None:
    missing = image_preview(str(tmp_path / "missing.png"), _render_context())
    unsupported = image_preview(str(tmp_path / "notes.txt"), _render_context())
    broken_path = tmp_path / "broken.png"
    broken_path.write_bytes(b"not an image")
    broken = image_preview(str(broken_path), _render_context())

    assert isinstance(missing, ImageFallbackRenderable)
    assert missing.reason == "file does not exist"
    assert isinstance(unsupported, ImageFallbackRenderable)
    assert "extension" in unsupported.reason
    assert isinstance(broken, ImageFallbackRenderable)
    assert "image preview unavailable" in broken.reason


def test_cell_rendering_respects_requested_dimensions(tmp_path: Path) -> None:
    cases = [
        ("wide.png", (16, 4), (7, 3), (0, 255, 0, 255)),
        ("tall.png", (4, 16), (6, 4), (255, 0, 0, 255)),
        ("tiny.png", (1, 1), (5, 2), (0, 0, 255, 255)),
        ("transparent.png", (4, 4), (4, 3), (255, 255, 255, 0)),
    ]
    for name, image_size, preview_size, color in cases:
        image = tmp_path / name
        _write_image(image, size=image_size, color=color)
        columns, rows = preview_size

        renderable = image_preview(
            str(image),
            _render_context(),
            columns=columns,
            rows=rows,
        )
        segments = _render_segments(renderable)
        lines = _line_segments(segments)

        assert isinstance(renderable, CellImageRenderable)
        assert len(lines) == rows
        assert all(len(line) == columns for line in lines)
        assert len(_cell_segments(renderable)) == columns * rows


def test_diagonal_fixture_selects_diagonal_block_mask(tmp_path: Path) -> None:
    image = tmp_path / "diagonal.png"
    black = (0, 0, 0, 255)
    white = (255, 255, 255, 255)
    _write_pixels(
        image,
        [
            [white, black],
            [black, white],
        ],
    )

    renderable = image_preview(
        str(image),
        _render_context(),
        columns=1,
        rows=1,
    )

    [segment] = _cell_segments(renderable)
    assert segment.text == "\u259a"
    assert segment.style is not None
    assert segment.style.color is not None
    assert segment.style.bgcolor is not None


def test_transparency_composites_against_configured_background(tmp_path: Path) -> None:
    image = tmp_path / "transparent.png"
    _write_image(image, size=(2, 2), color=(255, 0, 0, 0))
    background = (10, 20, 30)

    renderable = CellImageRenderable.from_path(
        str(image),
        columns=1,
        rows=1,
        truecolor=True,
        background=background,
    )

    [segment] = _cell_segments(renderable)
    assert segment.style is not None
    assert segment.style.color is not None
    assert segment.style.bgcolor is not None
    assert segment.style.color.triplet is not None
    assert segment.style.bgcolor.triplet is not None
    assert tuple(segment.style.color.triplet) == background
    assert tuple(segment.style.bgcolor.triplet) == background


def test_exif_orientation_is_applied_before_cell_conversion(tmp_path: Path) -> None:
    from PIL import Image

    image = Image.new("RGBA", (2, 4))
    for y in range(4):
        image.putpixel((0, y), (255, 0, 0, 255))
        image.putpixel((1, y), (0, 0, 255, 255))

    exif = Image.Exif()
    exif[274] = 6
    path = tmp_path / "oriented.png"
    image.save(path, exif=exif)
    with Image.open(path) as reopened:
        if reopened.getexif().get(274) != 6:
            pytest.skip("Pillow did not persist PNG EXIF orientation")

    renderable = image_preview(
        str(path),
        _render_context(),
        columns=2,
        rows=1,
    )

    glyphs = {segment.text for segment in _cell_segments(renderable)}
    assert glyphs <= {UPPER_HALF_BLOCK, "\u2584"}
    assert glyphs


def test_truecolor_and_ansi_256_styles_are_valid(tmp_path: Path) -> None:
    image = tmp_path / "styles.png"
    _write_image(image, color=(70, 120, 220, 255))

    truecolor_renderable = image_preview(
        str(image),
        _render_context(truecolor=True),
        columns=1,
        rows=1,
    )
    ansi_renderable = image_preview(
        str(image),
        _render_context(truecolor=False),
        columns=1,
        rows=1,
    )

    truecolor_style = _cell_segments(truecolor_renderable)[0].style
    ansi_style = _cell_segments(ansi_renderable)[0].style
    assert truecolor_style is not None
    assert truecolor_style.color is not None
    assert truecolor_style.bgcolor is not None
    assert truecolor_style.color.triplet is not None
    assert ansi_style is not None
    assert ansi_style.color is not None
    assert ansi_style.bgcolor is not None


def test_cell_cache_invalidates_when_file_metadata_changes(tmp_path: Path) -> None:
    clear_cell_image_cache()
    image = tmp_path / "cached.png"
    _write_image(image, color=(255, 0, 0, 255))

    first = image_preview(str(image), _render_context(), columns=2, rows=1)
    first_style = next(
        segment.style for segment in _render_segments(first) if segment.style
    )

    _write_image(image, size=(5, 4), color=(0, 0, 255, 255))
    stat = image.stat()
    os.utime(image, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    second = image_preview(str(image), _render_context(), columns=2, rows=1)
    second_style = next(
        segment.style for segment in _render_segments(second) if segment.style
    )

    assert first_style != second_style


def test_no_preview_renderable_emits_more_rows_than_requested(tmp_path: Path) -> None:
    image = tmp_path / "cell.png"
    _write_image(image)

    renderable = image_preview(str(image), _render_context(), columns=4, rows=2)

    lines = _line_segments(_render_segments(renderable))
    assert len(lines) <= 2
