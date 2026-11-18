"""Shared helpers for video inspect tests.

Split from ``tests.ace.tui.artifact_file_viewer.test_video_inspect``.
Helpers use public names so focused test modules can import them without
touching a ``_``-prefixed symbol across files.
"""

from __future__ import annotations

from pathlib import Path


class FakeScrub:
    def __init__(
        self,
        *,
        done: bool = True,
        fps: float = 1.0,
        frames: tuple[Path, ...] = (),
        progress: float = 1.0,
    ) -> None:
        self.done = done
        self.fps = fps
        self.frame_paths = frames
        self.progress = progress
        self.cancelled = False

    def nearest(self, at_seconds: float) -> Path | None:
        if not self.frame_paths:
            return None
        index = int(round(float(at_seconds) * self.fps))
        index = max(0, min(index, len(self.frame_paths) - 1))
        return self.frame_paths[index]

    def cancel(self) -> None:
        self.cancelled = True


def write_clip(tmp_path: Path, name: str = "clip.mp4") -> Path:
    video = tmp_path / name
    video.write_bytes(b"video")
    return video
