"""Video preview modal tests for prompt paths."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.testing import wait_for
from sase.ace.tui.graphics import (
    CellImageRenderable,
    ImageFallbackRenderable,
    VideoPreviewInfo,
    image_preview_size_for_viewport,
)
from sase.ace.tui.graphics._viewer_video_media import VideoMetadata
from sase.ace.tui.modals.preview_panel_video_modal import VideoPreviewPanelModal
import sase.ace.tui.modals.preview_panel_video_modal as video_modal_module
from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload


class _VideoPreviewModalTestApp(App[None]):
    def __init__(self, payload: PreviewPayload) -> None:
        super().__init__()
        self.payload = payload

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(VideoPreviewPanelModal(self.payload))


def _video_payload(path: Path) -> PreviewPayload:
    return PreviewPayload(
        kind_label="video",
        icon="@",
        title=path.name,
        source_path=str(path),
        content="",
        lexer="text",
        media="video",
    )


def _info(duration: float | None = 100.0) -> VideoPreviewInfo:
    metadata = VideoMetadata(
        duration_seconds=duration,
        width=320,
        height=180,
        fps=30,
        codec="h264",
        size_bytes=1_234_567,
    )
    summary = "0:10 · 320×180 · 30 fps · h264 · 1.2 MB"
    return VideoPreviewInfo(
        metadata=metadata,
        summary=summary,
        duration_seconds=duration,
        notice=None
        if duration is not None
        else "ffprobe not found: video metadata unavailable",
    )


def _band_text(modal: VideoPreviewPanelModal) -> str:
    console = Console(record=True, force_terminal=False)
    console.print(modal._properties_band)  # noqa: SLF001
    return console.export_text().strip()


async def test_video_modal_metadata_and_viewport_frame_run_off_main_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PIL import Image

    from sase.ace.tui.graphics import image_render_context

    video = tmp_path / "sample.mp4"
    video.write_bytes(b"video")
    frame = tmp_path / "frame.png"
    Image.new("RGBA", (64, 36), (0, 200, 20, 255)).save(frame)
    thread_checks: list[bool] = []

    def load_info(path: str) -> VideoPreviewInfo:
        thread_checks.append(threading.current_thread() is threading.main_thread())
        assert path == str(video)
        return _info(10)

    def render_frame(
        path: str,
        at_seconds: float,
        context: Any,
        *,
        columns: int,
        rows: int,
    ) -> CellImageRenderable:
        thread_checks.append(threading.current_thread() is threading.main_thread())
        assert path == str(video)
        assert at_seconds == 0
        return CellImageRenderable.from_path(
            frame,
            columns=columns,
            rows=rows,
            truecolor=(context or image_render_context()).truecolor,
        )

    monkeypatch.setattr(video_modal_module, "load_video_preview_info", load_info)
    monkeypatch.setattr(video_modal_module, "video_preview_frame", render_frame)
    app = _VideoPreviewModalTestApp(_video_payload(video))

    async with app.run_test(size=(100, 30)) as pilot:
        modal = app.screen_stack[-1]
        assert isinstance(modal, VideoPreviewPanelModal)
        await wait_for(
            pilot,
            lambda: (
                isinstance(
                    modal._image_renderable,  # noqa: SLF001
                    CellImageRenderable,
                )
                and modal._video_info is not None
            ),  # noqa: SLF001
        )

        from textual.containers import VerticalScroll

        expected = image_preview_size_for_viewport(
            scroll_widget=modal.query_one("#preview-scroll", VerticalScroll),
            content_widget=modal.query_one("#preview-content", Static),
        )
        renderable = modal._image_renderable  # noqa: SLF001
        assert isinstance(renderable, CellImageRenderable)
        assert (renderable.columns, renderable.rows) == expected
        assert "0:10 · 320×180 · 30 fps · h264 · 1.2 MB" in _band_text(modal)
        assert "frame 1/10 · 00:00.0 / 00:10.0" in _band_text(modal)

    assert thread_checks and not any(thread_checks)


async def test_video_modal_decile_stepping_and_clamping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"video")
    calls: list[float] = []
    monkeypatch.setattr(
        video_modal_module, "load_video_preview_info", lambda _path: _info()
    )

    def render_frame(
        _path: str,
        at_seconds: float,
        _context: Any,
        *,
        columns: int,
        rows: int,
    ) -> Text:
        calls.append(at_seconds)
        return Text(f"frame at {at_seconds} ({columns}×{rows})")

    monkeypatch.setattr(video_modal_module, "video_preview_frame", render_frame)
    app = _VideoPreviewModalTestApp(_video_payload(video))

    async with app.run_test(size=(100, 30)) as pilot:
        modal = app.screen_stack[-1]
        assert isinstance(modal, VideoPreviewPanelModal)
        await wait_for(pilot, lambda: modal._video_info is not None)  # noqa: SLF001
        await wait_for(
            pilot,
            lambda: (
                bool(calls) and calls[-1] == 0.0 and not modal._video_frame_in_flight  # noqa: SLF001
            ),
        )

        await pilot.press("h")
        await pilot.pause()
        assert calls[-1] == 0.0
        assert all(stamp == 0.0 for stamp in calls)

        await pilot.press("l")
        await wait_for(pilot, lambda: calls[-1:] == [10.0])
        assert "frame 2/10 · 00:10.0 / 01:40.0" in _band_text(modal)

        await pilot.press("h")
        await wait_for(pilot, lambda: calls[-1:] == [0.0])
        await pilot.press("5")
        await wait_for(pilot, lambda: calls[-1:] == [50.0])
        assert "frame 6/10 · 00:50.0 / 01:40.0" in _band_text(modal)
        await pilot.press("9")
        await wait_for(pilot, lambda: calls[-1:] == [90.0])
        await pilot.press("l")
        await pilot.pause()
        assert calls[-1] == 90.0


async def test_video_modal_coalesces_frame_extractions_to_latest_decile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"video")
    first_started = threading.Event()
    release_first = threading.Event()
    lock = threading.Lock()
    calls: list[float] = []
    active = 0
    max_active = 0
    monkeypatch.setattr(
        video_modal_module, "load_video_preview_info", lambda _path: _info()
    )

    def render_frame(
        _path: str,
        at_seconds: float,
        _context: Any,
        *,
        columns: int,
        rows: int,
    ) -> Text:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            calls.append(at_seconds)
            first = len(calls) == 1
        if first:
            first_started.set()
            release_first.wait(timeout=5)
        with lock:
            active -= 1
        return Text(f"frame at {at_seconds} ({columns}×{rows})")

    monkeypatch.setattr(video_modal_module, "video_preview_frame", render_frame)
    app = _VideoPreviewModalTestApp(_video_payload(video))

    try:
        async with app.run_test(size=(100, 30)) as pilot:
            modal = app.screen_stack[-1]
            assert isinstance(modal, VideoPreviewPanelModal)
            await wait_for(pilot, first_started.is_set)
            await wait_for(pilot, lambda: modal._video_info is not None)  # noqa: SLF001
            await pilot.press("l")
            await pilot.press("l")
            await pilot.press("l")
            assert max_active == 1
            release_first.set()
            await wait_for(
                pilot,
                lambda: (
                    bool(calls)
                    and calls[-1] == 30.0
                    and not modal._video_frame_in_flight  # noqa: SLF001
                ),
            )
            assert 0.0 in calls
            assert 30.0 in calls
            assert 10.0 not in calls
            assert 20.0 not in calls
            await wait_for(
                pilot,
                lambda: "frame at 30.0" in modal._build_content().plain,  # noqa: SLF001
            )
    finally:
        release_first.set()

    assert max_active == 1


async def test_unknown_duration_warns_and_hides_stepping_hints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"video")
    notifications: list[tuple[str, str | None]] = []
    frame_calls: list[float] = []
    monkeypatch.setattr(
        video_modal_module,
        "load_video_preview_info",
        lambda _path: _info(None),
    )
    monkeypatch.setattr(
        video_modal_module,
        "video_preview_frame",
        lambda _path, at, _context, **_kwargs: frame_calls.append(at) or Text("frame"),
    )
    app = _VideoPreviewModalTestApp(_video_payload(video))
    monkeypatch.setattr(
        app,
        "notify",
        lambda message, severity=None, **_kwargs: notifications.append(
            (message, severity)
        ),
    )

    async with app.run_test(size=(100, 30)) as pilot:
        modal = app.screen_stack[-1]
        assert isinstance(modal, VideoPreviewPanelModal)
        await wait_for(pilot, lambda: modal._video_probe_complete)  # noqa: SLF001
        await wait_for(pilot, lambda: bool(frame_calls))
        assert "h/l" not in modal._build_footer()  # noqa: SLF001
        await pilot.press("l")
        await pilot.pause()

    assert notifications == [
        ("Video duration unknown; press Z for the artifact viewer", "warning")
    ]
    assert frame_calls
    assert all(stamp == 0.0 for stamp in frame_calls)


async def test_video_fallback_warnings_and_viewer_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"video")
    notifications: list[tuple[str, str | None]] = []
    viewer_calls: list[tuple[Any, str]] = []
    monkeypatch.setattr(
        video_modal_module, "load_video_preview_info", lambda _path: _info()
    )
    monkeypatch.setattr(
        video_modal_module,
        "video_preview_frame",
        lambda *_args, **_kwargs: ImageFallbackRenderable(
            str(video),
            "ffmpeg executable not found",
            "Press Z to open it in the artifact viewer",
            heading="▶ video preview unavailable",
            name=video.name,
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals._source_file_actions.open_artifact_path",
        lambda app, path: viewer_calls.append((app, path)),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals._source_file_actions.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("video preview must not launch an editor")
        ),
    )
    app = _VideoPreviewModalTestApp(_video_payload(video))
    monkeypatch.setattr(
        app,
        "notify",
        lambda message, severity=None, **_kwargs: notifications.append(
            (message, severity)
        ),
    )

    async with app.run_test(size=(100, 30)) as pilot:
        modal = app.screen_stack[-1]
        assert isinstance(modal, VideoPreviewPanelModal)
        await wait_for(
            pilot,
            lambda: (
                isinstance(
                    modal._image_renderable,  # noqa: SLF001
                    ImageFallbackRenderable,
                )
                and modal._video_info is not None
            ),  # noqa: SLF001
        )
        fallback = modal._image_renderable  # noqa: SLF001
        assert isinstance(fallback, ImageFallbackRenderable)
        console = Console(width=2000, record=True, force_terminal=False)
        console.print(fallback)
        fallback_text = console.export_text()
        assert "▶ video preview unavailable" in fallback_text
        assert video.name in fallback_text
        assert str(video) in fallback_text
        assert "ffmpeg executable not found" in fallback_text
        assert "Press Z" in fallback_text
        assert "VIDEO" in modal._build_title().plain  # noqa: SLF001
        assert modal._build_footer() == (  # noqa: SLF001
            "h/l ±10% | 0-9 jump | Y path | % copy | Z inspect/play | esc close"
        )

        await pilot.press("/")
        await pilot.press("y")
        await pilot.press("o")
        await pilot.press("Z")
        await pilot.pause()

    assert notifications == [
        ("Search is not available for video previews", "warning"),
        ("Video previews have no text to copy; press Y to copy the path", "warning"),
        ("Videos open in the artifact viewer; press Z", "warning"),
    ]
    assert len(viewer_calls) == 1
    assert viewer_calls[0][1] == str(video)
