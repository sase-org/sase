from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console
from rich.segment import Segment

from sase.ace.tui.graphics import (
    CellImageRenderable,
    GraphicsCapability,
    ImageFallbackRenderable,
    KITTY_PLACEHOLDER,
    KittyImageRenderable,
    UPPER_HALF_BLOCK,
    clear_cell_image_cache,
    image_preview,
)


PNG_BYTES = b"\x89PNG\r\n\x1a\nfake"


def _kitty_capability() -> GraphicsCapability:
    return GraphicsCapability(
        supported=True,
        protocol="kitty",
        passthrough="none",
        reason="test",
        terminal="kitty",
        truecolor=True,
        probed=True,
    )


def _cell_capability(*, truecolor: bool = True) -> GraphicsCapability:
    return GraphicsCapability.unavailable(
        "no native graphics",
        truecolor=truecolor,
    )


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


def _render_segments(renderable: object) -> list[Segment]:
    console = Console(record=True, force_terminal=True, width=120)
    return list(console.render(renderable))


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


def test_image_preview_uses_cell_renderable_when_capability_unsupported(
    tmp_path: Path,
) -> None:
    image = tmp_path / "sample.png"
    _write_image(image)

    renderable = image_preview(
        str(image),
        _cell_capability(),
    )

    assert isinstance(renderable, CellImageRenderable)


def test_image_preview_returns_kitty_renderable_for_png(tmp_path: Path) -> None:
    image = tmp_path / "sample.png"
    image.write_bytes(PNG_BYTES)

    renderable = image_preview(str(image), _kitty_capability(), columns=2, rows=1)

    assert isinstance(renderable, KittyImageRenderable)
    assert renderable.columns == 2
    assert renderable.rows == 1


def test_jpeg_webp_and_gif_use_cell_renderable(tmp_path: Path) -> None:
    paths = [
        tmp_path / "sample.jpg",
        tmp_path / "sample.webp",
        tmp_path / "sample.gif",
    ]
    for path in paths:
        _write_image(path)

    renderables = [image_preview(str(path), _kitty_capability()) for path in paths]

    assert all(
        isinstance(renderable, CellImageRenderable) for renderable in renderables
    )


def test_missing_unsupported_and_decode_failing_images_fall_back(
    tmp_path: Path,
) -> None:
    missing = image_preview(str(tmp_path / "missing.png"), _cell_capability())
    unsupported = image_preview(str(tmp_path / "notes.txt"), _cell_capability())
    broken_path = tmp_path / "broken.png"
    broken_path.write_bytes(b"not an image")
    broken = image_preview(str(broken_path), _cell_capability())

    assert isinstance(missing, ImageFallbackRenderable)
    assert missing.reason == "file does not exist"
    assert isinstance(unsupported, ImageFallbackRenderable)
    assert "extension" in unsupported.reason
    assert isinstance(broken, ImageFallbackRenderable)
    assert "portable preview unavailable" in broken.reason


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
            _cell_capability(),
            columns=columns,
            rows=rows,
        )
        segments = _render_segments(renderable)
        lines = _line_segments(segments)

        assert isinstance(renderable, CellImageRenderable)
        assert len(lines) == rows
        assert all(len(line) == columns for line in lines)
        assert sum(segment.text.count(UPPER_HALF_BLOCK) for segment in segments) == (
            columns * rows
        )


def test_cell_cache_invalidates_when_file_metadata_changes(tmp_path: Path) -> None:
    clear_cell_image_cache()
    image = tmp_path / "cached.png"
    _write_image(image, color=(255, 0, 0, 255))

    first = image_preview(str(image), _cell_capability(), columns=2, rows=1)
    first_style = next(
        segment.style for segment in _render_segments(first) if segment.style
    )

    _write_image(image, size=(5, 4), color=(0, 0, 255, 255))
    stat = image.stat()
    os.utime(image, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    second = image_preview(str(image), _cell_capability(), columns=2, rows=1)
    second_style = next(
        segment.style for segment in _render_segments(second) if segment.style
    )

    assert first_style != second_style


def test_no_preview_renderable_emits_more_rows_than_requested(tmp_path: Path) -> None:
    cell_path = tmp_path / "cell.png"
    _write_image(cell_path)
    kitty_path = tmp_path / "kitty.png"
    kitty_path.write_bytes(PNG_BYTES)

    cell = image_preview(str(cell_path), _cell_capability(), columns=4, rows=2)
    kitty = image_preview(str(kitty_path), _kitty_capability(), columns=4, rows=2)

    for renderable in (cell, kitty):
        lines = _line_segments(_render_segments(renderable))
        assert len(lines) <= 2


def test_kitty_renderable_emits_control_segments_and_placeholders(
    tmp_path: Path,
) -> None:
    image = tmp_path / "sample.png"
    image.write_bytes(PNG_BYTES)
    renderable = KittyImageRenderable.from_path(
        str(image),
        columns=2,
        rows=1,
        passthrough="none",
    )

    console = Console(record=True, force_terminal=True, width=20)
    segments = list(console.render(renderable))

    assert any(segment.control for segment in segments)
    assert any(
        isinstance(segment, Segment) and KITTY_PLACEHOLDER in segment.text
        for segment in segments
    )
