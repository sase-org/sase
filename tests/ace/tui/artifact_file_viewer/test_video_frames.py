from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from PIL import Image

from sase.ace.tui.graphics import (
    _viewer_video_cache as frame_cache,
    _viewer_video_extract as frame_extract,
    _viewer_video_scrub as frame_scrub,
    _viewer_video_storyboard as frame_storyboard,
)
from sase.ace.tui.graphics._viewer_video_frames import (
    ScrubTrack,
    build_storyboard,
    content_digest_for_path,
    enforce_cache_budget,
    extract_frame,
    metadata_for_frame_service,
    scrub_fps_for_duration,
    start_scrub_track,
)

_FFPROBE_PAYLOAD = {
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 320,
            "height": 240,
            "avg_frame_rate": "10/1",
        }
    ],
    "format": {"duration": "3.000000", "size": "12345"},
}


@pytest.fixture
def fake_video_executables(monkeypatch: pytest.MonkeyPatch) -> None:
    real_which = shutil.which

    def which(name: str) -> str | None:
        if name in {"ffmpeg", "ffprobe"}:
            return f"/usr/bin/{name}"
        return real_which(name)

    monkeypatch.setattr(shutil, "which", which)


def _write_clip(
    tmp_path: Path, name: str = "clip.mp4", *, body: bytes = b"video"
) -> Path:
    video = tmp_path / name
    video.write_bytes(body)
    return video


def _ok_run_factory(
    calls: list[list[str]],
    *,
    payload: dict | None = None,
    write_output: bool = True,
    returncode: int = 0,
) -> object:
    def fake_run(argv: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = list(argv)  # type: ignore[arg-type]
        calls.append(command)
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(payload or _FFPROBE_PAYLOAD), stderr=""
            )
        if command[0] in ("ffmpeg", "nice"):
            if write_output and returncode == 0:
                Path(command[-1]).write_bytes(b"PNG")
            return subprocess.CompletedProcess(
                command, returncode, stdout="", stderr=""
            )
        raise AssertionError(f"unexpected command: {command}")

    return fake_run


def test_extract_frame_command_golden(tmp_path: Path) -> None:
    video = _write_clip(tmp_path)
    dest = tmp_path / "frame.png"

    assert frame_extract._extract_frame_command(video, 1.5, dest, 800) == [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "error",
        "-ss",
        "1.500",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-vf",
        "scale=min(iw\\,800):-2",
        str(dest),
    ]


def test_scrub_track_command_golden(tmp_path: Path) -> None:
    video = _write_clip(tmp_path)

    assert frame_scrub._scrub_track_command(video, "frame-%04d.png", 2.0, 800) == [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-vf",
        "fps=2,scale=min(iw\\,800):-2",
        "-threads",
        "2",
        "frame-%04d.png",
    ]


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (None, 2.0),
        (0.0, 2.0),
        (-5.0, 2.0),
        (6.0, 2.0),
        (120.0, 2.0),
        (240.0, 1.0),
        (480.0, 0.5),
    ],
)
def test_scrub_fps_for_duration(duration: float | None, expected: float) -> None:
    assert scrub_fps_for_duration(duration) == expected


@pytest.mark.parametrize(
    ("duration", "fps", "expected"),
    [
        (None, 2.0, 240),
        (0.0, 2.0, 240),
        (6.0, 2.0, 12),
        (120.0, 2.0, 240),
        (480.0, 0.5, 240),
        (3.0, 2.0, 6),
        (3.0, 0.0, 1),
    ],
)
def test_scrub_frame_count_for_duration(
    duration: float | None, fps: float, expected: int
) -> None:
    assert frame_scrub._scrub_frame_count_for_duration(duration, fps) == expected


