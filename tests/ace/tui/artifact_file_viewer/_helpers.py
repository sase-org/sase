from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sase.ace.tui.graphics._viewer_video_frames import (
    FrameExtractResult,
    StoryboardResult,
)
from sase.ace.tui.graphics._viewer_video_media import VideoMetadata
from sase.ace.tui.graphics.viewer import ArtifactFileImageArea, kitten_icat_command


_TEST_IMAGE_AREA = ArtifactFileImageArea(columns=90, rows=24)
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(value: str) -> str:
    return _ANSI_RE.sub("", value)


def _test_icat_command(page: Path) -> list[str]:
    return kitten_icat_command(page, _TEST_IMAGE_AREA)


def _tmux_which(tool: str) -> str | None:
    return f"/usr/bin/{tool}" if tool == "tmux" else None


# Public aliases for the split video-inspect test modules, which must not
# import ``_``-prefixed names across files. Existing importers of the
# ``_``-prefixed names keep working unchanged.
TEST_IMAGE_AREA = _TEST_IMAGE_AREA
strip_ansi = _strip_ansi
test_icat_command = _test_icat_command


def _patch_tmux_which(monkeypatch, which=_tmux_which) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_tmux_common.shutil.which",
        which,
    )


def _patch_tmux_run(monkeypatch, fake_run) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_tmux_common.subprocess.run",
        fake_run,
    )


def stub_video_inspect_service(
    monkeypatch: Any,
    tmp_path: Path,
    *,
    duration: float = 7.0,
    fps: float = 30.0,
    scrub: Any = None,
    storyboard: bool = True,
) -> dict[str, Any]:
    """Stub the inspect-view frame service so tests never shell out to ffmpeg."""

    cache = tmp_path / "artifact-video-cache"
    cache.mkdir(parents=True, exist_ok=True)
    extracts: list[float] = []
    storyboards: list[Path] = []

    def fake_extract(path: object, at_seconds: float, max_px: int, **kwargs: object):
        del path, kwargs
        extracts.append(float(at_seconds))
        dest = cache / f"frame-{at_seconds:.3f}-w{max_px}.png"
        dest.write_bytes(b"PNG")
        return FrameExtractResult(path=dest, cached=False, error=None)

    def fake_metadata(path: object, **kwargs: object) -> VideoMetadata:
        del path, kwargs
        return VideoMetadata(
            duration_seconds=duration,
            width=640,
            height=360,
            fps=fps,
            codec="h264",
            size_bytes=1234,
        )

    def fake_storyboard(*args: object, **kwargs: object) -> StoryboardResult:
        del args, kwargs
        dest = cache / "storyboard.png"
        dest.write_bytes(b"BOARD")
        storyboards.append(dest)
        if not storyboard:
            return StoryboardResult(path=None, cached=False, cells=0, error="skipped")
        return StoryboardResult(path=dest, cached=False, cells=10, error=None)

    def fake_scrub(*args: object, **kwargs: object) -> Any:
        del args, kwargs
        return scrub

    def fake_which(tool: str) -> str | None:
        return f"/usr/bin/{tool}"

    session_target = "sase.ace.tui.graphics._viewer_loop_video_session"
    view_target = "sase.ace.tui.graphics._viewer_loop_video_view"
    monkeypatch.setattr(f"{session_target}.kitty_graphics_capable", lambda **_k: True)
    monkeypatch.setattr(f"{session_target}.extract_frame", fake_extract)
    monkeypatch.setattr(f"{session_target}.metadata_for_frame_service", fake_metadata)
    monkeypatch.setattr(f"{session_target}.build_storyboard", fake_storyboard)
    monkeypatch.setattr(f"{session_target}.start_scrub_track", fake_scrub)
    monkeypatch.setattr(
        f"{session_target}.artifact_video_cache_dir", lambda **_k: cache
    )
    monkeypatch.setattr(
        f"{session_target}.terminal_pixel_size", lambda **_k: (1600, 900)
    )
    monkeypatch.setattr(f"{session_target}.shutil.which", fake_which)
    monkeypatch.setattr(
        f"{session_target}.content_digest_for_path", lambda _p: "digest"
    )
    monkeypatch.setattr(f"{view_target}.enforce_cache_budget", lambda *_a, **_k: 0)
    monkeypatch.setattr(f"{session_target}.scrub_fps_for_duration", lambda _d: 2.0)
    return {
        "cache": cache,
        "extracts": extracts,
        "storyboards": storyboards,
    }


def _tmux_split_env(cmd: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    index = 0
    while index < len(cmd) - 1:
        if cmd[index] == "-e":
            key, _, value = cmd[index + 1].partition("=")
            env[key] = value
            index += 2
            continue
        index += 1
    return env
