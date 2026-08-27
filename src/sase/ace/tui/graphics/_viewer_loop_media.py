"""Text and video display helpers for artifact viewer loops."""

from __future__ import annotations

import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ._viewer_loop_terminal import (
    clear_terminal,
    move_cursor_below_image,
    print_artifact_header,
)
from ._viewer_loop_types import (
    ArtifactVideoPlaybackConfig,
    TextDisplayResult,
    VideoDisplayResult,
)
from ._viewer_render import validate_artifact_file_viewer_dependencies
from ._viewer_types import (
    ArtifactFileImageArea,
    ArtifactFileViewerWarning,
    ArtifactFileViewSpec,
)


def artifact_text_viewer_command(path: str | Path) -> list[str]:
    """Build the terminal command for displaying a raw artifact file."""

    expanded = Path(path).expanduser().resolve(strict=False)
    return [sys.executable, "-m", "sase", "pager", "--", str(expanded)]


def artifact_video_player_command(
    path: str | Path,
    image_area: ArtifactFileImageArea,
    config: ArtifactVideoPlaybackConfig | None = None,
) -> list[str]:
    """Build the bounded ``mpv`` command for a terminal video artifact."""

    expanded = Path(path).expanduser().resolve(strict=False)
    video_config = config or ArtifactVideoPlaybackConfig()
    vo = video_config.vo.strip() or "kitty"
    command = [
        "mpv",
        "--no-config",
        f"--vo={vo}",
        "--keep-open=yes",
    ]
    if video_vo_uses_kitty_placement(vo):
        command.extend(
            [
                "--vo-kitty-alt-screen=no",
                "--vo-kitty-config-clear=no",
                f"--vo-kitty-left={max(0, image_area.left)}",
                f"--vo-kitty-top={max(0, image_area.top)}",
                f"--vo-kitty-cols={max(1, image_area.columns)}",
                f"--vo-kitty-rows={max(1, image_area.rows)}",
            ]
        )
    if not video_config.audio:
        command.append("--mute=yes")
    if video_config.loop:
        command.append("--loop-file=inf")
    command.extend(video_config.extra_mpv_args)
    command.extend(["--", str(expanded)])
    return command


def load_artifact_video_playback_config() -> ArtifactVideoPlaybackConfig:
    """Load terminal video playback settings from merged SASE config."""

    try:
        from sase.config import load_merged_config

        merged = load_merged_config()
    except Exception:
        return ArtifactVideoPlaybackConfig()

    if not isinstance(merged, dict):
        return ArtifactVideoPlaybackConfig()
    ace = merged.get("ace", {})
    if not isinstance(ace, dict):
        return ArtifactVideoPlaybackConfig()
    artifact_file_viewer = ace.get("artifact_file_viewer", {})
    if not isinstance(artifact_file_viewer, dict):
        return ArtifactVideoPlaybackConfig()
    raw_video = artifact_file_viewer.get("video", {})
    if not isinstance(raw_video, dict):
        return ArtifactVideoPlaybackConfig()

    return ArtifactVideoPlaybackConfig(
        audio=_coerce_bool(raw_video.get("audio"), default=False),
        loop=_coerce_bool(raw_video.get("loop"), default=False),
        vo=_coerce_str(raw_video.get("vo"), default="kitty"),
        extra_mpv_args=_coerce_mpv_args(raw_video.get("extra_mpv_args")),
    )


def video_vo_uses_kitty_placement(vo: str) -> bool:
    return vo.split(",", 1)[0].strip() == "kitty"


def _coerce_bool(value: object, *, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _coerce_str(value: object, *, default: str) -> str:
    if not isinstance(value, str):
        return default
    stripped = value.strip()
    return stripped or default


def _coerce_mpv_args(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            return tuple(shlex.split(value))
        except ValueError:
            return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if item is not None)
    return ()


def display_text_artifact(
    spec: ArtifactFileViewSpec,
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]],
    *,
    artifact_index: int = 0,
    artifact_count: int = 1,
) -> TextDisplayResult:
    path = Path(spec.path).expanduser().resolve(strict=False)
    if not path.exists():
        warning = ArtifactFileViewerWarning(
            "artifact_not_found",
            "Artifact file not found",
        )
        return TextDisplayResult(warnings=(warning,))
    if not path.is_file():
        warning = ArtifactFileViewerWarning(
            "artifact_not_file",
            "Artifact path is not a file",
        )
        return TextDisplayResult(warnings=(warning,))

    clear_terminal(run_command)
    print_artifact_header(
        spec,
        page_index=0,
        page_count=1,
        artifact_index=artifact_index,
        artifact_count=artifact_count,
    )
    command = tuple(artifact_text_viewer_command(path))
    result = run_command(command)
    if result.returncode != 0:
        tool = Path(command[0]).name if command else None
        warning = ArtifactFileViewerWarning(
            "text_viewer_failed",
            f"{tool or 'text viewer'} failed with exit code {result.returncode}",
            tool=tool,
        )
        return TextDisplayResult(
            command=command,
            returncode=result.returncode,
            warnings=(warning,),
        )
    return TextDisplayResult(command=command, returncode=result.returncode)


def display_video_artifact(
    spec: ArtifactFileViewSpec,
    image_area: ArtifactFileImageArea,
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]],
    *,
    video_config: ArtifactVideoPlaybackConfig,
    artifact_index: int = 0,
    artifact_count: int = 1,
) -> VideoDisplayResult:
    path = Path(spec.path).expanduser().resolve(strict=False)
    if not path.exists():
        warning = ArtifactFileViewerWarning(
            "artifact_not_found",
            "Artifact file not found",
        )
        return VideoDisplayResult(warnings=(warning,))
    if not path.is_file():
        warning = ArtifactFileViewerWarning(
            "artifact_not_file",
            "Artifact path is not a file",
        )
        return VideoDisplayResult(warnings=(warning,))

    warnings = validate_artifact_file_viewer_dependencies("video")
    if warnings:
        return VideoDisplayResult(warnings=warnings)

    clear_terminal(run_command)
    print_artifact_header(
        spec,
        page_index=0,
        page_count=1,
        artifact_index=artifact_index,
        artifact_count=artifact_count,
        media_label="\u25b6 Video",
    )
    move_cursor_below_image(image_area)
    command = tuple(artifact_video_player_command(path, image_area, video_config))
    result = run_command(command)
    move_cursor_below_image(image_area)
    return VideoDisplayResult(command=command, returncode=result.returncode)


def text_viewer_command_needs_quit_key(command: Sequence[str]) -> bool:
    return False
