"""Image preview modal tests for the prompt preview reader."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Input, Static

from sase.ace.testing import wait_for
from sase.ace.tui.graphics import (
    CellImageRenderable,
    ImageFallbackRenderable,
    image_preview_size_for_viewport,
)
from sase.ace.tui.modals.preview_panel_image_modal import ImagePreviewPanelModal
import sase.ace.tui.modals.preview_panel_image_modal as image_modal_module
from sase.ace.tui.modals.preview_panel_sizing import max_geometry
from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload


class _ImagePreviewModalTestApp(App[None]):
    def __init__(self, payload: PreviewPayload) -> None:
        super().__init__()
        self.payload = payload

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(ImagePreviewPanelModal(self.payload))


def _write_image(path: Path, *, size: tuple[int, int] = (16, 16)) -> None:
    from PIL import Image

    Image.new("RGBA", size, (255, 0, 0, 255)).save(path)


def _image_payload(path: Path) -> PreviewPayload:
    return PreviewPayload(
        kind_label="image",
        icon="@",
        title=path.name,
        source_path=str(path),
        content="",
        lexer="text",
        media="image",
    )


async def test_image_modal_renders_cell_image_and_max_geometry(
    tmp_path: Path,
) -> None:
    image = tmp_path / "sample.png"
    _write_image(image)
    app = _ImagePreviewModalTestApp(_image_payload(image))

    async with app.run_test(size=(100, 30)) as pilot:
        modal = app.screen_stack[-1]
        assert isinstance(modal, ImagePreviewPanelModal)
        await wait_for(
            pilot,
            lambda: isinstance(
                modal._image_renderable,  # noqa: SLF001
                CellImageRenderable,
            ),
        )
        await pilot.pause()
        await pilot.pause()

        scroll = modal.query_one("#preview-scroll", VerticalScroll)
        content = modal.query_one("#preview-content", Static)
        expected = image_preview_size_for_viewport(
            scroll_widget=scroll,
            content_widget=content,
        )
        renderable = modal._image_renderable  # noqa: SLF001
        assert isinstance(renderable, CellImageRenderable)
        assert (renderable.columns, renderable.rows) == expected

        maximum = max_geometry(100, 30)
        container = modal.query_one("#preview-modal-container", Container)
        assert container.styles.width.cells == maximum.width
        assert container.styles.height.cells == maximum.height


def test_image_modal_footer_and_title(tmp_path: Path) -> None:
    image = tmp_path / "sample.png"
    _write_image(image)
    modal = ImagePreviewPanelModal(_image_payload(image))

    assert modal._build_footer() == "Y path | % copy | Z viewer | esc close"  # noqa: SLF001
    assert "IMAGE" in modal._build_title().plain  # noqa: SLF001


async def test_image_modal_decodes_off_main_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = tmp_path / "sample.png"
    _write_image(image)
    seen: list[bool] = []
    original = image_modal_module.image_preview

    def wrapper(
        path: str,
        context: Any = None,
        *,
        columns: int = 40,
        rows: int = 12,
        fallback_hint: str | None = None,
    ) -> Any:
        seen.append(threading.current_thread() is threading.main_thread())
        return original(
            path,
            context,
            columns=columns,
            rows=rows,
            fallback_hint=fallback_hint,
        )

    monkeypatch.setattr(image_modal_module, "image_preview", wrapper)
    app = _ImagePreviewModalTestApp(_image_payload(image))

    async with app.run_test(size=(100, 30)) as pilot:
        modal = app.screen_stack[-1]
        assert isinstance(modal, ImagePreviewPanelModal)
        await wait_for(
            pilot,
            lambda: isinstance(
                modal._image_renderable,  # noqa: SLF001
                CellImageRenderable,
            ),
        )

    assert seen
    assert not any(seen)


async def test_image_modal_resize_rerenders_with_new_viewport(
    tmp_path: Path,
) -> None:
    image = tmp_path / "sample.png"
    _write_image(image)
    app = _ImagePreviewModalTestApp(_image_payload(image))

    async with app.run_test(size=(100, 30)) as pilot:
        modal = app.screen_stack[-1]
        assert isinstance(modal, ImagePreviewPanelModal)
        await wait_for(
            pilot,
            lambda: isinstance(
                modal._image_renderable,  # noqa: SLF001
                CellImageRenderable,
            ),
        )
        await pilot.pause()
        first_size = modal._image_requested_size  # noqa: SLF001
        assert first_size is not None

        await pilot.resize_terminal(140, 40)
        await wait_for(
            pilot,
            lambda: modal._last_geometry_screen == (140, 40),  # noqa: SLF001
        )

        def _second_render_landed() -> bool:
            requested = modal._image_requested_size  # noqa: SLF001
            renderable = modal._image_renderable  # noqa: SLF001
            return (
                requested is not None
                and requested != first_size
                and isinstance(renderable, CellImageRenderable)
                and (renderable.columns, renderable.rows) == requested
            )

        await wait_for(pilot, _second_render_landed)
        await pilot.pause()

        scroll = modal.query_one("#preview-scroll", VerticalScroll)
        content = modal.query_one("#preview-content", Static)
        expected = image_preview_size_for_viewport(
            scroll_widget=scroll,
            content_widget=content,
        )
        renderable = modal._image_renderable  # noqa: SLF001
        assert isinstance(renderable, CellImageRenderable)
        assert (renderable.columns, renderable.rows) == expected

        maximum = max_geometry(140, 40)
        container = modal.query_one("#preview-modal-container", Container)
        assert container.styles.width.cells == maximum.width
        assert container.styles.height.cells == maximum.height


async def test_image_modal_drops_stale_render(tmp_path: Path) -> None:
    image = tmp_path / "sample.png"
    _write_image(image)
    app = _ImagePreviewModalTestApp(_image_payload(image))

    async with app.run_test(size=(100, 30)) as pilot:
        modal = app.screen_stack[-1]
        assert isinstance(modal, ImagePreviewPanelModal)
        await wait_for(
            pilot,
            lambda: isinstance(
                modal._image_renderable,  # noqa: SLF001
                CellImageRenderable,
            ),
        )
        before = modal._image_renderable  # noqa: SLF001
        columns, rows = modal._image_requested_size  # noqa: SLF001
        old_id = modal._image_request_id  # noqa: SLF001
        modal._image_request_id += 1  # noqa: SLF001
        await modal._render_image(old_id, columns, rows)  # noqa: SLF001
        assert modal._image_renderable is before  # noqa: SLF001


async def test_image_modal_undecodable_renders_viewer_hint(
    tmp_path: Path,
) -> None:
    image = tmp_path / "broken.png"
    image.write_bytes(b"not an image")
    app = _ImagePreviewModalTestApp(_image_payload(image))

    async with app.run_test(size=(100, 30)) as pilot:
        modal = app.screen_stack[-1]
        assert isinstance(modal, ImagePreviewPanelModal)
        await wait_for(
            pilot,
            lambda: isinstance(
                modal._image_renderable,  # noqa: SLF001
                ImageFallbackRenderable,
            ),
        )
        renderable = modal._image_renderable  # noqa: SLF001
        assert isinstance(renderable, ImageFallbackRenderable)
        assert "Z" in renderable.hint


async def test_image_modal_warns_for_search_copy_and_editor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = tmp_path / "sample.png"
    _write_image(image)
    notifications: list[tuple[str, str]] = []
    app = _ImagePreviewModalTestApp(_image_payload(image))

    def notify(
        message: str,
        *,
        severity: str = "information",
        **_kwargs: Any,
    ) -> None:
        notifications.append((message, severity))

    def _fail_run(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("editor must not run for image previews")

    monkeypatch.setattr(
        "sase.ace.tui.modals._source_file_actions.subprocess.run",
        _fail_run,
    )
    monkeypatch.setattr(app, "notify", notify)

    async with app.run_test(size=(100, 30)) as pilot:
        modal = app.screen_stack[-1]
        assert isinstance(modal, ImagePreviewPanelModal)
        await wait_for(
            pilot,
            lambda: modal._image_renderable is not None,  # noqa: SLF001
        )
        await pilot.press("/")
        await pilot.pause()
        assert modal.query_one("#preview-search-input", Input).display is False

        await pilot.press("y")
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()

    assert (
        "Search is not available for image previews",
        "warning",
    ) in notifications
    assert (
        "Image previews have no text to copy; press Y to copy the path",
        "warning",
    ) in notifications
    assert (
        "Images open in the artifact viewer; press Z",
        "warning",
    ) in notifications


async def test_image_modal_z_opens_artifact_viewer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = tmp_path / "sample.png"
    _write_image(image)
    seen: list[tuple[Any, str]] = []

    def fake_open(app: Any, path: str) -> None:
        seen.append((app, path))

    monkeypatch.setattr(
        "sase.ace.tui.modals._source_file_actions.open_artifact_path",
        fake_open,
    )
    app = _ImagePreviewModalTestApp(_image_payload(image))

    async with app.run_test(size=(100, 30)) as pilot:
        modal = app.screen_stack[-1]
        assert isinstance(modal, ImagePreviewPanelModal)
        await wait_for(
            pilot,
            lambda: modal._image_renderable is not None,  # noqa: SLF001
        )
        await pilot.press("Z")
        await pilot.pause()

    assert len(seen) == 1
    assert seen[0][1] == str(image)
