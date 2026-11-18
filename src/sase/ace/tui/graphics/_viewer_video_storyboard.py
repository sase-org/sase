"""Decile storyboard extraction and image composition."""

from __future__ import annotations

import concurrent.futures
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from ._viewer_video_cache import (
    artifact_video_cache_dir,
    content_digest_for_path,
    enforce_cache_budget,
    unlink_quietly,
)
from ._viewer_video_extract import extract_frame_with_digest
from ._viewer_video_scrub import ScrubTrack

_STORYBOARD_CELL_COUNT = 10

_FRAME_EXTRACT_TIMEOUT_SECONDS = 15.0

_STORYBOARD_LABEL_HEIGHT_PX = 14

_STORYBOARD_BACKGROUND = (17, 17, 17)


@dataclass(frozen=True)
class StoryboardResult:
    """Typed outcome of a decile storyboard composition."""

    path: Path | None
    cached: bool
    cells: int
    error: str | None

    @property
    def ok(self) -> bool:
        """Return True when a storyboard image is ready to display."""

        return self.path is not None and self.error is None


def build_storyboard(
    video_path: str | Path,
    duration_seconds: float | None,
    max_pixel_width: int,
    *,
    strip_width_px: int,
    strip_height_px: int,
    cache_dir: str | Path | None = None,
    scrub_track: ScrubTrack | None = None,
    source_frames: Sequence[str | Path] | None = None,
    timeout: float = _FRAME_EXTRACT_TIMEOUT_SECONDS,
) -> StoryboardResult:
    """Compose the ten-cell decile storyboard for *video_path*."""

    if duration_seconds is None or duration_seconds <= 0:
        return StoryboardResult(
            path=None, cached=False, cells=0, error="unknown video duration"
        )
    try:
        width = max(1, int(max_pixel_width))
        strip_width = max(1, int(strip_width_px))
        strip_height = max(1, int(strip_height_px))
    except (TypeError, ValueError):
        return StoryboardResult(
            path=None, cached=False, cells=0, error="invalid storyboard parameters"
        )
    digest = content_digest_for_path(video_path)
    if digest is None:
        return StoryboardResult(
            path=None, cached=False, cells=0, error="could not read video file"
        )
    root = artifact_video_cache_dir(cache_dir=cache_dir)
    dest = root / f"{digest}_w{width}_storyboard.png"
    if dest.is_file():
        return StoryboardResult(
            path=dest, cached=True, cells=_STORYBOARD_CELL_COUNT, error=None
        )
    try:
        sources = _resolve_storyboard_sources(
            video_path,
            digest,
            duration_seconds,
            width,
            root,
            scrub_track=scrub_track,
            source_frames=source_frames,
            timeout=timeout,
        )
    except Exception as exc:
        return StoryboardResult(path=None, cached=False, cells=0, error=str(exc))
    if sources is None:
        return StoryboardResult(
            path=None,
            cached=False,
            cells=0,
            error="storyboard extraction failed: missing source frames",
        )
    try:
        _compose_storyboard_image(
            sources, duration_seconds, strip_width, strip_height, dest
        )
    except Exception as exc:
        return StoryboardResult(path=None, cached=False, cells=0, error=str(exc))
    enforce_cache_budget(root)
    return StoryboardResult(
        path=dest, cached=False, cells=_STORYBOARD_CELL_COUNT, error=None
    )


def _resolve_storyboard_sources(
    video_path: str | Path,
    digest: str,
    duration_seconds: float,
    max_pixel_width: int,
    root: Path,
    *,
    scrub_track: ScrubTrack | None,
    source_frames: Sequence[str | Path] | None,
    timeout: float,
) -> list[Path] | None:
    if source_frames is not None:
        if len(source_frames) != _STORYBOARD_CELL_COUNT:
            raise ValueError(
                "storyboard needs exactly "
                f"{_STORYBOARD_CELL_COUNT} source frames, got {len(source_frames)}"
            )
        resolved = [Path(frame).expanduser() for frame in source_frames]
        if any(not frame.is_file() for frame in resolved):
            return None
        return resolved
    timestamps = _storyboard_timestamps_for_duration(duration_seconds)
    if scrub_track is not None and scrub_track.done:
        frames = [scrub_track.nearest(at) for at in timestamps]
        if all(frame is not None for frame in frames):
            return [frame for frame in frames if frame is not None]
    return _extract_storyboard_cells(
        video_path, digest, timestamps, max_pixel_width, root, timeout=timeout
    )


