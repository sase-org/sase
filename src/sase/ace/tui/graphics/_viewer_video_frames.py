"""ffmpeg-backed frame service for terminal video artifacts.

This is the UI-free service behind the inspect-first video view: exact-frame
extraction, a low-priority background scrub track, and a decile storyboard,
all served from a content-digest-keyed bounded cache with atomic writes.

PNG is the frame format throughout. JPEG would be smaller, but on-screen text
stays legible in PNG at the half-screen sizes this service targets, and kitty
accepts PNG over the graphics protocol. Frames are downscaled to at most the
pane's pixel width, which keeps typical half-screen stills near the ~350 KB
target without a second encoding pass.

Every blocking helper returns a typed result and never raises into the viewer
loop. The background scrub track is bounded by :meth:`ScrubTrack.cancel`.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from sase.core.paths import ensure_sase_directory

from ._viewer_video_media import (
    VideoMetadata,
    ffprobe_metadata_command,
    parse_ffprobe_metadata,
    probe_video_metadata,
)

_VIDEO_FRAME_CACHE_SUBDIR = "cache/artifact_video"
_DEFAULT_CACHE_MAX_BYTES = 256 * 1024 * 1024
_SCRUB_MAX_FPS = 2.0
_SCRUB_MAX_FRAMES = 240
_STORYBOARD_CELL_COUNT = 10
_FRAME_DIGEST_CHUNK_BYTES = 1024 * 1024
_FRAME_EXTRACT_TIMEOUT_SECONDS = 15.0
_METADATA_PROBE_TIMEOUT_SECONDS = 5.0
_STORYBOARD_LABEL_HEIGHT_PX = 14
_STORYBOARD_BACKGROUND = (17, 17, 17)
_DIGEST_CACHE_MAX_ENTRIES = 64
_DIGEST_CACHE: dict[tuple[str, int, int, int, int], str] = {}
_DIGEST_CACHE_LOCK = threading.Lock()


def _digest_cache_key(
    resolved: str, stat: os.stat_result
) -> tuple[str, int, int, int, int]:
    return (resolved, stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


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


def artifact_video_cache_dir(
    *,
    cache_dir: str | Path | None = None,
) -> Path:
    """Return the persistent video-frame cache directory, creating it."""

    if cache_dir is not None:
        root = Path(cache_dir).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        return root
    return Path(ensure_sase_directory(_VIDEO_FRAME_CACHE_SUBDIR))


def content_digest_for_path(path: str | Path) -> str | None:
    """Return the streamed sha256 hex digest of *path*, or None when unreadable.

    Memoized per viewer process by resolved path plus ``(st_dev, st_ino,
    st_size, st_mtime_ns)``, so one open plus many exact steps hash the file
    once. A changed file (new size, mtime, or inode) re-hashes.
    """

    try:
        resolved_path = str(Path(path).expanduser())
        stat = os.stat(resolved_path)
    except OSError:
        return None
    if not os.path.isfile(resolved_path):
        return None
    key = _digest_cache_key(resolved_path, stat)
    with _DIGEST_CACHE_LOCK:
        cached = _DIGEST_CACHE.get(key)
        if cached is not None:
            return cached
    try:
        digest = hashlib.sha256()
        with open(resolved_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(_FRAME_DIGEST_CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError:
        return None
    hex_digest = digest.hexdigest()
    try:
        fresh = os.stat(resolved_path)
    except OSError:
        return hex_digest
    if _digest_cache_key(resolved_path, fresh) != key:
        return hex_digest
    with _DIGEST_CACHE_LOCK:
        _DIGEST_CACHE[key] = hex_digest
        while len(_DIGEST_CACHE) > _DIGEST_CACHE_MAX_ENTRIES:
            _DIGEST_CACHE.pop(next(iter(_DIGEST_CACHE)))
    return hex_digest


def scrub_fps_for_duration(duration_seconds: float | None) -> float:
    """Return the background scrub-track fps for *duration_seconds*.

    At most two frames per second and at most 240 frames overall, so short
    clips scrub smoothly while long ones stay bounded.
    """

    if duration_seconds is None or duration_seconds <= 0:
        return _SCRUB_MAX_FPS
    return min(_SCRUB_MAX_FPS, _SCRUB_MAX_FRAMES / duration_seconds)


def metadata_for_frame_service(
    path: str | Path,
    *,
    metadata: VideoMetadata | None = None,
    cache_dir: str | Path | None = None,
) -> VideoMetadata | None:
    """Return ffprobe metadata for the frame service, cached when possible.

    A caller-provided *metadata* wins. Otherwise the ffprobe JSON payload is
    cached under the content digest so repeated opens of one clip probe once;
    without a *cache_dir* this falls back to a live probe.
    """

    if metadata is not None:
        return metadata
    if cache_dir is None:
        return probe_video_metadata(path)
    digest = content_digest_for_path(path)
    if digest is None:
        return probe_video_metadata(path)
    root = artifact_video_cache_dir(cache_dir=cache_dir)
    cached = _read_cached_metadata_payload(root, digest)
    if cached is not None:
        return cached
    fresh = _probe_and_cache_metadata(path, root, digest)
    if fresh is not None:
        return fresh
    return None


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
    return _extract_frame_with_digest(
        video_path, digest, at, width, root, timeout=timeout
    )


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


def enforce_cache_budget(
    cache_dir: str | Path,
    *,
    max_bytes: int = _DEFAULT_CACHE_MAX_BYTES,
) -> int:
    """Evict oldest cache files until *cache_dir* fits *max_bytes*.

    Returns the evicted byte count. Best-effort: unreadable entries are
    skipped, never raised.
    """

    try:
        root = Path(cache_dir).expanduser()
        entries = [
            (path, path.stat())
            for path in root.rglob("*")
            if path.is_file() and not path.name.startswith(".tmp-")
        ]
    except OSError:
        return 0
    total = sum(stat.st_size for _, stat in entries)
    if total <= max_bytes:
        return 0
    entries.sort(key=lambda item: (item[1].st_mtime_ns, item[0].name))
    evicted = 0
    for path, stat in entries:
        if total <= max_bytes:
            break
        try:
            path.unlink()
        except OSError:
            continue
        total -= stat.st_size
        evicted += stat.st_size
    _remove_empty_track_dirs(root)
    return evicted


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
            _atomic_write_text(
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


def _extract_frame_with_digest(
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
        _unlink_quietly(tmp_path)
        return FrameExtractResult(
            path=None, cached=False, error="ffmpeg frame extraction timed out"
        )
    except OSError as exc:
        _unlink_quietly(tmp_path)
        return FrameExtractResult(
            path=None, cached=False, error=f"ffmpeg frame extraction failed: {exc}"
        )
    if result.returncode != 0:
        _unlink_quietly(tmp_path)
        return FrameExtractResult(
            path=None,
            cached=False,
            error=f"ffmpeg frame extraction exited with code {result.returncode}",
        )
    try:
        os.replace(tmp_path, dest)
    except OSError as exc:
        _unlink_quietly(tmp_path)
        return FrameExtractResult(
            path=None, cached=False, error=f"could not publish frame: {exc}"
        )
    enforce_cache_budget(root)
    return FrameExtractResult(path=dest, cached=False, error=None)


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
                _extract_frame_with_digest,
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


def _metadata_payload_path(root: Path, digest: str) -> Path:
    return root / f"meta-{digest}.json"


def _read_cached_metadata_payload(root: Path, digest: str) -> VideoMetadata | None:
    try:
        raw = _metadata_payload_path(root, digest).read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return parse_ffprobe_metadata(payload)
    except Exception:
        return None


def _probe_and_cache_metadata(
    path: str | Path, root: Path, digest: str
) -> VideoMetadata | None:
    if shutil.which("ffprobe") is None:
        return None
    try:
        result = subprocess.run(
            ffprobe_metadata_command(path),
            check=False,
            capture_output=True,
            text=True,
            timeout=_METADATA_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        parsed = parse_ffprobe_metadata(payload)
    except Exception:
        return None
    try:
        _atomic_write_text(
            _metadata_payload_path(root, digest),
            json.dumps(payload, sort_keys=True),
        )
    except OSError:
        pass
    enforce_cache_budget(root)
    return parsed


def _atomic_write_text(dest: Path, text: str) -> None:
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    tmp_handle = tempfile.NamedTemporaryFile(
        dir=str(dest.parent), prefix=".tmp-", suffix=".json", delete=False
    )
    try:
        with tmp_handle:
            tmp_handle.write(text.encode("utf-8"))
        os.replace(tmp_handle.name, dest)
    except OSError:
        _unlink_quietly(Path(tmp_handle.name))
        raise


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
        _unlink_quietly(tmp_path)
        raise


def _remove_empty_track_dirs(root: Path) -> None:
    try:
        children = list(root.iterdir())
    except OSError:
        return
    for child in children:
        if not child.is_dir():
            continue
        try:
            if not any(child.iterdir()):
                child.rmdir()
        except OSError:
            continue


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


__all__ = [
    "FrameExtractResult",
    "ScrubTrack",
    "StoryboardResult",
    "artifact_video_cache_dir",
    "build_storyboard",
    "content_digest_for_path",
    "enforce_cache_budget",
    "extract_frame",
    "metadata_for_frame_service",
    "scrub_fps_for_duration",
    "start_scrub_track",
]