def test_content_digest_keys(tmp_path: Path) -> None:
    with frame_cache._DIGEST_CACHE_LOCK:
        frame_cache._DIGEST_CACHE.clear()
    first = _write_clip(tmp_path, "a.mp4", body=b"same")
    second = _write_clip(tmp_path, "b.mp4", body=b"same")
    other = _write_clip(tmp_path, "c.mp4", body=b"different")

    assert content_digest_for_path(first) == content_digest_for_path(second)
    assert content_digest_for_path(first) != content_digest_for_path(other)
    assert content_digest_for_path(tmp_path / "missing.mp4") is None


def test_content_digest_memoizes_per_open_and_invalidates_on_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with frame_cache._DIGEST_CACHE_LOCK:
        frame_cache._DIGEST_CACHE.clear()
    video = _write_clip(tmp_path, "clip.mp4", body=b"x" * 65536)

    opens = {"count": 0}
    real_open = open

    def counting_open(*args: object, **kwargs: object):
        opens["count"] += 1
        return real_open(*args, **kwargs)

    with monkeypatch.context() as isolated:
        isolated.setattr("builtins.open", counting_open)
        first = content_digest_for_path(video)
        assert first is not None
        assert opens["count"] == 1
        # Several exact-step equivalent reads hit the memo, not the disk.
        for _ in range(4):
            assert content_digest_for_path(video) == first
        assert opens["count"] == 1
    # Modifying the file (new size/mtime) must re-hash.
    video.write_bytes(b"y" * 65537)
    second = content_digest_for_path(video)
    assert second is not None and second != first
    # A repeat read of the modified file hits the new memo entry.
    assert content_digest_for_path(video) == second


def test_extract_frame_caches_and_reports_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_video_executables: None,
) -> None:
    video = _write_clip(tmp_path)
    cache = tmp_path / "cache"
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _ok_run_factory(calls, write_output=True))

    first = extract_frame(video, 1.5, 800, cache_dir=cache)
    assert first.ok and not first.cached and first.path is not None
    assert first.path.is_file()
    assert len(calls) == 1

    second = extract_frame(video, 1.5, 800, cache_dir=cache)
    assert second.ok and second.cached and second.path == first.path
    assert len(calls) == 1

    other_width = extract_frame(video, 1.5, 400, cache_dir=cache)
    assert other_width.ok and not other_width.cached
    assert other_width.path != first.path


def test_extract_frame_failed_run_leaves_no_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = _write_clip(tmp_path)
    cache = tmp_path / "cache"
    calls: list[list[str]] = []
    monkeypatch.setattr(
        subprocess, "run", _ok_run_factory(calls, write_output=False, returncode=1)
    )

    result = extract_frame(video, 1.5, 800, cache_dir=cache)
    assert not result.ok and result.path is None and result.error
    leftovers = [path for path in cache.rglob("*") if path.is_file()]
    assert leftovers == []


def test_extract_frame_missing_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = _write_clip(tmp_path)
    real_which = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda name: None if name == "ffmpeg" else real_which(name)
    )

    result = extract_frame(video, 1.0, 800, cache_dir=tmp_path / "cache")
    assert not result.ok and "ffmpeg" in (result.error or "")


