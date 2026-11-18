"""Exact-frame extraction for the terminal video viewer."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ._viewer_video_cache import (
    artifact_video_cache_dir,
    content_digest_for_path,
    enforce_cache_budget,
    unlink_quietly,
)

_FRAME_EXTRACT_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class FrameExtractResult:
    """Typed outcome of a single exact-frame extraction."""

    path: Path | None
    cached: bool
    error: str | None

    @property
    def ok(self) -> bool:
        """Return True when a frame file is ready to display."""

        return self.path is not None and self.error is None


def extract_frame(
    video_path: str | Path,
    at_seconds: float,
    max_pixel_width: int,
    *,
    cache_dir: str | Path | None = None,
    timeout: float = _FRAME_EXTRACT_TIMEOUT_SECONDS,
) -> FrameExtractResult:
    """Extract the exact frame at *at_seconds*, scaled to *max_pixel_width*."""

    try:
        at = max(0.0, float(at_seconds))
        width = max(1, int(max_pixel_width))
    except (TypeError, ValueError):
        return FrameExtractResult(
            path=None, cached=False, error="invalid frame parameters"
        )
    if shutil.which("ffmpeg") is None:
        return FrameExtractResult(
            path=None,
            cached=False,
            error="ffmpeg executable not found: video frame unavailable",
        )
    digest = content_digest_for_path(video_path)
    if digest is None:
        return FrameExtractResult(
            path=None, cached=False, error="could not read video file"
        )
    root = artifact_video_cache_dir(cache_dir=cache_dir)
    return extract_frame_with_digest(
        video_path, digest, at, width, root, timeout=timeout
    )


def _extract_frame_command(
    path: str | Path,
    at_seconds: float,
    dest: str | Path,
    max_pixel_width: int,
) -> list[str]:
    """Build the input-seek ffmpeg command that extracts one exact frame."""

    return [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "error",
        "-ss",
        f"{at_seconds:.3f}",
        "-i",
        str(Path(path).expanduser()),
        "-frames:v",
        "1",
        "-vf",
        f"scale=min(iw\\,{max_pixel_width}):-2",
        str(Path(dest).expanduser()),
    ]


def extract_frame_with_digest(
    video_path: str | Path,
    digest: str,
    at_seconds: float,
    max_pixel_width: int,
    root: Path,
    *,
    timeout: float,
) -> FrameExtractResult:
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return FrameExtractResult(
            path=None, cached=False, error=f"could not create frame cache: {exc}"
        )
    dest = (
        root / f"{digest}_w{max_pixel_width}_t{int(round(at_seconds * 1000)):08d}.png"
    )
    try:
        if dest.is_file():
            return FrameExtractResult(path=dest, cached=True, error=None)
    except OSError as exc:
        return FrameExtractResult(
            path=None, cached=False, error=f"could not read frame cache: {exc}"
        )
    try:
        tmp_handle = tempfile.NamedTemporaryFile(
            dir=str(root), prefix=".tmp-frame-", suffix=".png", delete=False
        )
        tmp_path = Path(tmp_handle.name)
        tmp_handle.close()
        # ffmpeg with -nostdin refuses to overwrite an existing file, so drop
        # the placeholder; the unique name still prevents collisions.
        tmp_path.unlink()
    except OSError as exc:
        return FrameExtractResult(
            path=None, cached=False, error=f"could not create frame temp file: {exc}"
        )
    try:
        result = subprocess.run(
            _extract_frame_command(video_path, at_seconds, tmp_path, max_pixel_width),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        unlink_quietly(tmp_path)
        return FrameExtractResult(
            path=None, cached=False, error="ffmpeg frame extraction timed out"
        )
    except OSError as exc:
        unlink_quietly(tmp_path)
        return FrameExtractResult(
            path=None, cached=False, error=f"ffmpeg frame extraction failed: {exc}"
        )
    if result.returncode != 0:
        unlink_quietly(tmp_path)
        return FrameExtractResult(
            path=None,
            cached=False,
            error=f"ffmpeg frame extraction exited with code {result.returncode}",
        )
    try:
        os.replace(tmp_path, dest)
    except OSError as exc:
        unlink_quietly(tmp_path)
        return FrameExtractResult(
            path=None, cached=False, error=f"could not publish frame: {exc}"
        )
    enforce_cache_budget(root)
    return FrameExtractResult(path=dest, cached=False, error=None)
