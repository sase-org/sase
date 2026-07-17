"""Shared types for terminal artifact viewer loops."""

from __future__ import annotations

from dataclasses import dataclass

from ._viewer_types import ArtifactFileViewerWarning


@dataclass(frozen=True)
class PageLoopResult:
    """Terminal page loop subprocess status."""

    returncode: int = 0
    warnings: tuple[ArtifactFileViewerWarning, ...] = ()


@dataclass(frozen=True)
class TextDisplayResult:
    """Terminal text viewer subprocess status."""

    command: tuple[str, ...] = ()
    returncode: int = 0
    warnings: tuple[ArtifactFileViewerWarning, ...] = ()


@dataclass(frozen=True)
class ArtifactVideoPlaybackConfig:
    """Runtime settings for terminal video artifact playback."""

    audio: bool = False
    loop: bool = False
    vo: str = "kitty"
    extra_mpv_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class VideoDisplayResult:
    """Terminal video player subprocess status."""

    command: tuple[str, ...] = ()
    returncode: int = 0
    warnings: tuple[ArtifactFileViewerWarning, ...] = ()