def test_enforce_cache_budget_evicts_oldest(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    entries = [("old.png", 1000), ("mid.png", 2000), ("new.png", 3000)]
    for name, stamp in entries:
        path = cache / name
        path.write_bytes(b"x" * 100)
        os.utime(path, (stamp, stamp))

    evicted = enforce_cache_budget(cache, max_bytes=250)

    assert evicted == 100
    assert not (cache / "old.png").exists()
    assert (cache / "mid.png").is_file()
    assert (cache / "new.png").is_file()


def test_storyboard_grid_for_aspect() -> None:
    assert frame_storyboard._storyboard_grid_for_aspect(1200, 400) == (10, 1)
    assert frame_storyboard._storyboard_grid_for_aspect(800, 600) == (5, 2)
    assert frame_storyboard._storyboard_grid_for_aspect(0, 0) == (5, 2)


def _write_synthetic_frames(tmp_path: Path) -> list[Path]:
    sources: list[Path] = []
    for index in range(10):
        path = tmp_path / f"cell-{index:02d}.png"
        Image.new("RGB", (160, 90), (20 * index, 100, 200 - 10 * index)).save(path)
        sources.append(path)
    return sources


def test_build_storyboard_from_synthetic_frames(tmp_path: Path) -> None:
    video = _write_clip(tmp_path)
    cache = tmp_path / "cache"
    sources = _write_synthetic_frames(tmp_path)

    result = build_storyboard(
        video,
        7.0,
        800,
        strip_width_px=1000,
        strip_height_px=300,
        cache_dir=cache,
        source_frames=sources,
    )

    assert result.ok and result.cells == 10 and result.path is not None
    with Image.open(result.path) as board:
        assert board.size == (1000, 300)
        assert board.mode == "RGB"
        assert board.getbbox() is not None

    cached = build_storyboard(
        video,
        7.0,
        800,
        strip_width_px=1000,
        strip_height_px=300,
        cache_dir=cache,
        source_frames=sources,
    )
    assert cached.ok and cached.cached and cached.path == result.path


def test_build_storyboard_narrow_strip_uses_two_rows(tmp_path: Path) -> None:
    video = _write_clip(tmp_path)
    sources = _write_synthetic_frames(tmp_path)

    result = build_storyboard(
        video,
        7.0,
        800,
        strip_width_px=800,
        strip_height_px=600,
        cache_dir=tmp_path / "cache",
        source_frames=sources,
    )

    assert result.ok and result.path is not None
    with Image.open(result.path) as board:
        assert board.size == (800, 600)


def test_build_storyboard_rejects_bad_inputs(tmp_path: Path) -> None:
    video = _write_clip(tmp_path)
    cache = tmp_path / "cache"

    assert not build_storyboard(
        video, None, 800, strip_width_px=1000, strip_height_px=300, cache_dir=cache
    ).ok

    sources = _write_synthetic_frames(tmp_path)
    short = build_storyboard(
        video,
        7.0,
        800,
        strip_width_px=1000,
        strip_height_px=300,
        cache_dir=cache,
        source_frames=sources[:3],
    )
    assert not short.ok and short.cells == 0


class _FakeProc:
    def __init__(self) -> None:
        self.killed = False
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int | None:
        return self.returncode


def test_scrub_track_cancel_kills_process(
    tmp_path: Path, fake_video_executables: None
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    seen: list[list[str]] = []
    procs: list[_FakeProc] = []

    def fake_popen(argv: object, **kwargs: object) -> _FakeProc:
        seen.append(list(argv))  # type: ignore[arg-type]
        proc = _FakeProc()
        procs.append(proc)
        return proc

    track = ScrubTrack(
        video_path=tmp_path / "clip.mp4",
        digest="abc123",
        duration_seconds=5.0,
        max_pixel_width=800,
        cache_dir=cache,
        popen_factory=fake_popen,
    )
    track.start()

    assert len(procs) == 1
    assert "ffmpeg" in seen[0]
    assert not track.done

    track.cancel()

    assert procs[0].killed
    assert track.done


def test_scrub_track_reuses_completed_cache(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    digest = "deadbeef"
    track = ScrubTrack(
        video_path=tmp_path / "clip.mp4",
        digest=digest,
        duration_seconds=5.0,
        max_pixel_width=800,
        cache_dir=cache,
    )
    track.track_dir.mkdir(parents=True)
    names = [f"frame-{index:04d}.png" for index in range(1, 11)]
    for name in names:
        (track.track_dir / name).write_bytes(b"PNG")
    (track.track_dir / "index.json").write_text(
        json.dumps(
            {"digest": digest, "fps": 2.0, "max_pixel_width": 800, "frames": names}
        )
    )

    spawned: list[list[str]] = []
    reuse = ScrubTrack(
        video_path=tmp_path / "clip.mp4",
        digest=digest,
        duration_seconds=5.0,
        max_pixel_width=800,
        cache_dir=cache,
        popen_factory=lambda argv, **kwargs: spawned.append(list(argv)),  # type: ignore[arg-type]
    )
    reuse.start()

    assert spawned == []
    assert reuse.done
    assert reuse.progress == 1.0
    assert reuse.nearest(0.0) == track.track_dir / "frame-0001.png"
    assert reuse.nearest(0.6) == track.track_dir / "frame-0002.png"
    assert reuse.nearest(100.0) == track.track_dir / "frame-0010.png"


def test_scrub_track_failed_process_reports_error(
    tmp_path: Path, fake_video_executables: None
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()

    class _FailedProc(_FakeProc):
        def __init__(self) -> None:
            super().__init__()
            self.returncode = 1

    track = ScrubTrack(
        video_path=tmp_path / "clip.mp4",
        digest="abc123",
        duration_seconds=5.0,
        max_pixel_width=800,
        cache_dir=cache,
        popen_factory=lambda argv, **kwargs: _FailedProc(),
    )
    track.start()

    assert track.done
    assert track.error and "code 1" in track.error
    assert track.nearest(1.0) is None


def test_metadata_service_caches_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_video_executables: None,
) -> None:
    from sase.ace.tui.graphics._viewer_video_media import VideoMetadata

    video = _write_clip(tmp_path)
    cache = tmp_path / "cache"
    calls: list[list[str]] = []

    explicit = VideoMetadata(duration_seconds=9.0)
    assert metadata_for_frame_service(video, metadata=explicit) is explicit

    monkeypatch.setattr(subprocess, "run", _ok_run_factory(calls))

    first = metadata_for_frame_service(video, cache_dir=cache)
    assert first is not None and first.duration_seconds == 3.0
    assert first.codec == "h264"
    assert (cache / f"meta-{content_digest_for_path(video)}.json").is_file()
    assert len(calls) == 1

    def _boom(argv: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("live probe must not run on a cache hit")

    monkeypatch.setattr(subprocess, "run", _boom)
    second = metadata_for_frame_service(video, cache_dir=cache)
    assert second == first


def test_metadata_service_live_fallback_without_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_video_executables: None,
) -> None:
    video = _write_clip(tmp_path)
    monkeypatch.setattr(subprocess, "run", _ok_run_factory([]))

    metadata = metadata_for_frame_service(video)
    assert metadata is not None and metadata.width == 320


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_real_ffmpeg_frame_scrub_and_storyboard(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    generated = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=320x240:rate=10",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            str(clip),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert generated.returncode == 0, generated.stderr
    cache = tmp_path / "cache"

    metadata = metadata_for_frame_service(clip, cache_dir=cache)
    duration = metadata.duration_seconds if metadata else 3.0
    assert duration is not None and duration > 0

    frame = extract_frame(clip, 1.0, 320, cache_dir=cache)
    assert frame.ok and frame.path is not None and frame.path.is_file()
    with Image.open(frame.path) as still:
        assert still.width <= 320

    track = start_scrub_track(clip, duration, 320, cache_dir=cache)
    assert track is not None
    deadline = time.monotonic() + 60
    while not track.done and time.monotonic() < deadline:
        time.sleep(0.2)  # sase-test-wait: poll background scrub-track ffmpeg until done
    assert track.done, track.error
    assert track.error is None
    assert track.progress == 1.0
    scrubbed = track.nearest(1.0)
    assert scrubbed is not None and scrubbed.is_file()

    board = build_storyboard(
        clip,
        duration,
        320,
        strip_width_px=1000,
        strip_height_px=300,
        cache_dir=cache,
        scrub_track=track,
    )
    assert board.ok and board.cells == 10 and board.path is not None
    with Image.open(board.path) as composed:
        assert composed.size == (1000, 300)
