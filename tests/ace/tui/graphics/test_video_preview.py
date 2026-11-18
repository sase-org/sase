"""Public video preview seam tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.graphics import (
    CellImageRenderable,
    ImageFallbackRenderable,
    load_video_preview_info,
    video_preview_frame,
)
from sase.ace.tui.graphics._viewer_video_extract import FrameExtractResult
import sase.ace.tui.graphics.video_preview as video_preview_module


def _write_png(path: Path) -> None:
    from PIL import Image

    Image.new("RGBA", (32, 18), (20, 80, 220, 255)).save(path)


def test_video_preview_frame_renders_extracted_png(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = tmp_path / "frame.png"
    _write_png(frame)
    calls: list[tuple[str, float, int, str | None]] = []

    def fake_extract(
        path: str,
        at_seconds: float,
        pixel_width: int,
        *,
        cache_dir: str | Path | None = None,
    ) -> FrameExtractResult:
        calls.append((path, at_seconds, pixel_width, str(cache_dir)))
        return FrameExtractResult(frame, cached=False, error=None)

    monkeypatch.setattr(video_preview_module, "extract_frame", fake_extract)
    result = video_preview_frame(
        tmp_path / "clip.mp4",
        2.5,
        columns=50,
        rows=20,
        cache_dir=tmp_path / "cache",
    )

    assert isinstance(result, CellImageRenderable)
    assert (result.columns, result.rows) == (50, 20)
    assert calls == [(str(tmp_path / "clip.mp4"), 2.5, 640, str(tmp_path / "cache"))]


def test_video_preview_frame_fallback_includes_reason_and_viewer_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(
        video_preview_module,
        "extract_frame",
        lambda *_args, **_kwargs: FrameExtractResult(
            None,
            cached=False,
            error="ffmpeg executable not found: video frame unavailable",
        ),
    )

    result = video_preview_frame(
        video,
        0,
        columns=40,
        rows=12,
        cache_dir=tmp_path / "cache",
    )
    assert isinstance(result, ImageFallbackRenderable)
    assert result.heading == "▶ video preview unavailable"
    assert result.name == "clip.mp4"
    assert result.reason == "ffmpeg executable not found: video frame unavailable"
    assert "Z" in result.hint


def test_missing_ffprobe_keeps_file_size_and_notice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(video_preview_module.shutil, "which", lambda _name: None)

    info = load_video_preview_info(video, cache_dir=tmp_path / "cache")

    assert info.metadata is not None
    assert info.metadata.size_bytes == len(b"video")
    assert info.duration_seconds is None
    assert info.summary == "5 B"
    assert info.notice == "ffprobe not found: video metadata unavailable"


def test_missing_ffmpeg_uses_cached_frame_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(video_preview_module.shutil, "which", lambda _name: None)

    result = video_preview_frame(
        video,
        0,
        columns=40,
        rows=12,
        cache_dir=tmp_path / "cache",
    )

    assert isinstance(result, ImageFallbackRenderable)
    assert "ffmpeg executable not found" in result.reason
    assert result.path == str(video)