def _extract_storyboard_cells(
    video_path: str | Path,
    digest: str,
    timestamps: Sequence[float],
    max_pixel_width: int,
    root: Path,
    *,
    timeout: float,
) -> list[Path] | None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(
                extract_frame_with_digest,
                video_path,
                digest,
                at,
                max_pixel_width,
                root,
                timeout=timeout,
            )
            for at in timestamps
        ]
        results = [future.result() for future in futures]
    paths = [result.path for result in results if result.ok and result.path is not None]
    if len(paths) != len(timestamps):
        return None
    return paths


def _compose_storyboard_image(
    sources: Sequence[Path],
    duration_seconds: float,
    strip_width_px: int,
    strip_height_px: int,
    dest: Path,
) -> None:
    cols, rows = _storyboard_grid_for_aspect(strip_width_px, strip_height_px)
    cell_width = max(1, strip_width_px // cols)
    cell_total_height = max(_STORYBOARD_LABEL_HEIGHT_PX + 1, strip_height_px // rows)
    thumb_height = cell_total_height - _STORYBOARD_LABEL_HEIGHT_PX
    canvas = Image.new(
        "RGB", (cell_width * cols, cell_total_height * rows), _STORYBOARD_BACKGROUND
    )
    timestamps = _storyboard_timestamps_for_duration(duration_seconds)
    pencil = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, source in enumerate(sources[:_STORYBOARD_CELL_COUNT]):
        with Image.open(source) as frame:
            thumb = frame.convert("RGB")
            thumb.thumbnail((cell_width, thumb_height), Image.Resampling.LANCZOS)
        col, row = index % cols, index // cols
        origin_x, origin_y = col * cell_width, row * cell_total_height
        paste_x = origin_x + max(0, (cell_width - thumb.width) // 2)
        paste_y = origin_y + max(0, (thumb_height - thumb.height) // 2)
        canvas.paste(thumb, (paste_x, paste_y))
        label = _format_storyboard_timestamp(timestamps[index])
        pencil.text(
            (origin_x + 3, origin_y + thumb_height + 1),
            label,
            font=font,
            fill=(255, 255, 255),
        )
    _atomic_write_image(canvas, dest)


def _storyboard_grid_for_aspect(
    strip_width_px: int, strip_height_px: int
) -> tuple[int, int]:
    """Return the (columns, rows) storyboard grid for a strip aspect."""

    if strip_width_px <= 0 or strip_height_px <= 0:
        return (5, 2)
    if strip_width_px / strip_height_px >= 2.0:
        return (_STORYBOARD_CELL_COUNT, 1)
    return (5, 2)


def _storyboard_timestamps_for_duration(
    duration_seconds: float,
) -> tuple[float, ...]:
    """Return the ten decile timestamps for *duration_seconds*."""

    return tuple(
        index * duration_seconds / _STORYBOARD_CELL_COUNT
        for index in range(_STORYBOARD_CELL_COUNT)
    )


def _format_storyboard_timestamp(at_seconds: float) -> str:
    total = max(0.0, at_seconds)
    minutes = int(total // 60)
    seconds = total - minutes * 60
    return f"{minutes}:{seconds:04.1f}"


def _atomic_write_image(canvas: Image.Image, dest: Path) -> None:
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    tmp_handle = tempfile.NamedTemporaryFile(
        dir=str(dest.parent), prefix=".tmp-storyboard-", suffix=".png", delete=False
    )
    tmp_path = Path(tmp_handle.name)
    tmp_handle.close()
    try:
        canvas.save(tmp_path, format="PNG")
        os.replace(tmp_path, dest)
    except (OSError, ValueError):
        unlink_quietly(tmp_path)
        raise
