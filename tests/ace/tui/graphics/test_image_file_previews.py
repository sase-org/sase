from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from rich.console import Console

from sase.ace.tui.graphics import (
    ImageFallbackRenderable,
    image_preview_size_for_viewport,
)


def test_image_preview_size_caps_large_viewports() -> None:
    scroll = SimpleNamespace(
        scrollable_content_region=SimpleNamespace(width=220, height=90)
    )

    assert image_preview_size_for_viewport(scroll_widget=scroll) == (160, 60)


def test_image_preview_size_for_tiny_viewport_stays_bounded() -> None:
    scroll = SimpleNamespace(
        scrollable_content_region=SimpleNamespace(width=3, height=2)
    )

    assert image_preview_size_for_viewport(
        scroll_widget=scroll,
        reserved_rows=2,
    ) == (3, 1)


def test_image_fallback_mentions_editor_actions(tmp_path: Path) -> None:
    image = tmp_path / "fallback.jpg"
    image.write_bytes(b"jpeg")
    renderable = ImageFallbackRenderable(str(image), "no graphics")

    console = Console(record=True, width=100)
    console.print(renderable)

    fallback_text = console.export_text()
    assert "Open artifact with A" in fallback_text


def test_image_preview_custom_fallback_hint(tmp_path: Path) -> None:
    from sase.ace.tui.graphics import image_preview

    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    renderable = image_preview(
        str(broken),
        None,
        fallback_hint="Press Z to open it in the artifact viewer",
    )

    assert isinstance(renderable, ImageFallbackRenderable)
    console = Console(record=True, width=100)
    console.print(renderable)
    fallback_text = console.export_text()
    assert "Press Z to open it in the artifact viewer" in fallback_text
    assert "Open artifact with A" not in fallback_text


def test_image_preview_default_fallback_hint(tmp_path: Path) -> None:
    from sase.ace.tui.graphics import image_preview

    broken = tmp_path / "broken-default.png"
    broken.write_bytes(b"not an image")
    renderable = image_preview(str(broken), None)

    assert isinstance(renderable, ImageFallbackRenderable)
    console = Console(record=True, width=100)
    console.print(renderable)
    assert "Open artifact with A" in console.export_text()
