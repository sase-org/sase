"""Bounded background scrub-track generation for terminal video."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ._viewer_video_cache import (
    artifact_video_cache_dir,
    atomic_write_text,
    content_digest_for_path,
)
from ._viewer_video_media import VideoMetadata

_SCRUB_MAX_FPS = 2.0

_SCRUB_MAX_FRAMES = 240


def scrub_fps_for_duration(duration_seconds: float | None) -> float:
    """Return the background scrub-track fps for *duration_seconds*.

    At most two frames per second and at most 240 frames overall, so short
    clips scrub smoothly while long ones stay bounded.
    """

    if duration_seconds is None or duration_seconds <= 0:
        return _SCRUB_MAX_FPS
    return min(_SCRUB_MAX_FPS, _SCRUB_MAX_FRAMES / duration_seconds)


def start_scrub_track(
    video_path: str | Path,
    duration_seconds: float | None,
    max_pixel_width: int,
    *,
    cache_dir: str | Path | None = None,
    metadata: VideoMetadata | None = None,
    scrub_fps: float | None = None,
) -> ScrubTrack | None:
    """Start (or reuse) the background scrub track for *video_path*."""

    digest = content_digest_for_path(video_path)
    if digest is None:
        return None
    if duration_seconds is None and metadata is not None:
        duration_seconds = metadata.duration_seconds
    try:
        width = max(1, int(max_pixel_width))
    except (TypeError, ValueError):
        return None
    root = artifact_video_cache_dir(cache_dir=cache_dir)
    track = ScrubTrack(
        video_path=video_path,
        digest=digest,
        duration_seconds=duration_seconds,
        max_pixel_width=width,
        cache_dir=root,
        scrub_fps=scrub_fps,
    )
    track.start()
    return track


class ScrubTrack:
    """One background ffmpeg pass that streams scrub frames into the cache."""

    def __init__(
        self,
        *,
        video_path: str | Path,
        digest: str,
        duration_seconds: float | None,
        max_pixel_width: int,
        cache_dir: str | Path,
        scrub_fps: float | None = None,
        popen_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.video_path = Path(video_path).expanduser()
        self.digest = digest
        self.duration_seconds = duration_seconds
        self.max_pixel_width = max_pixel_width
        self.cache_dir = Path(cache_dir).expanduser()
        self.fps = (
            scrub_fps
            if scrub_fps and scrub_fps > 0
            else scrub_fps_for_duration(duration_seconds)
        )
        self.expected_frames = _scrub_frame_count_for_duration(
            duration_seconds, self.fps
        )
        self.track_dir = (
            self.cache_dir / f"{digest}_w{max_pixel_width}_scrub-{self.fps:g}fps"
        )
        self._popen_factory: Callable[..., Any] = popen_factory or subprocess.Popen
        self._proc: Any = None
        self._completed = False
        self._cancelled = False
        self._error: str | None = None

    def start(self) -> None:
        """Spawn the background ffmpeg pass, reusing a completed track."""

        if self._completed or self._proc is not None or self._cancelled:
            return
        if self._reuse_completed_track():
            self._completed = True
            return
        if shutil.which("ffmpeg") is None:
            self._error = "ffmpeg executable not found: scrub track unavailable"
            return
        try:
            self.track_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._error = f"could not create scrub-track dir: {exc}"
            return
        argv = _scrub_track_command(
            self.video_path,
            str(self.track_dir / "frame-%04d.png"),
            self.fps,
            self.max_pixel_width,
        )
        if shutil.which("nice") is not None:
            argv = ["nice", "-n", "10", *argv]
        try:
            self._proc = self._popen_factory(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, ValueError) as exc:
            self._proc = None
            self._error = f"could not start scrub-track ffmpeg: {exc}"

    def nearest(self, at_seconds: float) -> Path | None:
        """Return the cached scrub frame closest to *at_seconds*, if present."""

        self._poll()
        frames = self._present_frame_paths()
        if not frames:
            return None
        try:
            index = int(round(float(at_seconds) * self.fps))
        except (TypeError, ValueError):
            return None
        return frames[max(0, min(index, len(frames) - 1))]

    @property
    def progress(self) -> float:
        """Return the share of expected scrub frames present, from 0 to 1."""

        if self._completed:
            return 1.0
        if self.expected_frames <= 0:
            return 0.0
        return min(1.0, len(self._present_frame_paths()) / self.expected_frames)

    @property
    def done(self) -> bool:
        """Return True when no more scrub frames will arrive."""

        self._poll()
        if self._completed:
            return True
        if self._proc is None:
            return self._error is not None or self._cancelled
        try:
            return self._proc.poll() is not None
        except (OSError, subprocess.SubprocessError):
            return True

    @property
    def error(self) -> str | None:
        """Return the terminal scrub-track failure, if any."""

        self._poll()
        return self._error

    @property
    def frame_paths(self) -> tuple[Path, ...]:
        """Return the scrub frames present on disk, oldest first."""

        return self._present_frame_paths()

    def cancel(self) -> None:
        """Stop the background ffmpeg pass; never raises."""

        self._cancelled = True
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.kill()
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            proc.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass

    def _poll(self) -> None:
        if self._completed or self._proc is None:
            return
        try:
            finished = self._proc.poll() is not None
        except (OSError, subprocess.SubprocessError):
            finished = True
        if not finished:
            return
        code = self._proc.returncode
        if code == 0 and self._track_frames_complete():
            self._write_index()
            self._completed = True
        elif not self._cancelled and self._error is None:
            self._error = f"scrub-track ffmpeg exited with code {code}"

    def _present_frame_paths(self) -> tuple[Path, ...]:
        try:
            frames = sorted(self.track_dir.glob("frame-*.png"))
        except OSError:
            return ()
        return tuple(frame for frame in frames if frame.is_file())

    def _track_frames_complete(self) -> bool:
        return len(self._present_frame_paths()) >= max(1, self.expected_frames)

    def _reuse_completed_track(self) -> bool:
        index_path = self.track_dir / "index.json"
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(payload, dict):
            return False
        if payload.get("digest") != self.digest:
            return False
        try:
            if float(payload.get("fps", 0)) != self.fps:
                return False
            if int(payload.get("max_pixel_width", 0)) != self.max_pixel_width:
                return False
        except (TypeError, ValueError):
            return False
        names = payload.get("frames")
        if not isinstance(names, list) or not names:
            return False
        return all((self.track_dir / str(name)).is_file() for name in names)

    def _write_index(self) -> None:
        frames = self._present_frame_paths()
        payload = {
            "digest": self.digest,
            "fps": self.fps,
            "max_pixel_width": self.max_pixel_width,
            "duration_seconds": self.duration_seconds,
            "frames": [frame.name for frame in frames],
        }
        try:
            atomic_write_text(
                self.track_dir / "index.json",
                json.dumps(payload, indent=2, sort_keys=True),
            )
        except OSError:
            pass


def _scrub_frame_count_for_duration(duration_seconds: float | None, fps: float) -> int:
    """Return the planned scrub-track frame count, capped at 240."""

    if duration_seconds is None or duration_seconds <= 0:
        return _SCRUB_MAX_FRAMES
    if fps <= 0:
        return 1
    return max(1, min(_SCRUB_MAX_FRAMES, int(duration_seconds * fps)))


def _scrub_track_command(
    path: str | Path,
    out_pattern: str | Path,
    fps: float,
    max_pixel_width: int,
) -> list[str]:
    """Build the single-pass ffmpeg command that streams scrub frames."""

    return [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(Path(path).expanduser()),
        "-vf",
        f"fps={fps:g},scale=min(iw\\,{max_pixel_width}):-2",
        "-threads",
        "2",
        str(out_pattern),
    ]
