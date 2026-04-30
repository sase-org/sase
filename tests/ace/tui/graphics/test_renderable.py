from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.segment import Segment

from sase.ace.tui.graphics import (
    GraphicsCapability,
    ImageFallbackRenderable,
    KITTY_PLACEHOLDER,
    KittyImageRenderable,
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


def test_image_preview_falls_back_when_capability_unsupported(tmp_path: Path) -> None:
    image = tmp_path / "sample.png"
    image.write_bytes(PNG_BYTES)

    renderable = image_preview(
        str(image),
        GraphicsCapability.unavailable("no graphics"),
    )

    assert isinstance(renderable, ImageFallbackRenderable)
    assert renderable.reason == "no graphics"


def test_image_preview_returns_kitty_renderable_for_png(tmp_path: Path) -> None:
    image = tmp_path / "sample.png"
    image.write_bytes(PNG_BYTES)

    renderable = image_preview(str(image), _kitty_capability(), columns=2, rows=1)

    assert isinstance(renderable, KittyImageRenderable)
    assert renderable.columns == 2
    assert renderable.rows == 1


def test_jpeg_uses_fallback_until_transcoding_exists(tmp_path: Path) -> None:
    image = tmp_path / "sample.jpg"
    image.write_bytes(b"jpeg")

    renderable = image_preview(str(image), _kitty_capability())

    assert isinstance(renderable, ImageFallbackRenderable)
    assert "PNG files" in renderable.reason


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
